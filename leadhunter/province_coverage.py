"""Evidence-gated, resumable coverage ledger for Turkey's 81 provinces.

This module is an offline state model only. It does not issue OSM requests or
write CRM rows. A caller must provide a checksum-identified boundary/work-item
manifest before it can begin an attempt. Existing Kadikoy pilot work is kept
outside this national ledger so it cannot be mistaken for province-wide scan
coverage.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from urllib.parse import urlsplit

SCHEMA_VERSION = 1
STATUS_VALUES = ("pending", "running", "completed", "partial", "failed")

# Official province license-plate codes are stable identifiers. Names are
# Turkish administrative province names; no geometry is inferred from names.
PROVINCES = (
    ("01", "Adana"), ("02", "Adıyaman"), ("03", "Afyonkarahisar"),
    ("04", "Ağrı"), ("05", "Amasya"), ("06", "Ankara"),
    ("07", "Antalya"), ("08", "Artvin"), ("09", "Aydın"),
    ("10", "Balıkesir"), ("11", "Bilecik"), ("12", "Bingöl"),
    ("13", "Bitlis"), ("14", "Bolu"), ("15", "Burdur"),
    ("16", "Bursa"), ("17", "Çanakkale"), ("18", "Çankırı"),
    ("19", "Çorum"), ("20", "Denizli"), ("21", "Diyarbakır"),
    ("22", "Edirne"), ("23", "Elazığ"), ("24", "Erzincan"),
    ("25", "Erzurum"), ("26", "Eskişehir"), ("27", "Gaziantep"),
    ("28", "Giresun"), ("29", "Gümüşhane"), ("30", "Hakkâri"),
    ("31", "Hatay"), ("32", "Isparta"), ("33", "Mersin"),
    ("34", "İstanbul"), ("35", "İzmir"), ("36", "Kars"),
    ("37", "Kastamonu"), ("38", "Kayseri"), ("39", "Kırklareli"),
    ("40", "Kırşehir"), ("41", "Kocaeli"), ("42", "Konya"),
    ("43", "Kütahya"), ("44", "Malatya"), ("45", "Manisa"),
    ("46", "Kahramanmaraş"), ("47", "Mardin"), ("48", "Muğla"),
    ("49", "Muş"), ("50", "Nevşehir"), ("51", "Niğde"),
    ("52", "Ordu"), ("53", "Rize"), ("54", "Sakarya"),
    ("55", "Samsun"), ("56", "Siirt"), ("57", "Sinop"),
    ("58", "Sivas"), ("59", "Tekirdağ"), ("60", "Tokat"),
    ("61", "Trabzon"), ("62", "Tunceli"), ("63", "Şanlıurfa"),
    ("64", "Uşak"), ("65", "Van"), ("66", "Yozgat"),
    ("67", "Zonguldak"), ("68", "Aksaray"), ("69", "Bayburt"),
    ("70", "Karaman"), ("71", "Kırıkkale"), ("72", "Batman"),
    ("73", "Şırnak"), ("74", "Bartın"), ("75", "Ardahan"),
    ("76", "Iğdır"), ("77", "Yalova"), ("78", "Karabük"),
    ("79", "Kilis"), ("80", "Osmaniye"), ("81", "Düzce"),
)

# Explicitly requested in an earlier user message; do not derive from an
# assumed commercial priority order.
INITIAL_PHASE_CITY_CODES = ("34", "06", "35", "16", "07", "41", "54", "42", "27", "38")
ERROR_CODES = ("timeout", "rate_limited", "source_unavailable",
               "invalid_response", "other")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _aware(value, label):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def _url(value, label):
    parsed = urlsplit(str(value or ""))
    if (parsed.scheme != "https" or not parsed.netloc or parsed.username
            or parsed.password):
        raise ValueError(f"{label} must be an HTTPS source URL")
    return str(value)


def _registry(registry):
    if not isinstance(registry, dict) or registry.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported province coverage schema")
    entries = registry.get("provinces")
    if not isinstance(entries, list) or len(entries) != len(PROVINCES):
        raise ValueError("Coverage registry must contain exactly 81 provinces")
    expected = {code: name for code, name in PROVINCES}
    actual = {entry.get("code"): entry for entry in entries if isinstance(entry, dict)}
    if len(actual) != 81 or set(actual) != set(expected):
        raise ValueError("Coverage registry province codes are incomplete or duplicated")
    for code, entry in actual.items():
        if entry.get("name") != expected[code] or entry.get("status") not in STATUS_VALUES:
            raise ValueError("Coverage registry has an invalid province record")
    return actual


def new_registry():
    """Return 81 pending rows. Pending means no national coverage is claimed."""
    target_codes = set(INITIAL_PHASE_CITY_CODES)
    return {
        "schema_version": SCHEMA_VERSION,
        "provinces": [
            {"code": code, "name": name,
             "initial_phase_target": code in target_codes,
             "status": "pending", "plan": None,
             "completed_items": {}, "attempts": [],
             "updated_at": None}
            for code, name in PROVINCES
        ],
    }


def configure_plan(registry, province_code, *, source_url, source_sha256,
                   work_item_ids, excluded_item_ids=(), configured_at):
    """Install a reviewed boundary/partition manifest; never marks work done.

    Exclusions are explicit item IDs already covered by another system, such
    as the existing Kadıköy pilot. They stay visible in the manifest but are
    never counted as scanned by this national ledger.
    """
    current = _registry(registry)
    if province_code not in current:
        raise ValueError("Unknown province code")
    if current[province_code]["status"] == "running":
        raise ValueError("Cannot replace a plan during an active attempt")
    if (current[province_code].get("plan") is not None
            and current[province_code].get("completed_items")):
        raise ValueError("Plan is immutable after source receipts exist")
    source_url = _url(source_url, "Plan source")
    if not isinstance(source_sha256, str) or not _SHA256.fullmatch(source_sha256):
        raise ValueError("Plan source requires a lowercase SHA-256")
    _aware(configured_at, "configured_at")
    items = list(work_item_ids)
    excluded = set(excluded_item_ids)
    if (not items or any(not isinstance(x, str) or not x.strip() for x in items)
            or len(items) != len(set(items))):
        raise ValueError("Plan work item IDs must be nonempty, unique strings")
    if not excluded <= set(items):
        raise ValueError("Excluded pilot items must be present in the source manifest")
    if len(excluded) == len(items):
        raise ValueError("A plan cannot consist only of excluded pilot items")
    result = deepcopy(registry)
    entry = _registry(result)[province_code]
    entry["plan"] = {
        "source_url": source_url, "source_sha256": source_sha256,
        "configured_at": str(configured_at), "work_item_ids": items,
        "excluded_item_ids": sorted(excluded),
    }
    entry["status"] = "pending"
    entry["updated_at"] = str(configured_at)
    return result


def begin_attempt(registry, province_code, *, attempt_id, started_at):
    """Start one serialized bounded attempt; successful items remain resumable."""
    current = _registry(registry)
    if province_code not in current:
        raise ValueError("Unknown province code")
    _aware(started_at, "started_at")
    result = deepcopy(registry)
    entry = _registry(result)[province_code]
    plan = entry.get("plan")
    if not isinstance(plan, dict):
        raise ValueError("Province boundary/work-item manifest is not configured")
    if entry["status"] == "running":
        raise ValueError("Province already has a running attempt")
    if entry["status"] == "completed":
        raise ValueError("Completed province cannot be scanned again by first-pass workflow")
    if not isinstance(attempt_id, str) or not attempt_id.strip():
        raise ValueError("attempt_id is required for idempotent resumption")
    if any(a["attempt_id"] == attempt_id for a in entry["attempts"]):
        raise ValueError("attempt_id already exists")
    excluded = set(plan["excluded_item_ids"])
    remaining = [item for item in plan["work_item_ids"]
                 if item not in excluded and item not in entry["completed_items"]]
    if not remaining:
        raise ValueError("No uncompleted work items remain")
    entry["attempts"].append({
        "attempt_id": attempt_id, "started_at": str(started_at),
        "planned_item_ids": remaining, "results": {}, "finished_at": None,
    })
    entry["status"] = "running"
    entry["updated_at"] = str(started_at)
    return result


def record_item_result(registry, province_code, attempt_id, item_id, *,
                       succeeded, observed_at, error_code=None, source_url=None,
                       source_data_at=None, records_count=None):
    """Record a source receipt or bounded failure without storing business data."""
    current = _registry(registry)
    if province_code not in current:
        raise ValueError("Unknown province code")
    _aware(observed_at, "observed_at")
    result = deepcopy(registry)
    entry = _registry(result)[province_code]
    attempts = [a for a in entry["attempts"] if a["attempt_id"] == attempt_id]
    if entry["status"] != "running" or not attempts or attempts[-1]["finished_at"]:
        raise ValueError("No matching active attempt")
    attempt = attempts[-1]
    if item_id not in attempt["planned_item_ids"]:
        raise ValueError("Work item is outside the bounded attempt")
    prior = attempt["results"].get(item_id)
    if prior is not None:
        raise ValueError("Work item already has a result in this attempt")
    if succeeded:
        if error_code is not None:
            raise ValueError("Successful item cannot also have an error")
        if isinstance(records_count, bool) or not isinstance(records_count, int) or records_count < 0:
            raise ValueError("Successful receipt requires a non-negative record count")
        _aware(source_data_at, "source_data_at")
        receipt = {
            "state": "success", "observed_at": str(observed_at),
            "source_data_at": str(source_data_at),
            "source_url": _url(source_url, "Receipt source"),
            "records_count": records_count,
        }
        entry["completed_items"][item_id] = receipt
    else:
        if error_code not in ERROR_CODES:
            raise ValueError("Failure requires a bounded error code")
        receipt = {"state": "failed", "observed_at": str(observed_at),
                   "error_code": error_code}
    attempt["results"][item_id] = receipt
    entry["updated_at"] = str(observed_at)
    return result


def finish_attempt(registry, province_code, attempt_id, *, finished_at):
    """Close attempt and derive truthful province status from item receipts."""
    current = _registry(registry)
    if province_code not in current:
        raise ValueError("Unknown province code")
    _aware(finished_at, "finished_at")
    result = deepcopy(registry)
    entry = _registry(result)[province_code]
    attempts = [a for a in entry["attempts"] if a["attempt_id"] == attempt_id]
    if entry["status"] != "running" or not attempts or attempts[-1]["finished_at"]:
        raise ValueError("No matching active attempt")
    attempt = attempts[-1]
    attempt["finished_at"] = str(finished_at)
    required = set(entry["plan"]["work_item_ids"]) - set(entry["plan"]["excluded_item_ids"])
    completed = set(entry["completed_items"]) & required
    failed = any(r["state"] == "failed" for r in attempt["results"].values())
    if required <= completed:
        entry["status"] = "completed"
    elif completed:
        entry["status"] = "partial"
    elif failed:
        entry["status"] = "failed"
    else:
        # An attempt with no receipts did not prove coverage.
        entry["status"] = "failed"
    entry["updated_at"] = str(finished_at)
    return result


def coverage_table(registry):
    """Return compact province coverage rows suitable for a CRM/report tab."""
    entries = _registry(registry)
    rows = []
    for code, name in PROVINCES:
        entry = entries[code]
        plan = entry.get("plan") or {}
        total = len(set(plan.get("work_item_ids", ())) -
                    set(plan.get("excluded_item_ids", ())))
        completed = len(set(entry.get("completed_items", {})) &
                        set(plan.get("work_item_ids", ())) -
                        set(plan.get("excluded_item_ids", ())))
        rows.append({
            "code": code, "province": name,
            "initial_phase_target": code in INITIAL_PHASE_CITY_CODES,
            "status": entry["status"], "completed_items": completed,
            "total_items": total,
            "coverage_percent": round(completed * 100 / total) if total else None,
            "source_url": plan.get("source_url"),
            "source_data_at": max(
                (r["source_data_at"] for r in entry.get("completed_items", {}).values()),
                default=None),
            "updated_at": entry.get("updated_at"),
        })
    return rows
