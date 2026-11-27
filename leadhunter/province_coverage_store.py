"""Atomic Neon persistence for the evidence-gated province coverage ledger.

This repository is an offline/persistence boundary only. It does not fetch OSM
data, write customer leads, or mark a province complete without source receipts
validated by :mod:`province_coverage`.
"""
from __future__ import annotations

import json
import hashlib
import re

from . import province_coverage as model

LOCK_ID = 985_402_618
TABLE = "owner_province_scan_coverage"
_OSM_ID = re.compile(r"(?:node|way|relation)/[0-9]+\Z", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
# A district is an atomic receipt unit, so safely bounded large districts must
# fit in one transaction rather than being prematurely marked complete after
# partial lead chunks.
MAX_DISTRICT_LEADS = 10_000
_SOURCE_FIELDS = ("name", "category", "website", "phone", "email", "address")


def _changed_source_fields(prior, fresh):
    return tuple(
        key for key in _SOURCE_FIELDS
        if str(prior.get(key) or "").strip().casefold()
        != str(fresh.get(key) or "").strip().casefold()
    )


def _decode(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            raise RuntimeError("Province coverage state is corrupt") from None
    if not isinstance(value, dict):
        raise RuntimeError("Province coverage state is corrupt")
    return value


def _from_rows(rows):
    """Rebuild and validate the domain registry from private aggregate rows."""
    if len(rows) != len(model.PROVINCES):
        raise RuntimeError("Province coverage registry is incomplete")
    registry = {"schema_version": model.SCHEMA_VERSION, "provinces": []}
    seen = set()
    for code, name, initial_target, status, raw_state in rows:
        state = _decode(raw_state)
        if (code in seen or state.get("code") != code or state.get("name") != name
                or state.get("initial_phase_target") is not initial_target
                or state.get("status") != status):
            raise RuntimeError("Province coverage row disagrees with its state")
        seen.add(code)
        registry["provinces"].append(state)
    model.coverage_table(registry)  # verifies the exact 81-code catalog
    return registry


def initialize(connection):
    """Idempotently create the 81 pending province rows; never rewrites state."""
    registry = model.new_registry()
    insert = (
        f"INSERT INTO {TABLE} "
        "(province_code,province_name,initial_phase_target,status,province_state) "
        "VALUES (%s,%s,%s,%s,%s::jsonb) ON CONFLICT (province_code) DO NOTHING"
    )
    try:
        with connection.transaction():
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
                cur.executemany(insert, [
                    (entry["code"], entry["name"], entry["initial_phase_target"],
                     entry["status"], json.dumps(entry, ensure_ascii=False))
                    for entry in registry["provinces"]
                ])
                cur.execute(
                    f"SELECT province_code,province_name,initial_phase_target,status,province_state "
                    f"FROM {TABLE} ORDER BY province_code")
                rows = cur.fetchall()
                _from_rows(rows)
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Private province coverage initialization failed") from None
    return len(rows)


def initialize_and_read(connection):
    """Ensure all 81 rows exist, then return the validated registry.

    Apply migration 016 once via deployment, then call this before building a
    workbook. Existing state is preserved; this helper performs no scans and
    writes no lead or CRM data.
    """
    initialize(connection)
    return read(connection)

def read(connection):
    """Read the complete 81-row state table; missing rows are never inferred."""
    try:
        with connection.cursor() as cur:
            cur.execute(
                f"SELECT province_code,province_name,initial_phase_target,status,province_state "
                f"FROM {TABLE} ORDER BY province_code")
            return _from_rows(cur.fetchall())
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Private province coverage read failed") from None


def _mutate(connection, province_code, transition, *args, **kwargs):
    """Serialize one transition and commit only validated, idempotent state."""
    try:
        with connection.transaction():
            with connection.cursor() as cur:
                # One small global lock prevents lost updates while the ledger
                # is being initialized or reconstructed from all 81 rows.
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
                cur.execute(
                    f"SELECT province_code,province_name,initial_phase_target,status,province_state "
                    f"FROM {TABLE} ORDER BY province_code FOR UPDATE")
                before = _from_rows(cur.fetchall())
                after = transition(before, province_code, *args, **kwargs)
                model.coverage_table(after)
                old_by_code = {p["code"]: p for p in before["provinces"]}
                for state in after["provinces"]:
                    old = old_by_code[state["code"]]
                    if state == old:
                        continue
                    cur.execute(
                        f"UPDATE {TABLE} SET province_name=%s,initial_phase_target=%s,"
                        f"status=%s,province_state=%s::jsonb,updated_at=now() "
                        f"WHERE province_code=%s",
                        (state["name"], state["initial_phase_target"], state["status"],
                         json.dumps(state, ensure_ascii=False), state["code"]))
                    if cur.rowcount != 1:
                        raise RuntimeError("Province coverage update lost its target row")
                return after
    except ValueError:
        raise
    except RuntimeError:
        raise
    except Exception:
        raise RuntimeError("Private province coverage update failed") from None


def configure_plan(connection, province_code, **kwargs):
    return _mutate(connection, province_code, model.configure_plan, **kwargs)


def begin_attempt(connection, province_code, **kwargs):
    return _mutate(connection, province_code, model.begin_attempt, **kwargs)


def record_item_result(connection, province_code, attempt_id, item_id, **kwargs):
    return _mutate(connection, province_code, model.record_item_result,
                    attempt_id, item_id, **kwargs)


def finish_attempt(connection, province_code, attempt_id, **kwargs):
    return _mutate(connection, province_code, model.finish_attempt,
                    attempt_id, **kwargs)


def commit_district_batch(connection, province_code, attempt_id, item_id, *,
                          leads, records_count, observed_at, source_url,
                          source_data_at, source_sha256):
    """Atomically persist one successful district receipt and its new leads.

    The PBF digest and a canonical lead-payload digest are attached to the
    receipt for auditable replay. Existing CRM rows are never overwritten;
    inserts, optional first-stage lifecycle events, and the receipt share one
    PostgreSQL transaction. A retry with identical input is a no-op replay.
    """
    if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
        raise ValueError("District receipt requires a lowercase PBF SHA-256")
    if not isinstance(leads, (list, tuple)) or len(leads) > MAX_DISTRICT_LEADS:
        raise ValueError("District lead batch must be a bounded list of at most 1000 leads")
    normalized = []
    seen = set()
    for lead in leads:
        if not isinstance(lead, dict):
            raise ValueError("District batch lead must be an object")
        lead = dict(lead)
        lead_id = lead.get("id")
        if not isinstance(lead_id, str) or not _OSM_ID.fullmatch(lead_id):
            raise ValueError("District batch lead must have a valid OSM ID")
        if lead_id in seen:
            raise ValueError("District batch contains duplicate OSM IDs")
        seen.add(lead_id)
        normalized.append(lead)
    if isinstance(records_count, bool) or not isinstance(records_count, int) or records_count < len(normalized):
        raise ValueError("District source count must cover every candidate lead")

    # Bind receipt replay to the exact payload and source snapshot. This makes
    # a retry after a lost worker response safe without silently accepting a
    # different extraction for the same district attempt.
    canonical = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":"), allow_nan=False)
    batch_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    provenance = {"province_code": province_code,
                  "district_relation_id": item_id,
                  "source_url": source_url,
                  "source_data_at": str(source_data_at),
                  "source_sha256": source_sha256}
    enriched = []
    for lead in normalized:
        row = dict(lead)
        prior = row.get("discovery_provenance")
        if prior is not None and prior != provenance:
            raise ValueError("Lead provenance conflicts with its district receipt")
        row["discovery_provenance"] = provenance
        enriched.append(row)

    try:
        with connection.transaction():
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
                cur.execute(
                    f"SELECT province_code,province_name,initial_phase_target,status,province_state "
                    f"FROM {TABLE} ORDER BY province_code FOR UPDATE")
                before = _from_rows(cur.fetchall())
                current = model._registry(before)[province_code]
                attempts = [a for a in current["attempts"]
                            if a["attempt_id"] == attempt_id]
                if (current["status"] != "running" or not attempts
                        or attempts[-1]["finished_at"]):
                    raise ValueError("No matching active district scan attempt")
                attempt = attempts[-1]
                if item_id not in attempt["planned_item_ids"]:
                    raise ValueError("District is outside the bounded active attempt")
                if attempt.get("source_sha256") != source_sha256:
                    raise ValueError("District batch digest does not match its active attempt snapshot")

                expected = {
                    "state": "success", "observed_at": str(observed_at),
                    "source_data_at": str(source_data_at),
                    "source_url": model._url(source_url, "Receipt source"),
                    "records_count": records_count,
                    "source_sha256": source_sha256,
                    "lead_batch_sha256": batch_sha256,
                    "lead_count": len(enriched),
                }
                old = attempt["results"].get(item_id)
                if old is not None:
                    if old != expected or current["completed_items"].get(item_id) != expected:
                        raise ValueError("District receipt already exists with different evidence")
                    # The lead rows and receipt committed together; replay must
                    # not touch any CRM or ledger values.
                    return {"registry": before, "new_leads": 0, "replayed": True}

                after = model.record_item_result(
                    before, province_code, attempt_id, item_id,
                    succeeded=True, observed_at=observed_at,
                    source_url=source_url, source_data_at=source_data_at,
                    records_count=records_count)
                entry = model._registry(after)[province_code]
                receipt = entry["attempts"][-1]["results"][item_id]
                receipt.update(source_sha256=source_sha256,
                               lead_batch_sha256=batch_sha256,
                               lead_count=len(enriched))
                entry["completed_items"][item_id].update(receipt)

                inserted_ids = []
                for lead in enriched:
                    cur.execute(
                        "INSERT INTO owner_leads(osm_id,lead_data,status) "
                        "VALUES (%s,%s::jsonb,'review') ON CONFLICT(osm_id) DO NOTHING "
                        "RETURNING osm_id",
                        (lead["id"], json.dumps(lead, ensure_ascii=False,
                                                sort_keys=True, allow_nan=False)))
                    inserted = cur.fetchone()
                    if inserted is not None:
                        inserted_ids.append(lead["id"])

                # Refresh observations for pre-existing OSM objects as review
                # proposals only. Never overwrite the stored lead, contact
                # eligibility, owner decision, or delivery state.
                cur.execute(
                    "SELECT osm_id,lead_data FROM owner_leads WHERE osm_id=ANY(%s)",
                    (list(seen),),
                )
                stored_rows = cur.fetchall()
                stored = {
                    osm_id: (json.loads(payload) if isinstance(payload, str) else payload)
                    for osm_id, payload in stored_rows
                }
                if set(stored) != seen:
                    raise RuntimeError("District batch could not reload every stored OSM object")
                changed_rows = []
                inserted_set = set(inserted_ids)
                for lead in normalized:
                    if lead["id"] in inserted_set:
                        continue
                    fields = _changed_source_fields(stored[lead["id"]], lead)
                    if fields:
                        changed_rows.append((lead["id"], fields, lead))
                if changed_rows:
                    cur.execute("SELECT to_regclass('owner_osm_incremental_changes')")
                    if cur.fetchone()[0] is None:
                        raise RuntimeError(
                            "OSM changed-business review migration 009 is not installed"
                        )
                    queued_changes = 0
                    for lead_id, fields, proposed in changed_rows:
                        cur.execute(
                            "INSERT INTO owner_osm_incremental_changes"
                            "(osm_id,snapshot_sha256,source_data_at,fields_changed,"
                            "proposed_lead) VALUES (%s,%s,%s,%s,%s::jsonb)"
                            " ON CONFLICT(osm_id) DO UPDATE SET "
                            "snapshot_sha256=EXCLUDED.snapshot_sha256,"
                            "source_data_at=EXCLUDED.source_data_at,"
                            "fields_changed=EXCLUDED.fields_changed,"
                            "proposed_lead=EXCLUDED.proposed_lead,"
                            "review_state='needs_review',observed_at=now() "
                            "WHERE owner_osm_incremental_changes.source_data_at "
                            "< EXCLUDED.source_data_at RETURNING osm_id",
                            (lead_id, source_sha256, source_data_at, list(fields),
                             json.dumps(proposed, ensure_ascii=False, sort_keys=True,
                                        allow_nan=False)),
                        )
                        queued_changes += int(cur.fetchone() is not None)
                else:
                    queued_changes = 0

                # Keep discovery-stage history in the same transaction when
                # the optional lifecycle migration is installed. Legacy rows
                # are never retroactively initialized.
                if inserted_ids:
                    cur.execute("SELECT to_regclass('owner_lead_lifecycle_state')")
                    if cur.fetchone()[0] is not None:
                        from .lifecycle_store import record_transition
                        for lead_id in inserted_ids:
                            record_transition(
                                connection, lead_id, "new_discovered",
                                idempotency_key=f"discover:{lead_id}",
                                reason="New OSM business registered from a verified district PBF snapshot",
                                evidence_refs=(f"osm://{lead_id}",
                                               f"osm://{item_id}",
                                               source_url))

                model.coverage_table(after)
                state = model._registry(after)[province_code]
                cur.execute(
                    f"UPDATE {TABLE} SET province_name=%s,initial_phase_target=%s,"
                    f"status=%s,province_state=%s::jsonb,updated_at=now() "
                    "WHERE province_code=%s",
                    (state["name"], state["initial_phase_target"], state["status"],
                     json.dumps(state, ensure_ascii=False), province_code))
                if cur.rowcount != 1:
                    raise RuntimeError("District receipt update lost its province row")
        return {"registry": after, "new_leads": len(inserted_ids),
                "changed_existing": queued_changes, "replayed": False}
    except (ValueError, RuntimeError):
        raise
    except Exception:
        raise RuntimeError("Atomic district lead and receipt commit failed") from None
