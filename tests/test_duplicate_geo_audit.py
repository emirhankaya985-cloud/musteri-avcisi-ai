"""No-network regressions for strictly one OSM node geographic comparison."""
import io
import unittest
from contextlib import contextmanager
from leadhunter.duplicate_geo_audit import (
    MAX_NODES,haversine_m,band,fetch_locations,run
)


class FakeDB:
    def __init__(self):
        self.pairs=[("node/1","node/2"),("node/3","node/4")]
        self.writes=[]
    @contextmanager
    def transaction(self):
        yield self
    @contextmanager
    def cursor(self):
        yield self
    def execute(self,query,args=None):
        if query.startswith("INSERT INTO owner_duplicate_geo_evidence"):
            self.writes.append(args)
        elif not query.startswith("SELECT lead_a,lead_b"):
            raise AssertionError("Unexpected SQL mutation or query")
    def fetchall(self):
        return self.pairs


def responder(request,timeout=None):
    if request.full_url.endswith("nodes=1,2,3,4"):
        return io.BytesIO(
          b'<?xml version="1.0" encoding="UTF-8"?>'
          b'<osm version="0.6">'
          b'<node id="1" lat="41.00000" lon="29.00000" />'
          b'<node id="2" lat="41.00010" lon="29.00010" />'
          b'<node id="3" lat="40.90000" lon="29.00000" />'
          b'<node id="4" lat="41.01000" lon="29.12000" />'
          b'</osm>')
    raise AssertionError("Unexpected network request")


class GeoReviewTests(unittest.TestCase):
    def setUp(self):
        self.env={"GITHUB_RUN_ID":"43876920577","AUTO_MAIL_ENABLED":"false",
                  "OWNER_NEW_LEAD_NOTICES":"false"}
    def test_exactly_one_explicit_bounded_node_request_no_bulk_area(self):
        seen=[]
        def one(req,timeout=None):
            seen.append(req.full_url)
            return responder(req,timeout)
        got=fetch_locations(["node/4","node/3","node/2","node/1"],opener=one)
        self.assertEqual(set(got),{"node/1","node/2","node/3","node/4"})
        self.assertEqual(len(seen),1)
        self.assertEqual(seen[0].count("/nodes?nodes="),1)
        self.assertNotIn("interpreter",seen[0])
        with self.assertRaises(ValueError):
            fetch_locations(["node/1"]*(MAX_NODES+1),opener=one)
        with self.assertRaises(ValueError):
            fetch_locations(["way/1"],opener=one)
        self.assertEqual(len(seen),1)

    def test_co_located_and_separate_branches_are_only_evidence_not_merge(self):
        db=FakeDB()
        out=run(env=self.env,db=db,opener=responder,output=lambda _:None)
        self.assertEqual(out,{"co_located":1,"nearby":0,"separated":1,"unverified":0})
        self.assertEqual(len(db.writes),2)
        self.assertEqual(db.writes[0][3],"co_located")
        self.assertEqual(db.writes[1][3],"separated")
        self.assertGreater(db.writes[1][2],500)
        self.assertEqual(band(31),"nearby")
        self.assertEqual(band(None),"unverified")
        self.assertEqual(haversine_m((41,29),(41,29)),0)

    def test_missing_node_does_not_fabricate_coordinates(self):
        def partial(req,timeout=None):
            return io.BytesIO(b'<?xml version="1.0"?><osm version="0.6">'
                  b'<node id="1" lat="41" lon="29"/></osm>')
        db=FakeDB()
        out=run(env=self.env,db=db,opener=partial,output=lambda _:None)
        self.assertEqual(out["unverified"],2)
        self.assertTrue(all(z[2] is None for z in db.writes))

    def test_rate_limit_or_refusal_stops_without_bypass_or_private_changes(self):
        calls=[]
        def denied(req,timeout=None):
            calls.append(req.full_url)
            raise RuntimeError("429 blocked")
        db=FakeDB()
        with self.assertRaisesRegex(RuntimeError,"no bypass"):
            run(env=self.env,db=db,opener=denied,output=lambda _:None)
        self.assertEqual(len(calls),1)
        self.assertEqual(db.writes,[])
    def test_no_outbound_smtp_or_owner_notices(self):
        for field in ("AUTO_MAIL_ENABLED","OWNER_NEW_LEAD_NOTICES"):
            bad=dict(self.env);bad[field]="true"
            with self.assertRaisesRegex(RuntimeError,"No-contact"):
                run(env=bad,db=FakeDB(),opener=lambda *a: self.fail("network used"))


if __name__=="__main__":
    unittest.main()
