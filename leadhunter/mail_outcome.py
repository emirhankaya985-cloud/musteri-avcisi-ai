"""Owner-only, read-only Gmail/SMTP outcome audit.

SMTP acceptance does not prove inbox delivery. Never export recipient addresses
or message bodies; never change an existing claim or unlock an SMTP path.
"""
import os
from .review_private import connect_private_database


REASON_KEYS = ("dns_nxdomain", "mailbox_missing", "relay_denied",
               "connection_refused", "unknown")


def audit_failure_reasons(conn, failed_total):
    """Aggregate already stored DSN reason labels, never recipient details."""
    if type(failed_total) is not int or failed_total < 0:
        raise ValueError("Invalid failed delivery count")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT coalesce(lead_data->'_auto_mail'->'delivery_feedback'->>'reason',"
            "'unknown'), count(*) FROM owner_leads WHERE "
            "lead_data->'_auto_mail'->'delivery_feedback'->>'state'='failed' "
            "GROUP BY 1")
        rows = cur.fetchall()
    counts = dict.fromkeys(REASON_KEYS, 0)
    for reason, raw_count in rows:
        value = int(raw_count)
        if value < 0:
            raise ValueError("Invalid failure-reason count")
        key = reason if reason in REASON_KEYS else "unknown"
        counts[key] += value
    if sum(counts.values()) != failed_total:
        raise RuntimeError("Failure-reason counters inconsistent; SMTP remains paused")
    return counts


def summarize_counts(accepted, failed, delayed, replies):
    values = (accepted, failed, delayed, replies)
    if any(type(v) is not int or v < 0 for v in values):
        raise ValueError("Invalid aggregate counts")
    if failed > accepted or delayed > accepted:
        raise ValueError("Feedback counts exceed recorded SMTP acceptances")
    return {
        "accepted": accepted, "failed": failed, "delayed": delayed,
        "replies": replies,
        "unverified_delivery": accepted - failed,
        "verified_delivery": None,
        "paused": accepted >= 10 and failed * 100 >= accepted * 15,
    }


def audit(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE lead_data->'_auto_mail'->>'state'='accepted' "
            "OR lead_data->'_mail'->>'state'='accepted'),"
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->'delivery_feedback'->>'state'='failed'),"
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->'delivery_feedback'->>'state'='delayed'),"
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->'reply_feedback'->>'state'='sender_matched_reply') "
            "FROM owner_leads")
        accepted, failed, delayed, replies = cur.fetchone()
    return summarize_counts(int(accepted), int(failed), int(delayed), int(replies))


def run(env=None, connection=None, output=print):
    env = os.environ if env is None else env
    owns = connection is None
    if owns and not env.get("REVIEW_DATABASE_URL"):
        raise RuntimeError("Private audit database unavailable; no SMTP")
    conn = connection if connection is not None else connect_private_database(env["REVIEW_DATABASE_URL"])
    try:
        counts = audit(conn)
        reasons = audit_failure_reasons(conn, counts["failed"])
    finally:
        if owns:
            conn.close()
    output(
        "MAIL_OUTCOME_AUDIT: historical_smtp_accepted={accepted}; "
        "failed={failed}; delayed={delayed}; matched_replies={replies}; "
        "delivery_confirmed=unverified; remaining_acceptances_not_proven_delivered={unverified_delivery}; "
        "sender_paused={paused}; new_business_smtp_sent=0".format(**counts))
    output("MAIL_FAILURE_REASONS: " +
           "; ".join(k + "=" + str(reasons[k]) for k in REASON_KEYS) +
           "; addresses_redacted=1; business_mail_sent=0")
    return counts


if __name__ == "__main__":
    run()
