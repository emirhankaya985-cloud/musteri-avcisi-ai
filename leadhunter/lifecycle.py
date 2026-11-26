"""Private CRM lifecycle rules; independent from marketing permission.

These stages describe sales operations only. In particular,
``communication_eligible`` never writes ``marketing_eligibility`` and does not
authorize SMTP. Actual mail continues to require recipient_eligibility's
private, fresh consent / merchant-IYS evidence and the sender circuit.
"""
from __future__ import annotations

import re

STAGES = (
    "new_discovered",
    "researched",
    "need_verified",
    "communication_eligible",
    "proposal_prepared",
    "email_sent",
    "replied",
    "meeting_scheduled",
    "offer_made",
    "won",
    "lost",
    "do_not_contact",
)

TERMINAL_STAGES = frozenset(("won", "lost", "do_not_contact"))
OPT_OUT_STAGE = "do_not_contact"

TRANSITIONS = {
    "new_discovered": frozenset(("researched", "lost", OPT_OUT_STAGE)),
    "researched": frozenset(("need_verified", "lost", OPT_OUT_STAGE)),
    "need_verified": frozenset(("communication_eligible", "lost", OPT_OUT_STAGE)),
    "communication_eligible": frozenset(("proposal_prepared", "lost", OPT_OUT_STAGE)),
    "proposal_prepared": frozenset(("email_sent", "offer_made", "lost", OPT_OUT_STAGE)),
    "email_sent": frozenset(("replied", "lost", OPT_OUT_STAGE)),
    "replied": frozenset(("meeting_scheduled", "offer_made", "lost", OPT_OUT_STAGE)),
    "meeting_scheduled": frozenset(("offer_made", "won", "lost", OPT_OUT_STAGE)),
    "offer_made": frozenset(("won", "lost", OPT_OUT_STAGE)),
    # A later opt-out always adds the stronger suppression marker, even to a
    # closed business. No other terminal stage can be reopened.
    "won": frozenset((OPT_OUT_STAGE,)),
    "lost": frozenset((OPT_OUT_STAGE,)),
    "do_not_contact": frozenset(),
}

_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{7,159}\Z", re.ASCII)
_EVIDENCE_SCHEMES = ("https://", "osm://", "gmail-message://", "manual://", "smtp-claim://")


class LifecycleError(ValueError):
    """Invalid or unsafe lifecycle event."""


class IdempotencyConflict(LifecycleError):
    """An idempotency key was reused for a different event."""


class OptOutProtected(LifecycleError):
    """An opted-out lead cannot move to a contactable stage."""


def validate_stage(stage: str) -> str:
    if not isinstance(stage, str) or stage not in STAGES:
        raise LifecycleError("Unknown CRM lifecycle stage")
    return stage


def validate_event(*, idempotency_key: str, reason: str, evidence_refs=()) -> tuple[str, str, tuple[str, ...]]:
    if not isinstance(idempotency_key, str) or not _KEY.fullmatch(idempotency_key):
        raise LifecycleError("Lifecycle idempotency key must be 8-160 safe characters")
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise LifecycleError("Lifecycle event requires a reason up to 500 characters")
    if isinstance(evidence_refs, (str, bytes)):
        raise LifecycleError("Evidence references must be a sequence")
    refs = tuple(evidence_refs)
    if not refs or len(refs) > 12:
        raise LifecycleError("Lifecycle changes require 1-12 evidence references")
    for ref in refs:
        if (not isinstance(ref, str) or not ref.strip() or len(ref) > 500
                or not ref.startswith(_EVIDENCE_SCHEMES)):
            raise LifecycleError("Evidence references must be redacted HTTPS or approved opaque references")
        # A URL/query or opaque reference must not be used to store recipient details.
        if "@" in ref:
            raise LifecycleError("Lifecycle evidence must not contain email addresses")
    return idempotency_key, reason.strip(), refs


def validate_transition(current_stage: str, new_stage: str, *, opted_out: bool = False) -> tuple[str, str]:
    current = validate_stage(current_stage)
    target = validate_stage(new_stage)
    if type(opted_out) is not bool:
        raise LifecycleError("opted_out must be an explicit boolean")
    if opted_out and target != OPT_OUT_STAGE:
        raise OptOutProtected("An opted-out lead is permanently suppressed from contactable stages")
    if current == target:
        return current, target
    if current == OPT_OUT_STAGE:
        raise LifecycleError("Do-not-contact suppression cannot be reopened")
    if current in TERMINAL_STAGES and target != OPT_OUT_STAGE:
        raise LifecycleError("Terminal lifecycle stages cannot be reopened")
    if target not in TRANSITIONS[current]:
        raise LifecycleError("CRM lifecycle transition is not allowed")
    return current, target


def first_stage(*, opted_out: bool) -> str:
    """Return the safe initial stage without backfilling any private CRM data."""
    if type(opted_out) is not bool:
        raise LifecycleError("opted_out must be an explicit boolean")
    return OPT_OUT_STAGE if opted_out else "new_discovered"
