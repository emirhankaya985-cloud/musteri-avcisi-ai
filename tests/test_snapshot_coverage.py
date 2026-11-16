"""No-network regressions for checksum-verified full 402-cell OSM snapshot."""
import io
import json
import tempfile
import unittest
from contextlib import contextmanager
from datetime import date,datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch

from leadhunter.core import bbox_parse
from leadhunter.osm_direct import _tiles
from leadhunter.scan_regions import PILOT_BBOXES
from leadhunter.snapshot_coverage import (
    tile_bbox, overlaps, bounds_of, snapshot_timestamp,
    matching_cells, safe_metadata, run
)
from leadhunter.tile_progress import tile_total, _load


class PbfSnapshotCoverageTests(unittest.TestCase):
    def test_all_402_cells_exactly_match_existing_public_ledger_geometry(self):
        total=0
        for region in PILOT_BBOXES:
            area=bbox_parse(region)
            count=tile_total(area)
            total+=count
            self.assertIn(count,(48,54))
            for i in range(count):
                west,south,east,north=next(_tiles(
                    area,date(2026,11,16),maximum=1,start_index=i))
                self.assertEqual(tile_bbox(area,i),(south,west,north,east))
        self.assertEqual(total,402)

    def test_no_silent_five_business_cap_or_leaked_unrelated_geometry(self):
        cell=(40.982,29.015,40.987,29.020)
        features={
          "node/"+str(i):({"id":"node/"+str(i),"name":"Test "+str(i)},
                           (40.984,29.017,40.984,29.017))
          for i in range(20)}
        features["node/99"]=({"id":"node/99","name":"far"},
                              (40.955,29.1,40.955,29.1))
        self.assertEqual(len(matching_cells(features,cell)),20)
        self.assertFalse(overlaps((40.955,29.1,40.955,29.1),cell))
        self.assertTrue(overlaps((40.982,29.015,40.982,29.015),cell))

    def test_trusted_source_timestamp_requires_recent_real_pbf_date(self):
        now=datetime(2026,11,16,12,tzinfo=timezone.utc)
        self.assertEqual(snapshot_timestamp("2026-11-15T21:00:00Z",now).year,2026)
        for wrong in ("not-dated","", "2026-11-17T00:00:00Z",
                      "2026-10-01T00:00:00Z","2026-11-15"):
            with self.subTest(wrong=wrong),self.assertRaises(RuntimeError):
                snapshot_timestamp(wrong,now)

    def test_verified_digest_and_mail_locks_required(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"pilot.pbf"
            p.write_bytes(b'0'*4097)
            env={"GITHUB_RUN_ID":"43817606409",
                 "OSM_PILOT_FILE":str(p),"OSM_SNAPSHOT_SHA256":"a"*64,
                 "OSM_SNAPSHOT_TIMESTAMP":"2026-11-15T10:00:00Z",
                 "AUTO_MAIL_ENABLED":"false",
                 "OWNER_APPROVED_MAIL_ENABLED":"false",
                 "OWNER_NEW_LEAD_NOTICES":"false"}
            with patch("leadhunter.snapshot_coverage.snapshot_timestamp",
                       return_value=datetime.now(timezone.utc)):
                self.assertEqual(safe_metadata(env)[0],"43817606409")
                for key in ("AUTO_MAIL_ENABLED","OWNER_APPROVED_MAIL_ENABLED",
                            "OWNER_NEW_LEAD_NOTICES"):
                    copy=dict(env);copy[key]="true"
                    with self.assertRaises(RuntimeError):
                        safe_metadata(copy)
                bad=dict(env);bad["OSM_SNAPSHOT_SHA256"]="x"*64
                with self.assertRaises(RuntimeError):
                    safe_metadata(bad)

    def test_complete_tile_progress_after_private_durable_commit(self):
        class Cursor:
            def __init__(self,fail=False):
                self.answer=None
                self.fail=fail
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self,sql,args):
                if self.fail and sql.startswith("INSERT INTO owner_leads"):
                    raise RuntimeError("synthetic private DB failure")
                self.answer = (args[0],) if sql.startswith("INSERT INTO owner_leads") else (
                    (args[1],) if sql.startswith("UPDATE owner_osm_tile_ledger") else None)
            def fetchone(self):
                return self.answer
        class DB:
            def __init__(self,fail=False):
                self.cur=Cursor(fail)
            @contextmanager
            def transaction(self):
                yield self
            def cursor(self):return self.cur
            def close(self): pass
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"tiles.json"
            regions={}
            for i,area in enumerate(PILOT_BBOXES,1):
                total=tile_total(bbox_parse(area))
                regions[f"pilot_{i}_of_8"]={
                    "next":total-(1 if i==8 else 0),"total":total,
                    "cycle":0,"stalls":0}
            path.write_text(json.dumps({"version":1,"regions":regions}))
            lead={"id":"node/33","name":"Real-shaped synthetic flower",
                  "category":"Çiçekçi","website":"","phone":"","address":"",
                  "email":"","score":75}
            features={lead["id"]:(lead,(40.99,29.15,40.99,29.15))}
            # The last tile in area 8 might not overlap our point.
            # Supply a matching geometry for that exact final cell.
            last=tile_bbox(bbox_parse(PILOT_BBOXES[-1]),47)
            features={lead["id"]:(lead,(
                (last[0]+last[2])/2,(last[1]+last[3])/2,
                (last[0]+last[2])/2,(last[1]+last[3])/2))}
            env={"TILE_PROGRESS_FILE":str(path),"REVIEW_DATABASE_URL":"synthetic"}
            meta=("43817606409","a"*64,
                  datetime.now(timezone.utc),Path(td)/"pilot.pbf")
            with patch("leadhunter.snapshot_coverage.safe_metadata",return_value=meta),patch(
                 "leadhunter.snapshot_coverage.parse_pilot",
                 return_value=(features,{"node":1,"way":1,"relation":0})):
                with self.assertRaisesRegex(RuntimeError,"synthetic private DB"):
                    run(env=env,conn=DB(fail=True),output=lambda _:None)
                self.assertEqual(_load(path)["regions"]["pilot_8_of_8"]["next"],47)
                result=run(env=env,conn=DB(),output=lambda _:None)
                self.assertEqual(result,(1,1))
                self.assertEqual(_load(path)["regions"]["pilot_8_of_8"]["next"],48)
                self.assertEqual(run(env=env,conn=DB(),output=lambda _:None),(0,0))


if __name__=="__main__":
    unittest.main()
