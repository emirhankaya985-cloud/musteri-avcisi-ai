"""Pure owner decision transitions for future private Telegram review storage.

Never persist these decisions to the public repository. No email sender is wired.
"""
import re

OSM_ID = re.compile(r"(node|way|relation)/[0-9]+\Z")
ACTIONS = {"yes": "email_pending", "no": "rejected", "later": "deferred"}
TERMINAL = {"email_sent", "rejected"}


def decide(statuses, lead_id, action):
    """YES approves a future single email, NO excludes, LATER re-queues."""
    if not isinstance(lead_id, str) or not OSM_ID.fullmatch(lead_id):
        raise ValueError("Invalid public OSM object ID")
    if action not in ACTIONS:
        raise ValueError("Unknown owner decision")
    previous = statuses.get(lead_id)
    if previous in TERMINAL:
        return dict(statuses)
    if previous == "email_pending" and action == "yes":
        return dict(statuses)  # duplicate callback never schedules twice
    updated = dict(statuses)
    updated[lead_id] = ACTIONS[action]
    return updated


def mark_sent(statuses, lead_id, *, delivered):
    """Persistable confirmation transition; performs NO email sending."""
    if statuses.get(lead_id) != "email_pending":
        raise ValueError("Lead is not approved for email")
    if delivered is not True:
        return dict(statuses)
    updated = dict(statuses)
    updated[lead_id] = "email_sent"
    return updated


def prioritized_leads(statuses, discovered, *, deferred_fallback=(),
                      legacy_fallback=(), maximum=5):
    """Return held leads, fresh leads, then never-reviewed legacy seen leads.

    Legacy fallback is opt-in by the caller and is intentionally at the back:
    old Telegram reports are shown ONE TIME with actionable buttons, never
    re-presented after their private review status exists.
    """
    if type(maximum) is not int or maximum < 0:
        raise ValueError("Invalid maximum")
    pool = {}
    def identities(leads):
        result = []
        for lead in leads:
            lead_id = lead.get("id")
            if isinstance(lead_id, str) and OSM_ID.fullmatch(lead_id):
                pool.setdefault(lead_id, lead)
                if lead_id not in result:
                    result.append(lead_id)
        return result

    fresh_ids = identities(discovered)
    identities(deferred_fallback)
    legacy_ids = identities(legacy_fallback)
    held = [lid for lid, status in statuses.items()
            if status == "deferred" and lid in pool]
    fresh = [lid for lid in fresh_ids if lid not in statuses and lid not in held]
    legacy = [lid for lid in legacy_ids if lid not in statuses
              and lid not in held and lid not in fresh]
    # De-duplicate and preserve the exact priority ordering.
    return [pool[lid] for lid in (held + fresh + legacy)[:maximum]]


def email_ready(statuses, lead_id, *, recipient_verified=False,
                sender_configured=False, lawful_basis_verified=False):
    """Fails closed until an authorized one-to-one sender is configured."""
    return (statuses.get(lead_id) == "email_pending"
            and recipient_verified is True
            and sender_configured is True
            and lawful_basis_verified is True)
