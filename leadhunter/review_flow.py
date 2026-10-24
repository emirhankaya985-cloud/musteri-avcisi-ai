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


def prioritized_leads(statuses, discovered, *, deferred_fallback=(), maximum=5):
    """Include held leads first on every scan, excluding all other decisions.

    deferred_fallback can supply previously seen lead data loaded from private
    storage if OSM does not return it in the current scan.
    """
    if type(maximum) is not int or maximum < 0:
        raise ValueError("Invalid maximum")
    pool = {}
    for lead in list(discovered) + list(deferred_fallback):
        lead_id = lead.get("id")
        if isinstance(lead_id, str) and OSM_ID.fullmatch(lead_id):
            pool.setdefault(lead_id, lead)
    held = [lid for lid, status in statuses.items()
            if status == "deferred" and lid in pool]
    fresh = [lid for lid in pool if lid not in statuses]
    return [pool[lid] for lid in (held + fresh)[:maximum]]


def email_ready(statuses, lead_id, *, recipient_verified=False,
                sender_configured=False, lawful_basis_verified=False):
    """Fails closed until an authorized one-to-one sender is configured."""
    return (statuses.get(lead_id) == "email_pending"
            and recipient_verified is True
            and sender_configured is True
            and lawful_basis_verified is True)
