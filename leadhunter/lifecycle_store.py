"""Atomic private Neon writes for CRM lifecycle events.

No email is sent here. Sales stage ``communication_eligible`` is deliberately
independent from the separate mail eligibility and sender reputation gates.
"""
from __future__ import annotations

import json
import re

from .lifecycle import (
    LifecycleError,
    validate_event,
    validate_stage,
    validate_transition,
)

_SCHEMA = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z", re.ASCII)


def _schema_prefix(schema):
    if not isinstance(schema, str) or not _SCHEMA.fullmatch(schema):
        raise LifecycleError("Database schema name is invalid")
    return f'"{schema}"'


def _json_object(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise RuntimeError("Private CRM lead data is corrupt") from None
    if not isinstance(value, dict):
        raise RuntimeError("Private CRM lead data is corrupt")
    return value


def _opted_out(lead_data, crm_status):
    if crm_status == "rejected":
        return True
    info = lead_data.get("marketing_eligibility")
    if isinstance(info, dict) and info.get("opted_out") is True:
        return True
    for key in ("_auto_mail", "_mail"):
        record = lead_data.get(key)
        if not isinstance(record, dict):
            continue
        feedback = record.get("reply_feedback")
        if isinstance(feedback, dict) and feedback.get("intent") == "opt_out":
            return True
    return False


def _decode_evidence(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            raise RuntimeError("Private lifecycle evidence is corrupt") from None
    if not isinstance(value, list):
        raise RuntimeError("Private lifecycle evidence is corrupt")
    return tuple(value)


def record_transition(connection, lead_id: str, new_stage: str, *,
                      idempotency_key: str, reason: str, evidence_refs,
                      actor: str = "system", schema: str = "public") -> dict:
    """Record one lifecycle transition atomically and idempotently.

    Existing CRM leads are never backfilled automatically. The first explicit
    event must be ``new_discovered`` unless the private CRM already records an
    opt-out/rejection, in which case the only initial state allowed is
    ``do_not_contact``.
    """
    if not isinstance(lead_id, str) or not lead_id.strip() or len(lead_id) > 200:
        raise LifecycleError("A valid private CRM lead ID is required")
    new_stage = validate_stage(new_stage)
    key, reason, refs = validate_event(
        idempotency_key=idempotency_key, reason=reason,
        evidence_refs=evidence_refs)
    if (not isinstance(actor, str) or not actor.strip() or len(actor.strip()) > 80
            or "@" in actor):
        raise LifecycleError("Lifecycle actor must be a short private role label")
    actor = actor.strip()
    schema_prefix = _schema_prefix(schema)

    with connection.transaction():
        with connection.cursor() as cur:
            # Lock the private CRM parent row so concurrent transitions for the
            # same lead serialize before checking idempotency and current state.
            cur.execute(
                f"SELECT lead_data,status FROM {schema_prefix}.owner_leads "
                "WHERE osm_id=%s FOR UPDATE", (lead_id,))
            lead_row = cur.fetchone()
            if not lead_row:
                raise LifecycleError("Lead does not exist in the private CRM")
            lead_data = _json_object(lead_row[0])
            crm_status = str(lead_row[1] or "")
            opted_out = _opted_out(lead_data, crm_status)

            cur.execute(
                "SELECT event_id,lead_id,previous_stage,new_stage,reason,evidence_refs "
                f"FROM {schema_prefix}.owner_lead_lifecycle_events WHERE idempotency_key=%s",
                (key,))
            previous_event = cur.fetchone()
            if previous_event:
                event_id, prior_lead, prior_from, prior_to, prior_reason, prior_refs = previous_event
                if (prior_lead != lead_id or prior_to != new_stage
                        or prior_reason != reason
                        or _decode_evidence(prior_refs) != refs):
                    from .lifecycle import IdempotencyConflict
                    raise IdempotencyConflict("Lifecycle idempotency key was already used")
                return {"event_id": int(event_id), "previous_stage": prior_from,
                        "current_stage": prior_to, "changed": prior_from != prior_to,
                        "replayed": True}

            cur.execute(
                f"SELECT current_stage FROM {schema_prefix}.owner_lead_lifecycle_state "
                "WHERE lead_id=%s FOR UPDATE", (lead_id,))
            state_row = cur.fetchone()
            if state_row is None:
                expected_initial = "do_not_contact" if opted_out else "new_discovered"
                if new_stage != expected_initial:
                    if opted_out:
                        from .lifecycle import OptOutProtected
                        raise OptOutProtected("An opted-out lead may only start suppressed")
                    raise LifecycleError("Existing leads require an explicit new_discovered event first")
                previous_stage = None
            else:
                previous_stage = validate_stage(state_row[0])
                validate_transition(previous_stage, new_stage, opted_out=opted_out)
                if previous_stage == new_stage:
                    return {"event_id": None, "previous_stage": previous_stage,
                            "current_stage": new_stage, "changed": False,
                            "replayed": False}

            cur.execute(
                f"INSERT INTO {schema_prefix}.owner_lead_lifecycle_events "
                "(lead_id,idempotency_key,previous_stage,new_stage,reason,evidence_refs,actor) "
                "VALUES (%s,%s,%s,%s,%s,%s::jsonb,%s) RETURNING event_id",
                (lead_id, key, previous_stage, new_stage, reason,
                 json.dumps(refs, ensure_ascii=False), actor))
            event_id = int(cur.fetchone()[0])
            if previous_stage is None:
                cur.execute(
                    f"INSERT INTO {schema_prefix}.owner_lead_lifecycle_state "
                    "(lead_id,current_stage,updated_by) VALUES (%s,%s,%s)",
                    (lead_id, new_stage, actor))
            else:
                cur.execute(
                    f"UPDATE {schema_prefix}.owner_lead_lifecycle_state "
                    "SET current_stage=%s,stage_updated_at=now(),updated_by=%s "
                    "WHERE lead_id=%s",
                    (new_stage, actor, lead_id))
                if cur.rowcount != 1:
                    raise RuntimeError("Private lifecycle state update lost its row")

    return {"event_id": event_id, "previous_stage": previous_stage,
            "current_stage": new_stage, "changed": True, "replayed": False}


def read_stage(connection, lead_id: str, *, schema: str = "public"):
    """Read only the current CRM stage; returns ``None`` until explicitly set."""
    schema_prefix = _schema_prefix(schema)
    with connection.cursor() as cur:
        cur.execute(
            "SELECT current_stage,stage_updated_at,updated_by "
            f"FROM {schema_prefix}.owner_lead_lifecycle_state WHERE lead_id=%s",
            (lead_id,))
        row = cur.fetchone()
    if row is None:
        return None
    return {"stage": validate_stage(row[0]), "updated_at": row[1],
            "updated_by": row[2]}
