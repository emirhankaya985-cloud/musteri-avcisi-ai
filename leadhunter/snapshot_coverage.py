"""One-time, verifiable OSM PBF snapshot coverage; no public Overpass traffic.

The independent public Geofabrik country extract is checked for digest and
timestamp before this module runs. Its Istanbul-pilot subextract is complete
for ways and multipolygon relations. All 402 existing 0.005-degree cells are
inspected against the same real OSM snapshot; no invented empty-success cells.

Keep provenance in private Neon. Never email/Telegram businesses, alter old
CRM decisions, or label this historical snapshot as live Overpass freshness.
Data attribution: © OpenStreetMap contributors, ODbL.
"""
import hashlib
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .core import bbox_parse, lead_from_osm
from .osm_direct import TILE_DEGREES
from .scan_regions import PILOT_BBOXES
from .tile_progress import _load, commit as commit_tile, tile_total
from .review_private import connect_private_database

PBF_SOURCE_URL = "https://download.geofabrik.de/europe/turkey-latest.osm.pbf"
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
RUN_ID = re.compile(r"[0-9]{6,24}\Z")
ALLOWED_TAGS = frozenset((
    "name", "shop", "amenity", "website", "contact:website",
    "contact:phone", "phone", "email", "contact:email",
    "addr:street", "addr:housenumber", "addr:district"))


def tile_bbox(area, index):
    """Faithfully reconstruct the same row-major geometry as osm_direct._tiles."""
    south, west, north, east = area
    rows = math.ceil((north-south)/TILE_DEGREES)
    cols = math.ceil((east-west)/TILE_DEGREES)
    if type(index) is not int or index < 0 or index >= rows*cols:
        raise ValueError("OSM tile index outside verified geometry")
    row, col = divmod(index,cols)
    s = south + row*TILE_DEGREES
    w = west + col*TILE_DEGREES
    return (round(s,6),round(w,6),
            round(min(north,s+TILE_DEGREES),6),
            round(min(east,w+TILE_DEGREES),6))


def overlaps(a,b):
    """Conservative intersection: never omit a potentially intersecting way."""
    if len(a)!=4 or len(b)!=4:
        raise ValueError("Bounding boxes require four numeric coordinates")
    return (a[0]<=b[2] and a[2]>=b[0] and
            a[1]<=b[3] and a[3]>=b[1])


def bounds_of(coords):
    if not coords:
        raise RuntimeError("Relevant OSM geometry could not be validated")
    lats=[x[0] for x in coords]
    lons=[x[1] for x in coords]
    bounds=(min(lats),min(lons),max(lats),max(lons))
    if not all(math.isfinite(x) for x in bounds):
        raise RuntimeError("Invalid OSM geometry")
    return bounds


def snapshot_timestamp(value,now=None):
    try:
        time=datetime.fromisoformat(str(value).strip().replace("Z","+00:00"))
    except (ValueError,TypeError):
        raise RuntimeError("OSM snapshot has no trusted source timestamp") from None
    now=datetime.now(timezone.utc) if now is None else now
    if time.tzinfo is None or now.tzinfo is None:
        raise RuntimeError("OSM source timestamp must include timezone")
    age=(now.astimezone(timezone.utc)-time.astimezone(timezone.utc)).total_seconds()
    if not 0<=age<=7*24*3600:
        raise RuntimeError("OSM snapshot too old or future-dated; fail closed")
    return time.astimezone(timezone.utc)


def matching_cells(features,cell):
    """Test real snapshot features independently for each 0.005-degree cell."""
    return [(lead,geometry) for lead,geometry in features.values()
            if overlaps(geometry,cell)]


def parse_pilot(pbf):
    """Parse only the already clipped, relation-complete pilot PBF.

    Pyosmium is loaded lazily, so ordinary offline CI needs no PBF dependency.
    Relevant node/way/relation features are retained with conservative geometry;
    every encountered potentially relevant object must be resolvable.
    """
    import osmium
    features={}
    class Pilot(osmium.SimpleHandler):
        def __init__(self):
            super().__init__()
            self.nodes={}
            self.ways={}
            self.seen={"node":0,"way":0,"relation":0}
        def _lead(self,typ,obj,geometry,tags):
            if not tags.get("name"):
                return
            row={"type":typ,"id":int(obj.id),"tags":{
                k:v for k,v in tags.items() if k in ALLOWED_TAGS}}
            lead=lead_from_osm(row)
            if lead is not None:
                if geometry is None:
                    raise RuntimeError("Relevant OSM feature has incomplete geometry")
                features[lead["id"]]=(lead,geometry)
        def node(self,n):
            self.seen["node"]+=1
            try:
                if not n.location.valid():
                    raise ValueError("missing location")
                xy=(float(n.location.lat),float(n.location.lon))
            except (ValueError,AttributeError):
                tags=dict(n.tags)
                if lead_from_osm({"type":"node","id":int(n.id),"tags":tags}):
                    raise RuntimeError("Relevant node has no verified location") from None
                return
            self.nodes[int(n.id)]=xy
            tags=dict(n.tags)
            self._lead("node",n,(xy[0],xy[1],xy[0],xy[1]),tags)
        def way(self,w):
            self.seen["way"]+=1
            tags=dict(w.tags)
            coords=[]
            for member in w.nodes:
                xy=self.nodes.get(int(member.ref))
                if xy is not None:
                    coords.append(xy)
            # complete_ways/smart extraction includes all vertices, but an
            # unresolved relevant way cannot certify any tile as empty.
            if len(coords)!=len(w.nodes):
                if lead_from_osm({"type":"way","id":int(w.id),"tags":tags}):
                    raise RuntimeError("Relevant way is missing source vertices")
                return
            b=bounds_of(coords) if coords else None
            if b is not None:
                self.ways[int(w.id)]=b
            self._lead("way",w,b,tags)
        def relation(self,r):
            self.seen["relation"]+=1
            tags=dict(r.tags)
            if not lead_from_osm({"type":"relation","id":int(r.id),"tags":tags}):
                return
            parts=[]
            for member in r.members:
                kind=str(member.type)
                if kind=="w" and int(member.ref) in self.ways:
                    parts.append(self.ways[int(member.ref)])
                elif kind=="n" and int(member.ref) in self.nodes:
                    lat,lon=self.nodes[int(member.ref)]
                    parts.append((lat,lon,lat,lon))
                elif kind in ("w","n"):
                    raise RuntimeError("Relevant OSM relation incomplete in pilot extract")
            if not parts:
                raise RuntimeError("Relevant OSM relation has no verified spatial members")
            b=(min(x[0] for x in parts),min(x[1] for x in parts),
               max(x[2] for x in parts),max(x[3] for x in parts))
            self._lead("relation",r,b,tags)
    pilot=Pilot()
    pilot.apply_file(str(pbf),locations=False)
    if pilot.seen["node"]<1 or pilot.seen["way"]<1 or not features:
        raise RuntimeError("Real OSM pilot extract empty/incomplete; no tiles confirmed")
    return features,pilot.seen


def safe_metadata(env):
    run=str(env.get("GITHUB_RUN_ID",""))
    digest=str(env.get("OSM_SNAPSHOT_SHA256","")).lower()
    if not RUN_ID.fullmatch(run) or not SHA256.fullmatch(digest):
        raise RuntimeError("Verified run ID and SHA256 digest are required")
    if (env.get("AUTO_MAIL_ENABLED") != "false"
            or env.get("OWNER_APPROVED_MAIL_ENABLED") != "false"
            or env.get("OWNER_NEW_LEAD_NOTICES") != "false"):
        raise RuntimeError("Snapshot research must have mail and notices locked OFF")
    timestamp=snapshot_timestamp(env.get("OSM_SNAPSHOT_TIMESTAMP"))
    file=Path(env.get("OSM_PILOT_FILE",""))
    if not file.is_file() or file.stat().st_size<4096:
        raise RuntimeError("Actual nonempty pilot PBF required")
    return run,digest,timestamp,file


def run(env=None,output=print,conn=None):
    env=os.environ if env is None else env
    run_id,sha256,source_at,pbf=safe_metadata(env)
    ledger=Path(env.get("TILE_PROGRESS_FILE","data/osm_tile_progress.json"))
    features,counts=parse_pilot(pbf)
    if len(features)<1:
        raise RuntimeError("Snapshot did not contain any verifiable OSM businesses")
    owned=conn is None
    db=connect_private_database(env.get("REVIEW_DATABASE_URL")) if owned else conn
    done=inserted=0
    try:
        data=_load(ledger)
        for i,region in enumerate(PILOT_BBOXES,1):
            slot=f"pilot_{i}_of_8"
            bbox=bbox_parse(region)
            total=tile_total(bbox)
            existing=data["regions"].get(slot,{})
            start=existing.get("next",0)
            if existing and existing["total"]!=total:
                raise RuntimeError("Saved OSM geometry mismatch; fail closed")
            if start>=total:
                continue
            for tile in range(start,total):
                cell=tile_bbox(bbox,tile)
                leads=matching_cells(features,cell)
                added=0
                # Only private CRM + provenance are written. Frozen historical
                # sent/declined records are never updated or re-contacted.
                with db.transaction():
                    with db.cursor() as cur:
                        for lead,_ in leads:
                            cur.execute(
                                "INSERT INTO owner_leads(osm_id,lead_data,status) "
                                "VALUES (%s,%s::jsonb,'review') "
                                "ON CONFLICT(osm_id) DO NOTHING RETURNING osm_id",
                                (lead["id"],json.dumps(lead,ensure_ascii=False)))
                            added+=int(cur.fetchone() is not None)
                        cur.execute(
                            "INSERT INTO owner_osm_tile_snapshot_provenance"
                            "(region,tile_index,snapshot_sha256,source_data_at,"
                            "candidate_count,inserted_count,run_id,verified_at)"
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,now()) "
                            "ON CONFLICT (region,tile_index) DO NOTHING",
                            (slot,tile,sha256,source_at,len(leads),added,run_id))
                        cur.execute(
                            "UPDATE owner_osm_tile_ledger SET state='confirmed',"
                            "reason=NULL,last_observed_run_id=%s,updated_at=now() "
                            "WHERE region=%s AND tile_index=%s RETURNING region",
                            (run_id,slot,tile))
                        if cur.fetchone() is None:
                            raise RuntimeError("Private source tile row missing")
                # Make the source GitHub cursor catch up only after CRM write.
                commit_tile(ledger,slot,bbox,tile,1,attempted=1)
                done+=1
                inserted+=added
            output("SNAPSHOT_REGION: slot="+slot+"; verified="+str(total)+
                   "; source_date="+source_at.date().isoformat()+
                   "; business_mail_sent=0")
        output("SNAPSHOT_COVERAGE: confirmed_new="+str(done)+
               "; new_crm="+str(inserted)+
               "; candidate_features="+str(len(features))+
               "; source=Geofabrik_PBF; sha256_verified=1; "
               "historical_snapshot=1; business_mail_sent=0; telegram_sent=0")
        return done,inserted
    finally:
        if owned:
            db.close()


if __name__=="__main__":
    run()
