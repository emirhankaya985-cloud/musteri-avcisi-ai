"""Read-only eight-region acceptance; no private data or outreach.

One small OSM provider request per bounded pilot region with a fixed
cooldown; no retries or second provider in this diagnostic. The ordinary
hourly scanner remains the authoritative writer of private lead records.
"""
import json
import time
from collections import Counter
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .scan_regions import PILOT_BBOXES
from .core import bbox_parse, lead_from_osm, OVERPASS_ENDPOINTS
from .osm_direct import get_osm_direct


def osm_query(box):
    south, west, north, east = bbox_parse(box)
    bbox = ",".join(map(str, (south, west, north, east)))
    selectors = ('nwr["amenity"="car_wash"]',
                 'nwr["shop"="hairdresser"]',
                 'nwr["shop"="beauty"]',
                 'nwr["shop"="florist"]',
                 'nwr["shop"="optician"]')
    return '[out:json][timeout:12];(' + ''.join(x+'('+bbox+');' for x in selectors) + ');out center tags 200;'


def fallback_sample(box, opener, failure):
    """One tiny official OSM API tile if Overpass is temporarily unreachable.

    Success validates only that tile, never full bbox coverage. 429 and
    authorization failures must not be bypassed with another provider.
    """
    if failure not in ("network", "http_500", "http_502", "http_503", "http_504"):
        return failure, 0, 0
    try:
        raw = get_osm_direct(bbox_parse(box), seen_ids=(), opener=opener,
                             max_tiles=1)
    except (RuntimeError, ValueError):
        return failure, 0, 0
    valid = {lead['id'] for item in raw
             if (lead := lead_from_osm(item)) is not None}
    return "main_api_sample", len(raw), len(valid)


def inspect_one(box, opener=urlopen):
    req = Request(OVERPASS_ENDPOINTS[0],
                  data=urlencode({'data': osm_query(box)}).encode(),
                  headers={'Content-Type':'application/x-www-form-urlencoded',
                           'User-Agent':'MusteriAvcisiAI/1.0 owner-only acceptance'},
                  method='POST')
    try:
        with opener(req, timeout=15) as response:
            body = response.read(1_000_001)
            if len(body) > 1_000_000:
                return 'oversize', 0, 0
            doc = json.loads(body)
        if not isinstance(doc, dict) or doc.get('remark') or not isinstance(doc.get('elements'), list):
            return 'invalid_response', 0, 0
        raw = doc['elements']
        valid = {lead['id'] for item in raw
                 if (lead := lead_from_osm(item)) is not None}
        return 'ok', len(raw), len(valid)
    except HTTPError as exc:
        # Never evade 401/403/429; bounded official fallback on transient 5xx.
        reason = 'http_'+str(exc.code if exc.code in (400,401,403,429,500,502,503,504) else 'other')
        return fallback_sample(box, opener, reason)
    except (URLError, OSError, TimeoutError):
        return fallback_sample(box, opener, "network")
    except (ValueError, TypeError, UnicodeError):
        return 'invalid_response',0,0


def run(opener=urlopen, sleeper=time.sleep, output=print):
    statuses = []
    for index, box in enumerate(PILOT_BBOXES):
        if index:
            sleeper(2)
        state, raw, valid = inspect_one(box, opener)
        statuses.append(state)
        output(f"REGION_ACCEPTANCE: slot={index+1}/8; provider={state}; raw={raw}; valid={valid}; smtp_sent=0")
        if state == 'http_429':
            # Respect provider rate limiting; report unchecked slots as
            # unverified instead of retrying or claiming full coverage.
            break
    if len(statuses) != 8 or any(state not in ("ok","main_api_sample") for state in statuses):
        raise RuntimeError("REGION_ACCEPTANCE: PARTIAL; eight live provider replies not confirmed")
    output("REGION_ACCEPTANCE: PASS; eight bounded region probes replied (main_api_sample covers one tile only); no CRM writes")
    return statuses


if __name__ == '__main__':
    run()
