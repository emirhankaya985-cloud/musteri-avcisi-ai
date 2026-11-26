"""Record evidence-backed lifecycle events from frozen Gmail reply matches.

This helper never authorizes or sends mail. It refuses to backfill historical
accepted mail into a sent/replied stage; only an already-recorded
``email_sent`` stage can advance to ``replied``. An exact explicit opt-out is
stronger and may initialize an otherwise untracked lead directly as suppressed.
"""
from __future__ import annotations

import hashlib

from .lifecycle_store import read_stage, record_transition


def record_matched_reply(connection, lead_id: str, *, sender: str,
                         reply_reference: str, intent: str) -> dict:
    """Persist DNC for an exact opt-out, or ``replied`` from ``email_sent``.

    The caller must already have matched the sender and exact outgoing
    Message-ID. Raw addresses, headers, and message bodies are not stored in
    lifecycle evidence.
    """
    if intent not in ("opt_out", "positive_review", "needs_review"):
        return {"recorded": False, "reason": "unsupported_intent"}
    if (not isinstance(sender, str) or "@" not in sender
            or not isinstance(reply_reference, str)
            or not reply_reference.startswith("reply:")
            or "@" not in reply_reference):
        return {"recorded": False, "reason": "invalid_matched_reply"}
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('owner_lead_lifecycle_state')")
        if cur.fetchone()[0] is None:
            return {"recorded": False, "reason": "lifecycle_schema_missing"}

    digest = hashlib.sha256(
        (sender.casefold() + "\n" + reply_reference.casefold()).encode("utf-8")
    ).hexdigest()
    evidence = (f"gmail-message://sha256/{digest}",)
    if intent == "opt_out":
        result = record_transition(
            connection, lead_id, "do_not_contact",
            idempotency_key=f"gmail-optout:{digest}",
            reason="Exact frozen-thread reply explicitly requested no further contact",
            evidence_refs=evidence,
            actor="gmail_watcher",
        )
        return {"recorded": bool(result["changed"] or result["replayed"]),
                "stage": "do_not_contact", "reason": "explicit_opt_out"}

    current = read_stage(connection, lead_id)
    if not current or current["stage"] != "email_sent":
        return {"recorded": False, "reason": "no_email_sent_lifecycle_evidence"}
    result = record_transition(
        connection, lead_id, "replied",
        idempotency_key=f"gmail-reply:{digest}",
        reason="Exact frozen outgoing Message-ID matched an incoming reply",
        evidence_refs=evidence,
        actor="gmail_watcher",
    )
    return {"recorded": bool(result["changed"] or result["replayed"]),
            "stage": "replied", "reason": "exact_thread_match"}


def record_smtp_acceptance(connection, lead_id: str, *, claim_id: str) -> dict:
    """Advance only an already prepared proposal after durable SMTP acceptance.

    The claim ID is the system's frozen opaque mail-record ID, not the
    recipient address or SMTP response text. This records server acceptance;
    it does not claim inbox delivery. Missing lifecycle history is never
    initialized or backfilled here.
    """
    if (not isinstance(claim_id, str) or not claim_id
            or len(claim_id) > 160 or "@" in claim_id):
        return {"recorded": False, "reason": "invalid_smtp_claim"}
    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('owner_lead_lifecycle_state')")
        if cur.fetchone()[0] is None:
            return {"recorded": False, "reason": "lifecycle_schema_missing"}

    current = read_stage(connection, lead_id)
    if not current or current["stage"] != "proposal_prepared":
        return {"recorded": False, "reason": "proposal_prepared_stage_required"}
    digest = hashlib.sha256((lead_id + "\n" + claim_id).encode("utf-8")).hexdigest()
    result = record_transition(
        connection, lead_id, "email_sent",
        idempotency_key=f"smtp-accepted:{digest}",
        reason="Frozen proposal claim was accepted by the configured SMTP server",
        evidence_refs=(f"smtp-claim://sha256/{digest}",),
        actor="smtp_worker",
    )
    return {"recorded": bool(result["changed"] or result["replayed"]),
            "stage": "email_sent", "reason": "smtp_accepted_not_delivery_confirmed"}
