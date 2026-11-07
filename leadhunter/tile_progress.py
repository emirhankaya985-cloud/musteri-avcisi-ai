"""Public OSM tile success ledger; no customer or contact information.

Only small map requests accepted by the primary OSM API advance coverage.
A slow, missing or skipped GitHub schedule never advances the cursor.
The hourly workflow serializes writers and commits this state with seen IDs.
"""
import json
import math
import re
from pathlib import Path
from .osm_direct import TILE_DEGREES, MAX_TILES


def tile_total(bbox):
    south, west, north, east = bbox
    return (math.ceil((north - south) / TILE_DEGREES) *
            math.ceil((east - west) / TILE_DEGREES))


def _validate_slot(slot):
    if not isinstance(slot, str) or not re.fullmatch(r"pilot_[1-8]_of_8", slot):
        raise ValueError("Tile ledger requires a known eight-region pilot slot")


def _load(path):
    path = Path(path)
    if not path.exists():
        return {"version": 1, "regions": {}}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        raise RuntimeError("Corrupt public tile ledger; refusing to skip any tiles") from None
    if (not isinstance(document, dict) or document.get("version") != 1 or
            not isinstance(document.get("regions"), dict)):
        raise RuntimeError("Invalid tile ledger format")
    for slot, entry in document["regions"].items():
        _validate_slot(slot)
        if (not isinstance(entry, dict) or
                any(type(entry.get(k)) is not int for k in ("next", "total", "cycle")) or
                entry["total"] < 1 or entry["cycle"] < 0 or
                not 0 <= entry["next"] <= entry["total"] or
                type(entry.get("stalls", 0)) is not int or
                not 0 <= entry.get("stalls", 0) <= 1_000_000):
            raise RuntimeError("Invalid tile progress; fail closed")
    return document


def plan(path, slot, bbox):
    """Return deterministic, bounded next tile window, WITHOUT modifying state."""
    _validate_slot(slot)
    total = tile_total(bbox)
    if total <= 0:
        raise ValueError("Invalid pilot tile dimensions")
    entry = _load(path)["regions"].get(slot)
    if entry and entry["total"] != total:
        raise RuntimeError("OSM pilot geometry changed; migration required")
    cursor = entry["next"] if entry else 0
    start = 0 if cursor == total else cursor
    return {"start": start, "maximum": min(MAX_TILES, total - start),
            "total": total, "completed": cursor,
            "cycle": (entry["cycle"] if entry else 0) + int(cursor == total),
            "stalls": entry.get("stalls", 0) if entry else 0}


def commit(path, slot, bbox, expected_start, successful_prefix, *, attempted=None):
    """Commit only consecutive successful map tiles after owner/CRM side effects."""
    _validate_slot(slot)
    if type(successful_prefix) is not int or not 0 <= successful_prefix <= MAX_TILES:
        raise ValueError("Invalid confirmed tile count")
    current = plan(path, slot, bbox)
    if current["start"] != expected_start:
        raise RuntimeError("Tile cursor changed while scanning; abort stale commit")
    if successful_prefix > current["maximum"]:
        raise ValueError("Tile success exceeds requested bounded window")
    if attempted is not None and (type(attempted) is not int or
                                  not successful_prefix <= attempted <= current["maximum"]):
        raise ValueError("Invalid number of attempted map tiles")
    failed = attempted is not None and attempted > successful_prefix
    if successful_prefix == 0 and not failed:
        return current
    data = _load(path)
    completed = expected_start + successful_prefix
    stalls = (current["stalls"] + 1 if failed and not successful_prefix else
              1 if failed else 0)
    entry = {"next": completed, "total": current["total"], "cycle": current["cycle"],
             "stalls": min(stalls, 1_000_000)}
    data["regions"][slot] = entry
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    tmp = file.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n",
                   encoding="utf-8")
    tmp.replace(file)
    return {"start": completed, "maximum": min(MAX_TILES, current["total"] - completed),
            "total": current["total"], "completed": completed, "cycle": entry["cycle"],
            "stalls": entry["stalls"]}


def aggregate(path):
    """Only confirmed sample tiles. Untouched regions count as 0, never PASS."""
    document = _load(path)
    done = total = 0
    for index, box in enumerate(__import__(
            "leadhunter.scan_regions", fromlist=["PILOT_BBOXES"]).PILOT_BBOXES, 1):
        from .core import bbox_parse
        count = tile_total(bbox_parse(box))
        key = f"pilot_{index}_of_8"
        entry = document["regions"].get(key)
        if entry and entry["total"] != count:
            raise RuntimeError("OSM coverage geometry mismatch")
        total += count
        done += entry["next"] if entry else 0
    return done, total
