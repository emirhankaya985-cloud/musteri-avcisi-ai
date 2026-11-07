"""Bounded public Overpass read-only tile research for production coverage.

Never use OSM's *editing* API for scheduled data extraction. Use a single
listed Overpass instance per run (no 429/403 mirror hopping), at most two
small 0.005-degree queries, and a durable success-only public cursor.
Data: © OpenStreetMap contributors, ODbL.
"""
import json
import socket
import ssl
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from .osm_direct import (_tiles, MAX_RESPONSE_BYTES, MAX_TILES,
                         OSMProviderStop)

# Public global-data instance listed by the OpenStreetMap Overpass API wiki.
# Switch away from the provider repeatedly timing out in production.
# Queue delay observed near 23s in GitHub runner; 55s is the bounded client deadline.
# One fixed host per visit, no parallel requests and no rate-limit evasions.
READONLY_OVERPASS = "https://maps.mail.ru/osm/tools/overpass/api/interpreter"


class OverpassTransient(RuntimeError):
    """Redacted, classifiable temporary read-only provider error."""

    def __init__(self, reason):
        if reason not in ("timeout", "dns", "tls", "connection",
                          "network", "http_5xx", "http_other",
                          "response_oversize", "response_invalid",
                          "provider_remark"):
            raise ValueError("Unknown safe Overpass failure class")
        super().__init__("Read-only Overpass temporarily unavailable")
        self.reason = reason


def _network_reason(error):
    value = getattr(error, "reason", error)
    if isinstance(value, TimeoutError):
        return "timeout"
    if isinstance(value, socket.gaierror):
        return "dns"
    if isinstance(value, ssl.SSLError):
        return "tls"
    if isinstance(value, (ConnectionError, ConnectionRefusedError,
                          ConnectionResetError, BrokenPipeError)):
        return "connection"
    return "network"
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
        "[out:json][timeout:35];("
        f'nwr["amenity"="car_wash"]({values});'
        f'nwr["shop"="hairdresser"]({values});'
        f'nwr["shop"="beauty"]({values});'
        f'nwr["shop"="florist"]({values});'
        f'nwr["shop"="optician"]({values});'
        ");out tags qt;"
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
        with opener(req, timeout=55) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (400, 401, 403, 406, 429):
            stopped = OSMProviderStop(
                "Public read-only Overpass refused request (HTTP " +
                str(exc.code) + "); no bypass")
            stopped.http_status = exc.code
            raise stopped from None
        reason = "http_5xx" if 500 <= exc.code <= 599 else "http_other"
        raise OverpassTransient(reason) from None
    except (URLError, TimeoutError, OSError) as exc:
        raise OverpassTransient(_network_reason(exc)) from None

    if len(payload) > MAX_RESPONSE_BYTES:
        raise OverpassTransient("response_oversize")
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError, UnicodeError):
        raise OverpassTransient("response_invalid") from None
    if not isinstance(parsed, dict):
        raise OverpassTransient("response_invalid")
    if parsed.get("remark"):
        # A public provider can return an error in a 200 JSON response.
        # Never print or persist its untrusted error string or mark a tile done.
        raise OverpassTransient("provider_remark")
    if not isinstance(parsed.get("elements"), list):
        raise OverpassTransient("response_invalid")
    return parsed["elements"]

def get_overpass_tiles(bbox, opener=urlopen, *, day=None, hour=None,
                       rotation_period=1, max_tiles=MAX_TILES,
                       tile_start=None, tile_results=None,
                       on_diagnostic=None):
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
    for offset, (west, south, east, north) in enumerate(_tiles(
            bbox, day, max_tiles, hour=hour, rotation_period=rotation_period,
            start_index=tile_start)):
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
        except OSMProviderStop as exc:
            if tile_results is not None:
                tile_results.append(False)
            if on_diagnostic is not None:
                on_diagnostic("OVERPASS_TILE_FAILURE: class=provider_refusal; http_status=" +
                              str(exc.http_status) + "; tile_offset=" + str(offset))
            raise
        except OverpassTransient as exc:
            if tile_results is not None:
                tile_results.append(False)
            if on_diagnostic is not None:
                # Only an enum and relative tile offset; never raw response,
                # URL parameters, company data, exception body or credentials.
                on_diagnostic("OVERPASS_TILE_FAILURE: class=" + exc.reason +
                              "; tile_offset=" + str(offset))
            # Next normal hourly region visit retries this exact tile.
            break
    if not successful:
        raise RuntimeError("No confirmed read-only Overpass tile; cursor unchanged")
    return list(found.values())
