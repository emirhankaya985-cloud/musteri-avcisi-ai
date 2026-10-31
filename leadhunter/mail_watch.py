"""Read-only Gmail IMAP delivery feedback -> existing private Postgres mail ledger.

Does NOT send SMTP or edit Gmail. Never treats acceptance as inbox delivery.
Only strict automated bounce senders and known frozen recipients are considered.
"""
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import imaplib
import json
import os
import re
import ssl

from .review_private import connect_private_database
from .telegram_buttons import api

BOUNCE_SENDERS = {
    "mailer-daemon@googlemail.com", "mailer-daemon@gmail.com",
    "postmaster@googlemail.com",
}
FAILURE = re.compile(r"failure|failed|undeliver|not delivered|teslim edilemedi", re.I)
DELAY = re.compile(r"delay|delayed|gecik", re.I)


def bounce_feedback(raw):
    """One trusted RFC822 DSN -> (recipient text, delivery status), or None."""
    if len(raw) > 500_000:
        return None
    message = BytesParser(policy=policy.default).parsebytes(raw)
    sender = parseaddr(str(message.get("From", "")))[1].lower()
    subject = str(message.get("Subject", ""))
    if sender not in BOUNCE_SENDERS:
        return None
    if FAILURE.search(subject):
        state = "failed"
    elif DELAY.search(subject):
        state = "delayed"
    else:
        return None
    pieces = []
    for part in message.walk():
        if part.get_content_type() == "message/delivery-status":
            for block in part.get_payload() if isinstance(part.get_payload(), list) else []:
                pieces.extend(str(block.get(k, "")) for k in ("Final-Recipient", "Original-Recipient"))
        elif part.get_content_type() == "text/plain":
            try:
                pieces.append(part.get_content())
            except (TypeError, UnicodeError, LookupError):
                continue
    evidence = "\n".join(pieces).casefold()
    return (evidence[:200_000], state) if evidence else None


def reply_feedback(raw):
    """Candidate reply metadata only; full text must never enter private ledger."""
    if len(raw) > 500_000:
        return None
    message = BytesParser(policy=policy.default).parsebytes(raw)
    sender = parseaddr(str(message.get("From", "")))[1].strip().casefold()
    refs = str(message.get("In-Reply-To", "")) + " " + str(
        message.get("References", ""))
    if (not sender or sender in BOUNCE_SENDERS or
            not refs.strip() or "@" not in sender or len(refs) > 20_000):
        return None
    return sender, "reply:" + refs.casefold()


def read_delivery_messages(env, imap_factory=None, days=35):
    """Gmail readonly EXAMINE/UID fetch: no email mutations."""
    address = env.get("GMAIL_SENDER_ADDRESS")
    password = env.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise RuntimeError("Read-only Gmail credentials not configured")
    factory = imap_factory or imaplib.IMAP4_SSL
    imap = None
    try:
        imap = factory("imap.gmail.com", 993, ssl_context=ssl.create_default_context(), timeout=20)
        status, _ = imap.login(address, password)
        if status != "OK":
            raise RuntimeError("Read-only Gmail authentication unavailable")
        status, _ = imap.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Read-only Gmail inbox unavailable")
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = imap.uid("SEARCH", None, "SINCE", cutoff)
        if status != "OK":
            raise RuntimeError("Gmail search unavailable")
        uids = (data[0] or b"").split()[-200:]
        results = []
        for uid in uids:
            status, result = imap.uid("FETCH", uid, "(RFC822)")
            if status != "OK":
                raise RuntimeError("Gmail read failed")
            raw = next((part[1] for part in result if isinstance(part, tuple)
                        and isinstance(part[1], bytes)), None)
            if raw is not None:
                feedback = bounce_feedback(raw) or reply_feedback(raw)
                if feedback:
                    results.append(feedback)
        return results
    except Exception:
        raise RuntimeError("Read-only Gmail delivery watch failed; credentials redacted") from None
    finally:
        if imap is not None:
            try:
                imap.logout()
            except Exception:
                pass


def reconcile_mail(conn, notices):
    """Add feedback without changing any accepted/sending/uncertain claim."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(789654322)")
            cur.execute(
                "SELECT osm_id, lead_data FROM owner_leads WHERE "
                "lead_data->'_auto_mail'->>'state' IN ('accepted','sending','uncertain') "
                "FOR UPDATE")
            records = cur.fetchall()
            changed = 0
            for lead_id, data in records:
                value = json.loads(data) if isinstance(data, str) else data
                record = value.get("_auto_mail") or {}
                recipient = str(record.get("recipient") or "").strip().casefold()
                if not recipient:
                    continue
                state = None
                for evidence, candidate in notices:
                    # Trust only a message from an automated Gmail sender
                    # whose DSN evidence explicitly contains a frozen recipient.
                    if re.search(r"(?<![\w.+-])" + re.escape(recipient) + r"(?![\w.+-])", evidence):
                        if candidate == "failed":
                            state = "failed"
                            break
                        state = state or "delayed"
                # A reply requires an exact sender-to-recipient match AND
                # an RFC822 In-Reply-To/References header tied to our own
                # frozen outgoing Message-ID. Merely sharing a sender is not
                # enough to count an unrelated message as a business reply.
                mail_id = str(record.get("id") or "").casefold()
                has_reply = any(
                    candidate.startswith("reply:") and
                    evidence == recipient and len(mail_id) >= 12 and
                    ("<" + mail_id + "@") in candidate
                    for evidence, candidate in notices)
                if has_reply and not record.get("reply_feedback"):
                    reply_data = {"state": "sender_matched_reply",
                                  "observed_at": datetime.now(timezone.utc).isoformat()}
                    cur.execute(
                        "UPDATE owner_leads SET lead_data=jsonb_set("
                        "lead_data,'{_auto_mail,reply_feedback}',%s::jsonb,true),"
                        "updated_at=now() WHERE osm_id=%s AND "
                        "lead_data->'_auto_mail'->>'state' IN ('accepted','sending','uncertain')",
                        (json.dumps(reply_data), lead_id))
                    changed += 1
                before = record.get("delivery_feedback") or {}
                if not state or before.get("state") == "failed" or (
                        before.get("state") == state):
                    continue
                feedback = {"state": state, "observed_at": datetime.now(
                    timezone.utc).isoformat()}
                cur.execute(
                    "UPDATE owner_leads SET lead_data=jsonb_set("
                    "lead_data,'{_auto_mail,delivery_feedback}',%s::jsonb,true),"
                    "updated_at=now() WHERE osm_id=%s AND "
                    "lead_data->'_auto_mail'->>'state' IN ('accepted','sending','uncertain')",
                    (json.dumps(feedback), lead_id))
                changed += 1
            cur.execute(
                "SELECT osm_id, lead_data->'_auto_mail'->'delivery_feedback' "
                "FROM owner_leads WHERE lead_data->'_auto_mail'->"
                "'delivery_feedback' IS NOT NULL")
            pending = []
            for lead_id, feedback in cur.fetchall():
                status = json.loads(feedback) if isinstance(feedback, str) else feedback
                if status and not status.get("telegram_message_id"):
                    pending.append((lead_id, status["state"]))
            cur.execute(
                "SELECT osm_id, lead_data->'_auto_mail'->'reply_feedback' "
                "FROM owner_leads WHERE lead_data->'_auto_mail'->"
                "'reply_feedback' IS NOT NULL")
            for lead_id, feedback in cur.fetchall():
                status = json.loads(feedback) if isinstance(feedback, str) else feedback
                if status and not status.get("telegram_message_id"):
                    pending.append((lead_id, "reply"))
    return changed, pending


def deliver_pending(conn, pending, env, opener=None):
    if not pending:
        return 0
    if not env.get("TELEGRAM_BOT_TOKEN") or not str(
            env.get("TELEGRAM_CHAT_ID") or "").isdigit():
        raise RuntimeError("Owner Telegram credentials missing")
    failed = sum(state == "failed" for _, state in pending)
    delayed = sum(state == "delayed" for _, state in pending)
    replied = sum(state == "reply" for _, state in pending)
    text = (
        "📮 Müşteri Avcısı — Gmail teslimat kontrolü\n"
        f"🔴 Başarısız teslimat bildirimi: {failed}\n"
        f"🟡 Gecikme bildirimi: {delayed}\n"
        f"📨 Kayıtlı gönderimle eşleşen yanıt: {replied}\n"
        "⛔ Aynı alıcıya otomatik tekrar gönderim YOK.\n"
        "ℹ️ Bunlar yalnızca Gmail'in bildirimleri; SMTP kabul geçmişi korunur.\n"
        "📊 Ayrıntılı toplamlar için /eposta")
    if opener is None:
        result = api(env["TELEGRAM_BOT_TOKEN"], "sendMessage", {
            "chat_id": env["TELEGRAM_CHAT_ID"], "text": text})
    else:
        result = api(env["TELEGRAM_BOT_TOKEN"], "sendMessage", {
            "chat_id": env["TELEGRAM_CHAT_ID"], "text": text}, opener)
    message_id = result.get("message_id") if isinstance(result, dict) else None
    if type(message_id) is not int or message_id <= 0:
        raise RuntimeError("Owner-only delivery receipt missing")
    with conn.transaction():
        with conn.cursor() as cur:
            for lead_id, kind in pending:
                path = ("{_auto_mail,reply_feedback,telegram_message_id}" if
                        kind == "reply" else
                        "{_auto_mail,delivery_feedback,telegram_message_id}")
                parent = "reply_feedback" if kind == "reply" else "delivery_feedback"
                cur.execute(
                    "UPDATE owner_leads SET lead_data=jsonb_set("
                    "lead_data,%s::text[],%s::jsonb,true) WHERE osm_id=%s AND "
                    "lead_data->'_auto_mail'->%s IS NOT NULL AND "
                    "NOT (lead_data->'_auto_mail'->%s ? 'telegram_message_id')",
                    (path.strip("{}").split(","), json.dumps(message_id),
                     lead_id, parent, parent))
    return message_id


def run(env=None, imap_factory=None, opener=None):
    env = os.environ if env is None else env
    notices = read_delivery_messages(env, imap_factory=imap_factory)
    db = connect_private_database(env.get("REVIEW_DATABASE_URL"))
    try:
        changed, pending = reconcile_mail(db, notices)
        receipt = deliver_pending(db, pending, env, opener)
    finally:
        db.close()
    print(f"MAIL_WATCH: private_feedback_updated={changed}; "
          f"owner_alert_receipt_confirmed={bool(receipt)}; business_mail_sent=0")
    return changed, receipt


if __name__ == "__main__":
    try:
        run()
    except Exception:
        raise RuntimeError("Private Gmail watch failed; sensitive details redacted") from None
