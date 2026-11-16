"""One-time, narrow public OSM node-coordinate evidence for CRM duplicate pairs.

This is a SINGLE standard OSM API read of <=50 explicitly known OSM node IDs.
Not for scheduled harvesting or historical 402-tile rescans. 403/429 and
network failures stop without bypass, retries or changing CRM decisions.
Only private distance evidence is stored; no contact data or alerts.
"""
import json
import math
import os
import re
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from .review_private import connect_private_database

MAX_NODES=50
MAX_BYTES=250000
RUN_ID=re.compile(r"[0-9]{6,24}\Z")
OSM_NODE=re.compile(r"node/([0-9]{1,20})\Z")


def haversine_m(a,b):
    lat1,lon1=map(math.radians,a)
    lat2,lon2=map(math.radians,b)
    dlat=lat2-lat1
    dlon=lon2-lon1
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return round(6371008.8*2*math.asin(min(1,math.sqrt(h))),2)


def band(distance):
    if distance is None: return "unverified"
    if distance<=30: return "co_located"
    if distance<=500: return "nearby"
    return "separated"


def fetch_locations(ids,opener=urlopen):
    if not ids or len(ids)>MAX_NODES or len(ids)!=len(set(ids)):
        raise ValueError("OSM coordinate audit must have 1-50 unique known node IDs")
    if any(not OSM_NODE.fullmatch(v) for v in ids):
        raise ValueError("Only original OSM node IDs permitted")
    number_ids=sorted(x.split("/")[1] for x in ids)
    # One small explicit request, not a region download or retry/failover.
    url="https://api.openstreetmap.org/api/0.6/nodes?nodes="+quote(",".join(number_ids),safe=",")
    request=Request(url,headers={
        "Accept":"application/xml",
        "User-Agent":"MusteriAvcisiAI/1.0 (one-time owner review of 25 OSM nodes)"},
        method="GET")
    try:
        with opener(request,timeout=25) as response:
            payload=response.read(MAX_BYTES+1)
    except Exception:
        raise RuntimeError("One-time OSM coordinate source unavailable; no bypass, no source changes") from None
    if len(payload)>MAX_BYTES or not payload.startswith(b"<?xml"):
        raise RuntimeError("OSM coordinate response invalid or oversized")
    try:
        root=ElementTree.fromstring(payload)
    except (ValueError,ElementTree.ParseError):
        raise RuntimeError("OSM coordinate source XML invalid") from None
    if root.tag!="osm":
        raise RuntimeError("OSM coordinate source missing expected root")
    observed={}
    allowed=set(ids)
    for element in root.findall("node"):
        name="node/"+str(element.get("id",""))
        if name not in allowed:
            raise RuntimeError("OSM node response contains unrequested identity")
        try:
            lat=float(element.attrib["lat"]);lon=float(element.attrib["lon"])
        except (ValueError,KeyError,TypeError):
            raise RuntimeError("OSM node has invalid geographic coordinates") from None
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180:
            raise RuntimeError("OSM node location out of bounds")
        if name in observed:
            raise RuntimeError("Duplicate OSM node in source response")
        observed[name]=(lat,lon)
    if not observed:
        raise RuntimeError("OSM API returned no verified requested node positions")
    return observed


def run(env=None,db=None,opener=urlopen,output=print):
    env=os.environ if env is None else env
    run_id=str(env.get("GITHUB_RUN_ID",""))
    if not RUN_ID.fullmatch(run_id):
        raise RuntimeError("Real GitHub run id required")
    if env.get("AUTO_MAIL_ENABLED")!="false" or env.get("OWNER_NEW_LEAD_NOTICES")!="false":
        raise RuntimeError("No-contact safety lock required for location review")
    owned=db is None
    conn=connect_private_database(env.get("REVIEW_DATABASE_URL")) if owned else db
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT lead_a,lead_b FROM owner_duplicate_review_pairs ORDER BY lead_a,lead_b")
            pairs=cur.fetchall()
        if not pairs or len(pairs)>100:
            raise RuntimeError("Unexpected private candidate pairs; stop one-time review")
        ids=sorted({id for pair in pairs for id in pair})
        coords=fetch_locations(ids,opener=opener)
        count={label:0 for label in ("co_located","nearby","separated","unverified")}
        with conn.transaction():
            with conn.cursor() as cur:
                for left,right in pairs:
                    distance=(haversine_m(coords[left],coords[right])
                              if left in coords and right in coords else None)
                    label=band(distance)
                    count[label]+=1
                    cur.execute(
                        "INSERT INTO owner_duplicate_geo_evidence "
                        "(lead_a,lead_b,distance_m,location_band,github_run_id) "
                        "VALUES (%s,%s,%s,%s,%s) "
                        "ON CONFLICT(lead_a,lead_b) DO NOTHING",
                        (left,right,distance,label,run_id))
        output("OSM_DUPLICATE_GEO: source=single_25_node_api_request; pairs="+str(len(pairs))+
               "; positions_verified="+str(len(coords))+
               "; co_located="+str(count["co_located"])+
               "; nearby="+str(count["nearby"])+
               "; separated="+str(count["separated"])+
               "; unverified="+str(count["unverified"])+
               "; CRM_rows_changed=0; customer_mail_sent=0")
        return count
    finally:
        if owned:
            conn.close()


if __name__=="__main__":
    run()
