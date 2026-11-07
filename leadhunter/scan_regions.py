"""Bounded, repeat-safe hourly OSM pilot-area selection.

This changes only which small public OSM area is researched. It does not
change message recipients, sending permissions, or the global seen-ID ledger.
One scan still makes one bounded Overpass query (with existing failover).
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DEFAULT_BBOX = "40.982,29.015,41.008,29.055"

# Adjacent small Istanbul pilot areas. No larger bulk OSM request is made.
# Each window is below the core bbox_parse public API safety limits.
PILOT_BBOXES = (
    DEFAULT_BBOX,
    "40.963,29.055,40.992,29.095",
    "40.992,29.055,41.020,29.095",
    "40.975,29.095,41.003,29.135",
    "40.946,29.015,40.975,29.055",
    "40.955,29.095,40.982,29.135",
    "41.003,29.095,41.031,29.135",
    "40.982,29.135,41.010,29.175",
)


def select_bbox(env, now=None):
    """Return (bbox, public-safe slot label); an explicit override wins."""
    override = str(env.get("SCAN_BBOX") or "").strip()
    if override:
        return override, "explicit_override"
    if str(env.get("SCAN_ROTATE_BBOX") or "").strip().lower() != "true":
        return DEFAULT_BBOX, "default"
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("Region rotation requires a timezone-aware datetime")
    local_hour = current.astimezone(ZoneInfo("Europe/Istanbul")).hour
    slot = local_hour % len(PILOT_BBOXES)
    return PILOT_BBOXES[slot], f"pilot_{slot+1}_of_{len(PILOT_BBOXES)}"
