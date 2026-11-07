"""Low-volume direct OSM API fallback when Overpass is inaccessible.

OpenStreetMap API 0.6 GET /map.json and batch /nodes.json, /ways.json.
Keep the owner's existing public OSM identifiers available for one-time
Telegram review, and inspect at most two small map tiles per run for new
businesses. No scraping, login, marketing, or private business contacts.
Data: © OpenStreetMap contributors (ODbL).
"""
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

MAIN_API = "https://api.openstreetmap.org/api/0.6"
USER_AGENT = "MusteriAvcisiAI/0.2 (small owner-only research; https://www.openstreetmap.org/copyright)"
MAX_RESPONSE_BYTES = 8_000_000
TILE_DEGREES = 0.005
MAX_TILES = 2


class OSMProviderStop(RuntimeError):
    """Public provider rejected the request; do not retry or switch servers."""


# Keep direct fallback's shop coverage aligned with the Overpass query.
SUPPORTED_SHOPS = frozenset(("hairdresser", "beauty", "florist", "optician"))


def _get_json(url, opener, timeout=18):
    req = Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    try:
        with opener(req, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("OSM response exceeds bounded response limit")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("elements"), list):
            raise ValueError("Unexpected OSM response format")
        return data["elements"]
    except HTTPError as exc:
        if exc.code in (400, 401, 403, 429):
            # Obey rate limits, invalid requests and explicit provider denial.
            raise OSMProviderStop(
                "Official OSM API rejected request; no bypass or retry (HTTP " +
                str(exc.code) + ")") from None
        raise RuntimeError("Direct OSM API temporarily unavailable; no data invented") from None
    except (URLError, OSError, TimeoutError, ValueError, TypeError):
        raise RuntimeError("Direct OSM API temporarily unavailable; no data invented") from None


def _tiles(box, day, maximum=MAX_TILES, *, hour=0, rotation_period=1,
           start_index=None):
    south, west, north, east = box
    if (type(rotation_period) is not int or rotation_period < 1
            or 24 % rotation_period != 0):
        raise ValueError("Invalid OSM region rotation period")
    rows = max(1, math.ceil((north - south) / TILE_DEGREES))
    cols = max(1, math.ceil((east - west) / TILE_DEGREES))
    # For N hourly regions, this bbox is visited once every N hours.
    # Index by *visits to the region*, not wall-clock hours, otherwise
    # modulo arithmetic gets stuck on the same N-tile residue classes.
    # Re-runs in the same hour always inspect the same bounded sample.
    count = min(maximum, rows * cols)
    visits = (day.toordinal() * 24 + hour) // rotation_period
    start = visits * maximum % (rows * cols)
    if start_index is not None:
        if type(start_index) is not int or not 0 <= start_index < rows * cols:
            raise ValueError("Invalid persisted OSM map tile cursor")
        start = start_index
        count = min(count, rows * cols - start)
    for i in range(count):
        index = (start + i) % (rows * cols)
        row, col = divmod(index, cols)
        a = south + row * TILE_DEGREES
        b = west + col * TILE_DEGREES
        yield (
            round(b, 6), round(a, 6),
            round(min(east, b + TILE_DEGREES), 6),
            round(min(north, a + TILE_DEGREES), 6),
        )


def get_osm_direct(bbox, seen_ids=(), opener=urlopen, *, day=None, hour=None,
                   max_tiles=MAX_TILES, rotation_period=1,
                   tile_start=None, tile_results=None):
    """Fetch previous public OSM IDs + tiny rotating tiles, fail closed.

    This is intentionally a degraded small-area fallback. It must not be
    misreported as a comprehensive, up-to-date search of the entire bbox.
    """
    if type(max_tiles) is not int or not 0 <= max_tiles <= MAX_TILES:
        raise ValueError("Invalid direct OSM tile limit")
    if len(bbox) != 4 or not (
        -90 <= bbox[0] < bbox[2] <= 90 and -180 <= bbox[1] < bbox[3] <= 180
    ):
        raise ValueError("Invalid OSM bounding box")
    if day is None:
        now = datetime.now(ZoneInfo("Europe/Istanbul"))
        day = now.date()
        hour = now.hour if hour is None else hour
    elif hour is None:
        hour = 0
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError("Invalid direct OSM scan hour")
    if (type(rotation_period) is not int or rotation_period < 1
            or 24 % rotation_period != 0):
        raise ValueError("Invalid direct OSM region period")
    if tile_results is not None and not isinstance(tile_results, list):
        raise ValueError("Tile scan result collector must be a list")
    found, successes = {}, 0
    # At most 150 previously visible public OSM IDs, no private list.
    ids = {"node": [], "way": [], "relation": []}
    for osm_id in sorted(set(seen_ids)):
        if not isinstance(osm_id, str):
            continue
        typ, sep, value = osm_id.partition("/")
        if sep and typ in ids and value.isdecimal() and len(value) <= 19:
            ids[typ].append(value)
    for typ, plural in (("node", "nodes"), ("way", "ways"), ("relation", "relations")):
        if not ids[typ]:
            continue
        # Bounded batch size to avoid resource-intensive primary API usage.
        url = MAIN_API + "/" + plural + ".json?" + urlencode(
            {plural: ",".join(ids[typ][:150])})
        try:
            elements = _get_json(url, opener)
            successes += 1
            for row in elements:
                if isinstance(row, dict):
                    found.setdefault((row.get("type"), row.get("id")), row)
        except OSMProviderStop:
            raise
        except RuntimeError:
            pass

    for west, south, east, north in _tiles(
            bbox, day, max_tiles, hour=hour, rotation_period=rotation_period,
            start_index=tile_start):
        url = MAIN_API + "/map.json?" + urlencode(
            {"bbox": f"{west},{south},{east},{north}"})
        try:
            elements = _get_json(url, opener)
            successes += 1
            if tile_results is not None:
                tile_results.append(True)
            for row in elements:
                if not isinstance(row, dict):
                    continue
                tags = row.get("tags") or {}
                if not isinstance(tags, dict) or not str(tags.get("name") or "").strip():
                    continue
                if tags.get("shop") not in SUPPORTED_SHOPS and (
                    tags.get("amenity") != "car_wash"):
                    continue
                found.setdefault((row.get("type"), row.get("id")), row)
        except OSMProviderStop:
            if tile_results is not None:
                tile_results.append(False)
            raise
        except RuntimeError:
            if tile_results is not None:
                tile_results.append(False)
            pass
    if successes == 0:
        raise RuntimeError("All direct OSM API reads failed; no leads sent")
    # Return only the five categories supported by the owner-only scanner.
    # Prevent full raw-map objects and irrelevant personal metadata entering state.
    return [
        {"type": row.get("type"), "id": row.get("id"),
         "tags": {key: value for key, value in (row.get("tags") or {}).items()
                  if key in ("name", "shop", "amenity", "website", "contact:website",
                             "contact:phone", "phone", "email", "contact:email", "addr:street",
                             "addr:housenumber", "addr:district")}}
        for row in found.values()
        if isinstance(row.get("tags"), dict)
        and str(row["tags"].get("name") or "").strip()
        and (row["tags"].get("shop") in SUPPORTED_SHOPS
             or row["tags"].get("amenity") == "car_wash")
    ]
