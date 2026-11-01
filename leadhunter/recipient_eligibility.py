"""Fail-closed per-recipient commercial email eligibility.

The OSM listing of a business address and existence of MX records are NOT
evidence of current permission or recipient opt-out status. Eligibility may
only be imported from a verified owner/provider record into PRIVATE Postgres.
"""
from datetime import datetime, timedelta, timezone
from .mail_tracking import normalized_email


def eligible_recipient(lead, recipient, now=None):
    info = lead.get("marketing_eligibility") if isinstance(lead, dict) else None
    if not isinstance(info, dict):
        return False
    recipient = normalized_email(recipient)
    if not recipient or normalized_email(info.get("recipient")) != recipient:
        return False
    if info.get("opted_out") is not False:
        return False
    evidence = info.get("evidence_ref")
    if not isinstance(evidence, str) or not 8 <= len(evidence) <= 256:
        return False
    verified = info.get("verified_at")
    if not isinstance(verified, str):
        return False
    try:
        timestamp = datetime.fromisoformat(verified.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        return False
    if timestamp.tzinfo is None:
        return False
    now = now or datetime.now(timezone.utc)
    age = now - timestamp.astimezone(timezone.utc)
    if age < timedelta(0):
        return False
    route = info.get("route")
    if route == "consent":
        return info.get("consent_active") is True and age <= timedelta(days=30)
    if route == "iys_verified_business":
        # A public OSM shop tag alone does not prove legal merchant status.
        # IYS status must have been checked externally by the sender.
        return (info.get("merchant_verified") is True
                and info.get("iys_registered") is True
                and info.get("iys_rejected") is False
                and age <= timedelta(hours=24))
    return False
