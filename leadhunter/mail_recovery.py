"""Read-only, PII-free remediation advice for prior mail failures.

This report never tests recipients, retries mail, modifies Neon, or unlocks the
sender. It maps already recorded DSN classes to owner remediation evidence.
"""
from __future__ import annotations

import os

from .mail_outcome import (REASON_KEYS, audit, audit_failure_reasons,
                           summarize_counts)
from .review_private import connect_private_database


ADVICE = {
    "dns_nxdomain": (
        "Verify the recipient domain from a current authoritative business source; "
        "keep this address/domain on hold until corrected evidence is recorded."),
    "mailbox_missing": (
        "Treat this mailbox as invalid; research a replacement only from the "
        "business's official contact source and do not retry the failed address."),
    "relay_denied": (
        "Review the sender account's SMTP/Workspace relay policy and the recorded "
        "provider response; do not expose credentials or retry the old message."),
    "connection_refused": (
        "Review the SMTP endpoint, TLS/network availability, and delayed DSN "
        "timeline; do not replay an ambiguous message automatically."),
    "unknown": (
        "Inspect the original private delivery receipt and classify the DSN "
        "before considering any further action; do not retry automatically."),
}


def remediation_report(counts, reasons):
    """Return deterministic, aggregate-only next steps; never an unlock token."""
    if not isinstance(counts, dict) or not isinstance(reasons, dict):
        raise ValueError("Mail recovery audit inputs must be mappings")
    summary = summarize_counts(
        counts.get("accepted"), counts.get("failed"),
        counts.get("delayed"), counts.get("replies"))
    if set(reasons) != set(REASON_KEYS):
        raise ValueError("Mail recovery reason classes are incomplete")
    normalized = {}
    for key in REASON_KEYS:
        value = reasons[key]
        if type(value) is not int or value < 0:
            raise ValueError("Mail recovery reason count is invalid")
        normalized[key] = value
    if sum(normalized.values()) != summary["failed"]:
        raise ValueError("Mail failure reason totals disagree; keep sender paused")

    actions = [
        {"reason": key, "count": normalized[key], "action": ADVICE[key]}
        for key in REASON_KEYS if normalized[key]
    ]
    evidence = []
    if summary["unverified_delivery"]:
        evidence.append(
            f"Review the {summary['unverified_delivery']} historical SMTP acceptances "
            "without verified delivery.")
    if summary["paused"]:
        evidence.append(
            "Sender reputation circuit remains paused: failed/accepted ratio meets "
            "the configured threshold; remediation must be evidenced and reviewed.")
    if not summary["replies"]:
        evidence.append("No matched business replies are recorded yet.")
    return {
        "accepted": summary["accepted"],
        "failed": summary["failed"],
        "delayed": summary["delayed"],
        "replies": summary["replies"],
        "unverified_delivery": summary["unverified_delivery"],
        "paused": summary["paused"],
        "recipient_details_included": False,
        "smtp_attempts": 0,
        "unlock_authorized": False,
        "actions": actions,
        "evidence_gaps": evidence,
    }


def audit_recovery(connection):
    """Build recommendations from the existing read-only aggregate audit."""
    counts = audit(connection)
    reasons = audit_failure_reasons(connection, counts["failed"])
    return remediation_report(counts, reasons)


def run(env=None, connection=None, output=print):
    """Print only aggregate reason classes and remediation steps."""
    env = os.environ if env is None else env
    owns = connection is None
    if owns and not env.get("REVIEW_DATABASE_URL"):
        raise RuntimeError("Private mail recovery audit unavailable; no SMTP")
    conn = connection if connection is not None else connect_private_database(
        env["REVIEW_DATABASE_URL"])
    try:
        report = audit_recovery(conn)
    finally:
        if owns:
            conn.close()

    output(
        "MAIL_RECOVERY: accepted={accepted}; failed={failed}; delayed={delayed}; "
        "replies={replies}; unverified_delivery={unverified_delivery}; "
        "sender_paused={paused}; unlock_authorized=0; smtp_attempts=0; "
        "recipient_details=0".format(**report))
    for item in report["actions"]:
        output("MAIL_RECOVERY_ACTION: reason={reason}; count={count}; action={action}".format(**item))
    for item in report["evidence_gaps"]:
        output("MAIL_RECOVERY_EVIDENCE_GAP: " + item)
    return report


if __name__ == "__main__":
    run()
