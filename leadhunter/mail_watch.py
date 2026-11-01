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



def dsn_details(message):
    """Only machine-readable DSN status codes, never personal details or text."""
    enhanced, smtp_codes, recipients = set(), set(), set()
    for part in message.walk():
        if part.get_content_type() != "message/delivery-status":
            continue
        for block in (part.get_payload() if isinstance(part.get_payload(), list) else []):
            for field in ("Final-Recipient", "Original-Recipient"):
                value = str(block.get(field, "")).strip().casefold()
                if value:
                    recipients.add(value)
            status = str(block.get("Status", "")).strip()
            if re.fullmatch(r"[245]\.\d{1,3}\.\d{1,3}", status):
                enhanced.add(status)
            diagnostic = str(block.get("Diagnostic-Code", ""))
            match = re.search(r"(?<!\d)([245]\d\d)(?!\d)", diagnostic)
            if match:
                smtp_codes.add(match.group(1))
    # A shared multi-recipient DSN cannot safely attribute one code to a lead.
    if len(recipients) > 1 or len(enhanced) > 1 or len(smtp_codes) > 1:
        return {}
    result = {}
    if len(enhanced) == 1:
        result["enhanced_status"] = next(iter(enhanced))
    if len(smtp_codes) == 1:
        result["smtp_code"] = next(iter(smtp_codes))
    classes = {value[0] for value in (list(enhanced) + list(smtp_codes))}
    if classes == {"5"}:
        result["failure_kind"] = "permanent"
    elif classes == {"4"}:
        result["failure_kind"] = "temporary"
    # Some genuine Gmail notifications have only a human-readable plaintext
    # body, with no message/delivery-status MIME part. This parser is called
    # ONLY for whitelisted mailer-daemon addresses and DSN subjects.
    parts = []
    for part in message.walk():
        if part.get_content_type() == "text/plain":
            try:
                parts.append(part.get_content()[:20000])
            except (TypeError, UnicodeError, LookupError):
                pass
    body = "\n".join(parts)
    if body:
        if not result.get("smtp_code"):
            match = re.search(r"(?m)^\s*([45]\d\d)(?!\d)", body)
            if match:
                result["smtp_code"] = match.group(1)
        if not result.get("enhanced_status"):
            match = re.search(r"(?<!\d)([45]\.\d{1,3}\.\d{1,3})(?!\d)", body)
            if match:
                result["enhanced_status"] = match.group(1)
        low = body.casefold()
        # Coarse reasons only: never persist remote diagnostic text or PII.
        if "nxdomain" in low or "domain name not found" in low:
            result["reason"] = "dns_nxdomain"
            result["failure_kind"] = "permanent"
        elif "no such user here" in low:
            result["reason"] = "mailbox_missing"
            result["failure_kind"] = "permanent"
        elif "relay access denied" in low:
            result["reason"] = "relay_denied"
            result["failure_kind"] = "permanent"
        elif "connection refused" in low and not classes:
            result["reason"] = "connection_refused"
            result["failure_kind"] = "temporary"
        elif not result.get("failure_kind"):
            code = result.get("enhanced_status") or result.get("smtp_code")
            if code and code[0] in "45":
                result["failure_kind"] = (
                    "permanent" if code[0] == "5" else "temporary")
    return result


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
    if not evidence:
        return None
    details = dsn_details(message)
    return (evidence[:200_000], state, details) if details else (evidence[:200_000], state)


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


def matching_reply(notices, recipient, mail_id):
    """Two-field reply tuples coexist with three-field DSN metadata tuples."""
    if len(mail_id) < 12:
        return False
    return any(
        len(notice) >= 2 and notice[1].startswith("reply:")
        and notice[0] == recipient and ("<" + mail_id + "@") in notice[1]
        for notice in notices
    )


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
                state, details = None, {}
                for notice in notices:
                    evidence, candidate = notice[:2]
                    if candidate not in ("failed", "delayed"):
                        continue  # Reply metadata cannot be a delivery failure.
                    # Only match already frozen recipients, never arbitrary leads.
                    if re.search(r"(?<![\\w.+-])" + re.escape(recipient) + r"(?![\\w.+-])", evidence):
                        if candidate == "failed":
                            state, details = "failed", (notice[2] if len(notice) > 2 else {})
                            break
                        if state is None:
                            state, details = "delayed", (notice[2] if len(notice) > 2 else {})
                # A reply requires an exact sender-to-recipient match AND
                # an RFC822 In-Reply-To/References header tied to our own
                # frozen outgoing Message-ID. Merely sharing a sender is not
                # enough to count an unrelated message as a business reply.
                mail_id = str(record.get("id") or "").casefold()
                has_reply = matching_reply(notices, recipient, mail_id)
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
                if not state or before.get("state") == "failed" and state != "failed":
                    continue
                details = details if isinstance(details, dict) else {}
                # Preserve the old observed time/Telegram receipt on enrichment;
                # do not resend a notification when finding a diagnostic code.
                enrichment = {key: value for key, value in details.items()
                              if key in ("smtp_code", "enhanced_status", "failure_kind", "reason")
                              and key not in before}
                if before.get("state") == state and not enrichment:
                    continue
                feedback = {**before, "state": state, "observed_at":
                            before.get("observed_at") or datetime.now(timezone.utc).isoformat(),
                            **enrichment}
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
