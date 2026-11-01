"""Once-daily owner Telegram status, fail-closed receipt before external API.

Read-only CRM aggregates. One reserved day never sends twice, even if Telegram
accepted a message but the database confirmation subsequently failed.
No customer SMTP, no private addresses or bodies in Telegram.
"""
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from .recipient_eligibility import eligible_recipient
from .review_private import connect_private_database
from .telegram_buttons import api

ZONE = ZoneInfo("Europe/Istanbul")


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
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->>'claimed_day'=%s "
            "AND lead_data->'_auto_mail'->>'state'='accepted') "
            "FROM owner_leads", (day, day))
        total, new, accepted, failed, delayed, replies, duplicate, accepted_today = cur.fetchone()
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
                eligible=eligible)


def compose(day, counts, enabled):
    paused = counts['accepted'] >= 10 and counts['failed'] * 100 >= counts['accepted'] * 15
    live = enabled and not paused and counts['eligible'] > 0
    reason = ('Geçmiş teslimat hata oranı / itibar koruması'
              if paused else 'Doğrulanmış uygun alıcı yok'
              if counts['eligible'] == 0 else 'Çalışma izni/config kapalı'
              if not enabled else 'Uygunluk ve itibar ön denetimleri sağlandı')
    return (
        f"📊 Müşteri Avcısı AI — {day} TRT günlük rapor\n"
        f"🔎 Toplam aday: {counts['total']} | Bugün yeni: {counts['new']}\n"
        f"✅ Doğrulanmış iletişim uygunluğu: {counts['eligible']}\n"
        f"⏭️ Mükerrer: {counts['duplicate']}\n"
        f"📤 Geçmiş SMTP kabulü: {counts['accepted']} | Bugün: {counts['accepted_today']}\n"
        f"🔴 Teslimat hatası: {counts['failed']} | 🟡 Geciken: {counts['delayed']}\n"
        f"📨 Yanıt: {counts['replies']}\n"
        f"🔐 Otomatik gönderim: {'KOŞULLU' if live else 'KAPALI'} — {reason}\n"
        "ℹ️ SMTP kabulü, alıcının gelen kutusuna teslim kanıtı değildir."
    )


def run(env=None, connection=None, messenger=api, day=None):
    env = os.environ if env is None else env
    if not env.get('TELEGRAM_BOT_TOKEN') or not str(env.get('TELEGRAM_CHAT_ID') or '').isdigit():
        raise RuntimeError('Verified owner Telegram configuration required')
    today = day or datetime.now(ZONE).date().isoformat()
    owns_connection = connection is None
    conn = connection if connection is not None else connect_private_database(
        env.get('REVIEW_DATABASE_URL'))
    try:
        counts = aggregate(conn, today)
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO owner_daily_report_receipts (report_day,state) "
                    "VALUES (%s,'reserved') ON CONFLICT (report_day) DO NOTHING "
                    "RETURNING report_day", (today,))
                acquired = cur.fetchone() is not None
        if not acquired:
            print("OWNER_DAILY_REPORT: already_reserved=1; business_mail_sent=0")
            return 0
        message = compose(today, counts, env.get('AUTO_MAIL_ENABLED') == 'true')
        try:
            result = messenger(env['TELEGRAM_BOT_TOKEN'], 'sendMessage',
                               {'chat_id':env['TELEGRAM_CHAT_ID'], 'text':message})
            mid = result.get('message_id') if isinstance(result,dict) else None
            if type(mid) is not int or mid <= 0:
                raise RuntimeError('Owner Telegram receipt missing')
        except Exception:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE owner_daily_report_receipts SET state='uncertain',"
                        "updated_at=now() WHERE report_day=%s AND state='reserved'",
                        (today,))
            raise RuntimeError('Owner Telegram result uncertain; no automatic resend') from None
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE owner_daily_report_receipts SET state='confirmed',"
                    "telegram_message_id=%s,updated_at=now() "
                    "WHERE report_day=%s AND state='reserved'", (mid,today))
        print("OWNER_DAILY_REPORT: receipt_confirmed=1; business_mail_sent=0")
        return mid
    finally:
        if owns_connection:
            conn.close()


if __name__ == '__main__':
    run()
