"""Atomic Neon persistence for the evidence-gated province coverage ledger.

This repository is an offline/persistence boundary only. It does not fetch OSM
data, write customer leads, or mark a province complete without source receipts
validated by :mod:`province_coverage`.
"""
from __future__ import annotations

import json

from . import province_coverage as model

LOCK_ID = 985_402_618
TABLE = "owner_province_scan_coverage"


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
