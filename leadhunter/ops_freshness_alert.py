"""At-most-once owner Telegram alert for a failed operational freshness check.

Read-only classification and one private incident receipt; no customer contact.
The Neon-unavailable fallback cannot deduplicate across separate GitHub runs.
"""
import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .ops_freshness import classify, classify_source
from .review_private import connect_private_database
from .telegram_buttons import api, credentials


def _send(messenger, token, chat, text):
    try:
        response = messenger(token, "sendMessage", {
            "chat_id": chat, "text": text, "disable_web_page_preview": True})
        mid = response.get("message_id") if isinstance(response, dict) else None
        if type(mid) is not int or mid <= 0:
            raise ValueError("Missing Telegram receipt")
        return mid
    except Exception:
        # Provider errors can contain the token-bearing request URL.
        raise RuntimeError("Owner Telegram alert receipt unverified; credentials redacted") from None


def send_once(env=None, connection=None, messenger=api, output=print, now=None):
    env = os.environ if env is None else env
    now = datetime.now(timezone.utc) if now is None else now
    if now.tzinfo is None:
        raise ValueError("Aware time required")
    run_id = str(env.get("GITHUB_RUN_ID", ""))
    if not re.fullmatch(r"[0-9]{6,24}", run_id):
        raise RuntimeError("Verified GitHub run ID required")
    token, chat = credentials(env)
    local = now.astimezone(ZoneInfo("Europe/Istanbul"))
    stamp = local.strftime("%Y-%m-%d %H:%M TRT")
    link = ("https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/"
            "actions/runs/" + run_id)
    own = connection is None
    try:
        db = connection if connection is not None else connect_private_database(
            env.get("REVIEW_DATABASE_URL"))
    except Exception:
        # No Neon ledger available to deduplicate between different runs.
        # Send a bounded owner-only alarm for this one failed workflow run.
        _send(messenger, token, chat,
              "🔴 Müşteri Avcısı AI — Neon bağlantısı doğrulanamadı.\n"
              f"Zaman: {stamp}\nOlay: {run_id}\nEtkilenen: CRM / izleme\n"
              f"Kanıt: {link}\nBu iş müşteri e-postası göndermez.")
        output("OPS_ALERT: neon_unavailable=1; owner_api_accepted=1; "
               "cross_run_dedup_unavailable=1; business_mail_sent=0")
        return True
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT max(recorded_at) FROM owner_scan_attempts "
                "WHERE outcome IN ('success','partial','skipped')")
            scan = cur.fetchone()[0]
            cur.execute("SELECT max(created_at) FROM owner_mail_watch_runs")
            gmail = cur.fetchone()[0]
            cur.execute(
                "SELECT greatest("
                "coalesce((SELECT max(source_data_at) FROM "
                "owner_osm_tile_snapshot_provenance),'epoch'::timestamptz),"
                "coalesce((SELECT max(source_data_at) FROM "
                "owner_osm_incremental_runs),'epoch'::timestamptz))")
            source = cur.fetchone()[0]
        states = classify(scan, gmail, now=now)
        states["source"] = classify_source(source, now=now)
        bad = [name for name in ("scan", "gmail", "source")
               if states[name] != "fresh"]
        if not bad:
            output("OPS_ALERT: no_current_incident=1; business_mail_sent=0")
            return False
        key = "ops_freshness_" + local.strftime("%Y%m%d") + "_" + "_".join(bad)
        with db.transaction():
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO owner_telegram_alert_acceptance (test_key,state) "
                    "VALUES (%s,'reserved') ON CONFLICT DO NOTHING RETURNING test_key",
                    (key,))
                acquired = cur.fetchone() is not None
        if not acquired:
            output("OPS_ALERT: already_claimed=1; duplicate_sent=0")
            return False
        labels = {"scan": "Tarama", "gmail": "Gmail",
                  "source": "OSM kaynağı"}
        terms = {"stale": "gecikmiş", "unverified": "doğrulanamadı",
                 "stale_or_unverified": "güncelliği doğrulanamadı"}
        reason = ", ".join(labels[n] + ": " + terms.get(states[n], "hata")
                           for n in bad)
        msg = ("🔴 Müşteri Avcısı AI — kritik otomasyon hatası\n"
               f"Zaman: {stamp}\nOlay: {run_id}\nNeden: {reason}\n"
               f"Kanıt: {link}\nBu kontrol müşteri e-postası göndermez.")
        state, mid = "failed", None
        try:
            mid = _send(messenger, token, chat, msg)
            state = "api_accepted"
        finally:
            with db.transaction():
                with db.cursor() as cur:
                    cur.execute(
                        "UPDATE owner_telegram_alert_acceptance SET state=%s,"
                        "api_message_id=%s,verified_at=now() "
                        "WHERE test_key=%s AND state='reserved'",
                        (state, mid, key))
        output("OPS_ALERT: owner_api_accepted=1; duplicate_sent=0; "
               "business_mail_sent=0")
        return True
    finally:
        if own:
            db.close()


if __name__ == "__main__":
    send_once()
