"""Offline incremental-source acceptance; no provider, Telegram or SMTP calls."""
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from leadhunter.incremental_discovery import (
    AREAS, changed_fields, due, ingest, within_pilot)
from leadhunter.snapshot_coverage import overlaps


class FakeConn:
    def __init__(self,initial):
        self.latest=initial
        self.rows={
            "node/7":{"id":"node/7","name":"Old Salon",
                      "category":"Kuaför/berber","website":"",
                      "phone":"","email":"","address":""},
            "website/8":{"id":"website/8","name":"Protected Sent",
                      "category":"Çiçekçi","website":"",
                      "phone":"","email":"","address":""}
        }
        self.reviews={}
        self.run_receipts=[]
        self.reply=None
    @contextmanager
    def transaction(self):
        yield self
    @contextmanager
    def cursor(self):
        yield self
    def execute(self,sql,args=None):
        if sql.startswith("SELECT to_regclass"):
            self.reply=(None,)
        elif sql.startswith("SELECT pg_advisory"):
            self.reply=[]
        elif sql.startswith("SELECT osm_id,lead_data"):
            self.reply=[(k,self.rows[k]) for k in args[0] if k in self.rows]
        elif sql.startswith("INSERT INTO owner_leads"):
            identity,obj=args
            import json
            if identity not in self.rows:
                self.rows[identity]=json.loads(obj)
                self.reply=(identity,)
            else:
                self.reply=None
        elif sql.startswith("INSERT INTO owner_osm_incremental_changes"):
            identity,digest,timestamp,fields,proposed=args
            self.reviews[identity]=tuple(fields)
            self.reply=None
        elif sql.startswith("INSERT INTO owner_osm_incremental_runs"):
            self.run_receipts.append(args)
            self.latest=args[1]
            self.reply=None
        else:
            raise AssertionError("Unexpected SQL query type")
    def fetchall(self): return self.reply
    def fetchone(self): return self.reply


def sample(lead_id,name,location,website=""):
    return ({"id":lead_id,"name":name,"category":"Kuaför/berber",
             "website":website,"phone":"","email":"",
             "address":"","score":50},
            (location[0],location[1],location[0],location[1]))


class IncrementalDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.older=datetime(2026,11,15,21,22,28,tzinfo=timezone.utc)
        self.newer=self.older+timedelta(days=3,hours=2)

    def test_freshness_preflight_respects_minimum_source_interval(self):
        db=FakeConn(self.older)
        with patch("leadhunter.incremental_discovery.source_latest",
                   side_effect=lambda x:x.latest):
            self.assertFalse(due(db,now=self.older+timedelta(days=1)))
            self.assertTrue(due(db,now=self.newer))
            with self.assertRaisesRegex(RuntimeError,"future-dated"):
                due(db,now=self.older-timedelta(minutes=1))

    def test_only_new_osm_ids_added_and_changed_existing_not_overwritten(self):
        db=FakeConn(self.older)
        loc=(40.984,29.017)
        data={
            "node/7":sample("node/7","Renamed Salon",loc),
            "way/9":sample("way/9","Fresh Salon",loc),
            "node/10":sample("node/10","Outside Pilot",(0.0,0.0)),
        }
        with patch("leadhunter.incremental_discovery.source_latest",
                   side_effect=lambda x:x.latest):
            first=ingest(db,data,"a"*64,self.newer,"43858691000",output=lambda _:None)
            self.assertEqual(first,(1,1,True))
            self.assertEqual(len(db.run_receipts),1)
            self.assertEqual(db.rows["node/7"]["name"],"Old Salon")
            self.assertIn("name",db.reviews["node/7"])
            self.assertIn("way/9",db.rows)
            self.assertNotIn("node/10",db.rows)
            # Same source version is idempotent, no duplicate row.
            self.assertEqual(ingest(db,data,"a"*64,self.newer,
                                    "43858691000",output=lambda _:None),
                             (0,0,False))
            self.assertEqual(len(db.run_receipts),1)
            self.assertEqual(len(db.rows),3)

    def test_same_name_different_osm_ids_are_never_merged(self):
        p=(40.984,29.017)
        values={"node/1":sample("node/1","Same Brand",p),
                "way/2":sample("way/2","Same Brand",p)}
        db=FakeConn(self.older)
        with patch("leadhunter.incremental_discovery.source_latest",
                   side_effect=lambda x:x.latest):
            out=ingest(db,values,"b"*64,self.newer,"43858691000",
                       output=lambda _:None)
        self.assertEqual(out,(2,0,True))
        self.assertIn("node/1",db.rows)
        self.assertIn("way/2",db.rows)

    def test_location_filter_never_attempts_full_402_tile_rescan(self):
        p=(40.984,29.017)
        a={"node/1":sample("node/1","Inside",p),
           "node/2":sample("node/2","Outside",(39.1,36.1))}
        self.assertEqual(set(within_pilot(a)),{"node/1"})
        self.assertTrue(any(overlaps(a["node/1"][1],bbox) for bbox in AREAS))
        self.assertFalse(any(overlaps(a["node/2"][1],bbox) for bbox in AREAS))
        self.assertEqual(changed_fields(
            {"name":"Demo","category":"Çiçekçi"},
            {"name":"Demo","category":"Çiçekçi"}),())


if __name__=="__main__":
    unittest.main()
