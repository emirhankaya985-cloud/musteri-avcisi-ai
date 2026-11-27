"""Once-daily owner Telegram metrics + private CRM workbook delivery.

Read-only CRM aggregates. One reserved day never sends twice, even if Telegram
accepted a document/message but the database confirmation subsequently failed.
No customer SMTP; contact data stays in the private workbook sent to owner DM.
"""
import json
import hashlib
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .recipient_eligibility import eligible_recipient
from .review_private import connect_private_database
from .telegram_buttons import api

ZONE = ZoneInfo("Europe/Istanbul")
DISTRICT_MANIFEST = "data/osm_boundary_manifest_v2026.11.0.json"


def report_day(env=None, now=None):
    """Attribute delayed scheduled jobs to their 20:59 UTC intended date.

    20:59 UTC is 23:59 Europe/Istanbul all year. Using the actual local
    date alone incorrectly credited a 00:23 TRT late run to the next day.
    """
    env = os.environ if env is None else env
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    if env.get("GITHUB_EVENT_NAME") == "schedule":
        due = datetime.combine(now.date(), time(20,59),tzinfo=timezone.utc)
        return (now.date() if now >= due else
                (now - timedelta(days=1)).date()).isoformat()
    return now.astimezone(ZONE).date().isoformat()


def aggregate(conn, day):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*),"
            "count(*) FILTER (WHERE (first_seen_at AT TIME ZONE 'Europe/Istanbul')::date=%s::date),"
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->>'state'='accepted' "
            "OR lead_data->'_mail'->>'state'='accepted'),"
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->'delivery_feedback'->>'state'='failed'),"
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->'delivery_feedback'->>'state'='delayed'),"
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->'reply_feedback'->>'state'='sender_matched_reply'),"
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->>'state'='duplicate'),"
            "count(*) FILTER (WHERE (lead_data->'_auto_mail'->>'claimed_day'=%s "
            "AND lead_data->'_auto_mail'->>'state'='accepted') OR "
            "(lead_data->'_mail'->>'claimed_day'=%s "
            "AND lead_data->'_mail'->>'state'='accepted')) "
            "FROM owner_leads", (day, day, day))
        total, new, accepted, failed, delayed, replies, duplicate, accepted_today = cur.fetchone()
        cur.execute(
            "SELECT count(*),sum(scanned_count),sum(new_registered),"
            "sum(new_addresses),sum(new_mx) "
            "FROM owner_scan_run_metrics WHERE report_day=%s::date", (day,))
        measured_runs, inspected, registered_runs, found_addresses, checked_mx = cur.fetchone()
        cur.execute("SELECT to_regclass('owner_scan_attempts') IS NOT NULL")
        scan_attempts_available = bool(cur.fetchone()[0])
        if scan_attempts_available:
            cur.execute(
                "SELECT count(*),count(*) FILTER (WHERE outcome IN ('failure','partial','cancelled') "
                "OR mirror_outcome='failure') FROM owner_scan_attempts "
                "WHERE (recorded_at AT TIME ZONE 'Europe/Istanbul')::date=%s::date", (day,))
            measured_scan_attempts, system_errors = cur.fetchone()
        else:
            measured_scan_attempts, system_errors = None, None
        cur.execute(
            "SELECT count(*) FROM owner_leads WHERE "
            "(first_seen_at AT TIME ZONE 'Europe/Istanbul')::date=%s::date "
            "AND coalesce(lead_data->>'email','')<>''", (day,))
        # This is an independent CRM total, not necessarily fully
        # represented in the newly instrumented hourly scan ledger.
        registered_day_addresses = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FILTER (WHERE kind='failed'),"
            "count(*) FILTER (WHERE kind='delayed'),"
            "count(*) FILTER (WHERE kind='reply') "
            "FROM owner_mail_notice_metrics WHERE report_day=%s::date",(day,))
        today_failed_notices,today_delays,today_replies = cur.fetchone()
        cur.execute("SELECT count(*) FROM owner_mail_watch_runs "
                    "WHERE report_day=%s::date",(day,))
        measured_watches = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FILTER (WHERE left(lead_data#>>'{email_research,checked_at}',10)=%s "
            "AND lead_data#>>'{email_research,status}'='public_address_found'),"
            "count(*) FILTER (WHERE left(lead_data#>>'{email_research,checked_at}',10)=%s "
            "AND lead_data#>>'{email_research,status}'='no_unique_public_address'),"
            "count(*) FILTER (WHERE left(lead_data#>>'{email_research,checked_at}',10)=%s) "
            "FROM owner_leads", (day,day,day))
        researched_emails, new_public_addresses, no_public_address = cur.fetchone()
        cur.execute("SELECT to_regclass('owner_lead_lifecycle_state')")
        lifecycle_ready = cur.fetchone()[0] is not None
        lifecycle_stages = {}
        if lifecycle_ready:
            cur.execute(
                "SELECT current_stage,count(*) FROM owner_lead_lifecycle_state "
                "GROUP BY current_stage")
            lifecycle_stages = {stage: int(count) for stage, count in cur.fetchall()}
        cur.execute("SELECT lead_data FROM owner_leads WHERE status='review' "
                    "AND lead_data->'_auto_mail'->>'state'='draft'")
        candidates = cur.fetchall()
    eligible = 0
    for (raw,) in candidates:
        lead = json.loads(raw) if isinstance(raw, str) else raw
        recipient = (lead.get('_auto_mail') or {}).get('recipient')
        if recipient and eligible_recipient(lead, recipient):
            eligible += 1
    return dict(total=int(total),new=int(new),accepted=int(accepted),
                failed=int(failed),delayed=int(delayed),replies=int(replies),
                duplicate=int(duplicate),accepted_today=int(accepted_today),
                eligible=eligible, measured_runs=int(measured_runs),
                measured_scan_attempts=(int(measured_scan_attempts)
                                        if measured_scan_attempts is not None else None),
                system_errors=(int(system_errors) if measured_scan_attempts is not None else None),
                inspected=None if inspected is None else int(inspected),
                found_addresses=None if found_addresses is None else int(found_addresses),
                checked_mx=None if checked_mx is None else int(checked_mx),
                registered_day_addresses=int(registered_day_addresses),
                registered_runs=None if registered_runs is None else int(registered_runs),
                measured_watches=int(measured_watches),
                today_failed_notices=int(today_failed_notices) if measured_watches else None,
                today_delays=int(today_delays) if measured_watches else None,
                today_replies=int(today_replies) if measured_watches else None,
                email_research_count=int(researched_emails),
                new_public_addresses=int(new_public_addresses),
                email_research_no_address=int(no_public_address),
                lifecycle_stages=lifecycle_stages,
                lifecycle_recorded=sum(lifecycle_stages.values()))


def compose(day, counts, enabled):
    paused = counts['accepted'] >= 10 and counts['failed'] * 100 >= counts['accepted'] * 15
    live = enabled and not paused and counts['eligible'] > 0
    reason = ('Geçmiş teslimat hata oranı / itibar koruması'
              if paused else 'Doğrulanmış uygun alıcı yok'
              if counts['eligible'] == 0 else 'Çalışma izni/config kapalı'
              if not enabled else 'Uygunluk ve itibar ön denetimleri sağlandı')
    inspected = counts.get("inspected")
    addresses = counts.get("found_addresses")
    checked = counts.get("checked_mx")
    measured = counts.get("measured_runs",0)
    def amount(value):
        return "ölçülmedi" if value is None else str(value)
    coverage = (f"{measured} kimlikli koşum; günün yalnızca ölçülen kısmı"
                if measured else "henüz tarama koşum kaydı yok")
    return (
        f"📊 Müşteri Avcısı AI — {day} TRT günlük rapor\n"
        f"📦 CRM toplamı: {amount(counts.get('total'))} | e-posta eksik: {amount(counts.get('email_missing'))}\n"
        f"🔎 İncelenen işletme: {amount(inspected)} (tekrarları içerir; {coverage})\n"
        f"🗺️ İl kapsam defteri: {amount(counts.get('provinces_completed'))}/"
        f"{amount(counts.get('provinces_total'))} il tamamlandı ({amount(counts.get('province_coverage_percent'))}%)\n"
        f"📍 İlçe sınır envanteri: {amount(counts.get('districts_completed'))}/"
        f"{amount(counts.get('districts_total'))} ilçe taraması kanıtlandı\n"
        f"🆕 CRM'e yeni benzersiz aday: {counts['new']}\n"
        f"📧 Yeni kaydedilen teknik adres: {amount(addresses)}\n"
        f"🌐 Resmî işletme sitesi araştırması: {counts.get('email_research_count', 0)}"
        f" | yeni kamuya açık adres: {counts.get('new_public_addresses', 0)}"
        f" | bulunamadı: {counts.get('email_research_no_address', 0)}\n"
        "ℹ️ Kamuya açık adres bulunması, e-posta gönderme izni değildir.\n"
        f"🔎 Yeni adreslerden format+DNS MX kontrolünü geçen: {amount(checked)}"
        " (posta kutusu/teslim ve izin kanıtı değildir)\n"
        f"✅ Doğrulanmış iletişim uygunluğu: {counts['eligible']}\n"
        f"⏭️ Mükerrer: {counts['duplicate']}\n"
        f"📤 Geçmiş SMTP kabulü: {counts['accepted']} | Bugün: {counts['accepted_today']}\n"
        f"🔴 Bugün eşleşen başarısızlık DSN: {amount(counts.get('today_failed_notices'))} "
        f"| Gecikme DSN: {amount(counts.get('today_delays'))} "
        f"| Güncel başarısız gönderi: {counts['failed']} | Geciken: {counts['delayed']}\n"
        f"📨 Bugün eşleşen yeni müşteri yanıtı: {amount(counts.get('today_replies'))} "
        f"| Toplam eşleşmiş yanıt: {counts['replies']}\n"
        f"🧩 Kanıtlı hizmet eşleşmeleri: {amount(counts.get('service_matches'))}\n"
        f"🛠️ Sistem hatası olan tarama koşumu: {amount(counts.get('system_errors'))}"
        f" / {amount(counts.get('measured_scan_attempts'))}\n"
        "💸 Toplam maliyet: ölçülmedi (altyapı faturalama verisi bağlı değil)\n"
        f"📝 Kalıcı satış aşaması kaydı: {counts.get('lifecycle_recorded', 0)} işletme"
        f" | teklif: {counts.get('lifecycle_stages', {}).get('offer_made', 0)}"
        f" | toplantı: {counts.get('lifecycle_stages', {}).get('meeting_scheduled', 0)}"
        f" | kazanıldı: {counts.get('lifecycle_stages', {}).get('won', 0)}"
        f" | kaybedildi: {counts.get('lifecycle_stages', {}).get('lost', 0)}\n"
        "ℹ️ Geçmişi olmayan CRM kayıtlarına aşama atanmaz.\n"
        f"🔐 Otomatik gönderim: {'KOŞULLU' if live else 'KAPALI'} — {reason}\n"
        "ℹ️ SMTP kabulü, alıcının gelen kutusuna teslim kanıtı değildir."
    )


def district_coverage(registry, path=DISTRICT_MANIFEST):
    """Count only district relation IDs explicitly planned and receipt-confirmed."""
    try:
        with open(path, "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)
        provinces = manifest["provinces"]
        districts = [row["relation_id"] for province in provinces
                     for row in province["districts"]]
        district_ids = set(districts)
        if (manifest.get("province_count") != 81
                or manifest.get("district_count") != len(districts)
                or len(district_ids) != len(districts)
                or not all(isinstance(value, str) and value.startswith("relation/")
                           for value in district_ids)):
            return None, None
        completed = set()
        for province in registry["provinces"]:
            plan = province.get("plan") or {}
            planned = set(plan.get("work_item_ids") or ())
            receipts = set((province.get("completed_items") or {}).keys())
            completed.update(planned & receipts & district_ids)
        return len(completed), len(district_ids)
    except (OSError, ValueError, KeyError, TypeError):
        return None, None


def run(env=None, connection=None, messenger=api, day=None, document_sender=None):
    env = os.environ if env is None else env
    if (not env.get('TELEGRAM_BOT_TOKEN')
            or not str(env.get('TELEGRAM_CHAT_ID') or '').isdigit()
            or int(env['TELEGRAM_CHAT_ID']) <= 0):
        raise RuntimeError('Verified owner Telegram configuration required')
    today = day or report_day(env)
    owns_connection = connection is None
    conn = connection if connection is not None else connect_private_database(
        env.get('REVIEW_DATABASE_URL'))
    try:
        from .crm_export import (build_workbook, fetch_rows, fetch_duplicate_pairs,
                                 send_document, snapshot_digest)
        # Migration 016 backs this idempotent seed/read. The report renders only
        # durable registry receipts; absent/unapplied persistence fails closed.
        from .province_coverage_store import initialize as initialize_province_coverage
        from .province_coverage_store import read as read_province_coverage
        from .province_coverage import coverage_table
        initialize_province_coverage(conn)
        generated_at = datetime.now(timezone.utc)
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SELECT transaction_timestamp()")
                source_snapshot_at = cur.fetchone()[0]
            counts = aggregate(conn, today)
            crm_rows = fetch_rows(conn)
            duplicate_pairs = fetch_duplicate_pairs(conn)
            province_registry = read_province_coverage(conn)
            province_coverage = coverage_table(province_registry)
            registry_by_code = {p["code"]: p for p in province_registry["provinces"]}
            for province_row in province_coverage:
                plan = registry_by_code[province_row["code"]].get("plan") or {}
                province_row["source_sha256"] = plan.get("source_sha256")
            if counts["total"] != len(crm_rows):
                raise RuntimeError("Daily report snapshot row-count mismatch; report not sent")
            from .commercial_scoring import match_service
            email_present = sum(bool(str(row.get("email") or "").strip()) for row in crm_rows)
            provinces_completed = sum(row.get("status") == "completed" for row in province_coverage)
            districts_completed, districts_total = district_coverage(province_registry)
            counts.update(
                total=len(crm_rows), email_missing=len(crm_rows) - email_present,
                provinces_completed=provinces_completed,
                provinces_total=len(province_coverage),
                province_coverage_percent=(
                    round(100 * provinces_completed / len(province_coverage), 1)
                    if province_coverage else 0),
                districts_completed=districts_completed,
                districts_total=districts_total,
                service_matches=sum(
                    match_service({"qualification": row.get("qualification") or {}})["category"] is not None
                    for row in crm_rows))
        run_id = env.get("GITHUB_RUN_ID") or ""
        run_attempt = env.get("GITHUB_RUN_ATTEMPT") or ""
        snapshot_hash = snapshot_digest(crm_rows)
        counts.update(github_run_id=run_id, github_run_attempt=run_attempt,
                      generated_at=generated_at.isoformat(),
                      source_snapshot_at=source_snapshot_at.isoformat(),
                      crm_snapshot_sha256=snapshot_hash)
        workbook = build_workbook(crm_rows, counts, today,
                                  send_enabled=env.get('AUTO_MAIL_ENABLED') == 'true',
                                  duplicate_pairs=duplicate_pairs,
                                  province_coverage=province_coverage)
        workbook_hash = hashlib.sha256(workbook).hexdigest()
        document_sender = send_document if document_sender is None else document_sender
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO owner_daily_report_receipts "
                    "(report_day,state,github_run_id,github_run_attempt,crm_row_count,"
                    "source_snapshot_at,crm_snapshot_sha256,workbook_sha256,generated_at) "
                    "VALUES (%s,'reserved',%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (report_day) DO NOTHING "
                    "RETURNING report_day", (today, run_id, int(run_attempt) if str(run_attempt).isdigit() else None,
                                              len(crm_rows), source_snapshot_at, snapshot_hash,
                                              workbook_hash, generated_at))
                acquired = cur.fetchone() is not None
        if not acquired:
            print("OWNER_DAILY_REPORT: already_reserved=1; business_mail_sent=0")
            return 0
        message = compose(today, counts, env.get('AUTO_MAIL_ENABLED') == 'true')
        if env.get("UNIFIED_CONTROL_HTTP_ENABLED") == "true":
            from .unified_control import snapshot, safe_report
            # A Render outage must never block the source owner's daily receipt.
            try:
                message += "\n🛰️ " + safe_report(snapshot())
            except Exception:
                message += "\\n🛰️ İşletmePilot/YorumPilot HTTP: doğrulanamadı"

        try:
            document_id = document_sender(
                env['TELEGRAM_BOT_TOKEN'], env['TELEGRAM_CHAT_ID'], workbook,
                f"Musteri-Avcisi-CRM-{today}.xlsx",
                f"{today} özel CRM raporu | üretim UTC {generated_at.isoformat()} | "
                f"satır {len(crm_rows)} | SHA-256 {workbook_hash}")
            if type(document_id) is not int or document_id <= 0:
                raise RuntimeError('Owner workbook Telegram receipt missing')
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE owner_daily_report_receipts SET telegram_document_message_id=%s,"
                        "document_sent_at=now(),updated_at=now() WHERE report_day=%s AND state='reserved'",
                        (document_id,today))
            result = messenger(env['TELEGRAM_BOT_TOKEN'], 'sendMessage',
                               {'chat_id':env['TELEGRAM_CHAT_ID'], 'text':message})
            mid = result.get('message_id') if isinstance(result,dict) else None
            if type(mid) is not int or mid <= 0:
                raise RuntimeError('Owner Telegram receipt missing')
        except Exception:
            stage = "summary_send" if "document_id" in locals() else "document_upload"
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE owner_daily_report_receipts SET state='uncertain',"
                        "failure_stage=%s,updated_at=now() WHERE report_day=%s AND state='reserved'",
                        (stage,today))
            print(f"OWNER_DAILY_REPORT: delivery_status=UNCERTAIN; failure_stage={stage}; "
                  f"document_message_id={locals().get('document_id', 'none')}; no_resend=1")
            raise RuntimeError('Owner Telegram result uncertain; no automatic resend') from None
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE owner_daily_report_receipts SET state='confirmed',"
                    "telegram_message_id=%s,telegram_document_message_id=%s,failure_stage=NULL,updated_at=now() "
                    "WHERE report_day=%s AND state='reserved'", (mid,document_id,today))
        print("OWNER_DAILY_REPORT: receipt_confirmed=1; workbook_sent=1; "
              f"workbook_telegram_message_id={document_id}; "
              f"summary_telegram_message_id={mid}; workbook_sha256={workbook_hash}; "
              f"crm_snapshot_sha256={snapshot_hash}; github_run_id={run_id or 'unknown'}; business_mail_sent=0")
        # ntfy is optional and strictly secondary to the durable Telegram
        # receipt. No ntfy settings means no request; failures never replay
        # the already delivered Telegram report.
        from .ntfy_report import send_daily as send_ntfy_daily
        ntfy_status = send_ntfy_daily(message, env)
        print(f"NTFY_DAILY_REPORT: status={ntfy_status}; delivery_receipt=not_available")
        return mid
    finally:
        if owns_connection:
            conn.close()


if __name__ == '__main__':
    run()
