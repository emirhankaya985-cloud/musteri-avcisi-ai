"""Bounded public Overpass read-only tile research for production coverage.

Never use OSM's *editing* API for scheduled data extraction. Use a single
listed Overpass instance per run (no 429/403 mirror hopping), at most two
small 0.005-degree queries, and a durable success-only public cursor.
Data: © OpenStreetMap contributors, ODbL.
"""
import json
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .osm_direct import (_tiles, MAX_RESPONSE_BYTES, MAX_TILES,
                         OSMProviderStop)

# Existing read-only source already used by the legacy Overpass scanner.
# One fixed host per visit, no parallel requests and no rate-limit evasions.
READONLY_OVERPASS = "https://overpass.private.coffee/api/interpreter"
USER_AGENT = (
    "MusteriAvcisiAI/0.3 (owner-only bounded OSM research; "
    "https://www.openstreetmap.org/copyright)"
)
ALLOWED_TAGS = frozenset((
    "name", "shop", "amenity", "website", "contact:website",
    "contact:phone", "phone", "email", "contact:email",
    "addr:street", "addr:housenumber", "addr:district",
))


def _query(bbox):
    south, west, north, east = bbox
    values = ",".join(str(v) for v in (south, west, north, east))
    return (
        "[out:json][timeout:20];("
        f'nwr["amenity"="car_wash"]({values});'
        f'nwr["shop"="hairdresser"]({values});'
        f'nwr["shop"="beauty"]({values});'
        f'nwr["shop"="florist"]({values});'
        f'nwr["shop"="optician"]({values});'
        ");out center tags 200;"
    )


def _read_one(box, opener):
    query = _query(box)
    req = Request(
        READONLY_OVERPASS,
        data=urlencode({"data":query}).encode("utf-8"),
        headers={"User-Agent":USER_AGENT,
                 "Content-Type":"application/x-www-form-urlencoded"},
    )
    try:
        with opener(req, timeout=22) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ValueError("Overpass response too large")
        parsed = json.loads(payload)
        if (not isinstance(parsed, dict) or parsed.get("remark") or
                not isinstance(parsed.get("elements"), list)):
            raise ValueError("Malformed or provider-limited Overpass response")
        return parsed["elements"]
    except HTTPError as exc:
        if exc.code in (400, 401, 403, 406, 429):
            raise OSMProviderStop(
                "Public read-only Overpass refused request (HTTP " +
                str(exc.code) + "); no bypass") from None
        raise RuntimeError("Read-only OSM provider temporarily unavailable") from None
    except (URLError, TimeoutError, OSError, ValueError, TypeError):
        raise RuntimeError("Read-only OSM provider temporarily unavailable") from None


def get_overpass_tiles(bbox, opener=urlopen, *, day=None, hour=None,
                       rotation_period=1, max_tiles=MAX_TILES,
                       tile_start=None, tile_results=None):
    """No source switching; only two small sequential read-only requests."""
    if type(max_tiles) is not int or not 0 <= max_tiles <= MAX_TILES:
        raise ValueError("Unsafe Overpass tile count")
    if tile_results is not None and not isinstance(tile_results, list):
        raise ValueError("Expected an explicit tile result list")
    if day is None:
        current = datetime.now(ZoneInfo("Europe/Istanbul"))
        day = current.date()
        hour = current.hour if hour is None else hour
    elif hour is None:
        hour = 0
    found = {}
    successful = 0
    for west, south, east, north in _tiles(
            bbox, day, max_tiles, hour=hour, rotation_period=rotation_period,
            start_index=tile_start):
        try:
            elements = _read_one((south, west, north, east), opener)
            successful += 1
            if tile_results is not None:
                tile_results.append(True)
            for row in elements:
                if not isinstance(row, dict):
                    continue
                tags = row.get("tags")
                typ, oid = row.get("type"), row.get("id")
                if (typ not in ("node", "way", "relation") or
                        type(oid) is not int or not isinstance(tags, dict) or
                        not str(tags.get("name") or "").strip()):
                    continue
                if tags.get("shop") not in (
                        "hairdresser", "beauty", "florist", "optician") and (
                        tags.get("amenity") != "car_wash"):
                    continue
                found[(typ, oid)] = {
                    "type":typ, "id":oid,
                    "tags": {key:value for key,value in tags.items()
                             if key in ALLOWED_TAGS}
                }
        except OSMProviderStop:
            if tile_results is not None:
                tile_results.append(False)
            raise
        except RuntimeError:
            if tile_results is not None:
                tile_results.append(False)
            # The failed tile must be retried on the next normal visit;
            # never invent map coverage and never switch providers.
            break
    if not successful:
        raise RuntimeError("No confirmed read-only Overpass tile; cursor unchanged")
    return list(found.values())
