"""Durable eight-region OSM tile progress; synthetic and no network."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

from leadhunter.tile_progress import plan, commit, aggregate
from leadhunter.osm_direct import get_osm_direct
from leadhunter.scan_regions import PILOT_BBOXES
from leadhunter.core import bbox_parse


class TileProgressTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "tiles.json"
        self.slot = "pilot_1_of_8"
        self.box = bbox_parse(PILOT_BBOXES[0])

    def test_success_only_advancement_and_persistent_resume(self):
        first = plan(self.path,self.slot,self.box)
        self.assertEqual(first["start"],0)
        self.assertEqual(first["maximum"],2)
        self.assertEqual(commit(self.path,self.slot,self.box,0,0)["completed"],0)
        self.assertFalse(self.path.exists())
        next_ = commit(self.path,self.slot,self.box,0,1)
        self.assertEqual(next_["completed"],1)
        resumed = plan(self.path,self.slot,self.box)
        self.assertEqual(resumed["start"],1)
        self.assertEqual(commit(self.path,self.slot,self.box,1,2)["completed"],3)
        raw = self.path.read_text()
        self.assertNotIn("@",raw)
        self.assertNotIn("website",raw)
        self.assertEqual(json.loads(raw)["version"],1)

    def test_independent_regions_and_aggregate_no_false_prior_claim(self):
        total = aggregate(self.path)
        self.assertEqual(total[0],0)
        self.assertGreater(total[1],100)
        commit(self.path,self.slot,self.box,0,2)
        self.assertEqual(aggregate(self.path)[0],2)
        other = plan(self.path,"pilot_2_of_8",bbox_parse(PILOT_BBOXES[1]))
        self.assertEqual(other["start"],0)
        self.assertEqual(other["completed"],0)

    def test_corrupt_and_conflicting_state_fail_closed(self):
        self.path.write_text("not valid",encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError,"Corrupt public tile ledger"):
            plan(self.path,self.slot,self.box)
        self.path.unlink()
        commit(self.path,self.slot,self.box,0,2)
        with self.assertRaisesRegex(RuntimeError,"cursor changed"):
            commit(self.path,self.slot,self.box,0,1)
        with self.assertRaises(ValueError):
            commit(self.path,self.slot,self.box,2,3)

    def test_full_cycle_then_next_cycle_only_on_next_success(self):
        first=plan(self.path,self.slot,self.box)
        total=first["total"]
        while plan(self.path,self.slot,self.box)["completed"] < total:
            item=plan(self.path,self.slot,self.box)
            commit(self.path,self.slot,self.box,item["start"],item["maximum"])
        final=plan(self.path,self.slot,self.box)
        self.assertEqual(final["completed"],total)
        self.assertEqual(final["start"],0)
        self.assertEqual(final["cycle"],1)
        new=commit(self.path,self.slot,self.box,0,1)
        self.assertEqual(new["completed"],1)
        self.assertEqual(new["cycle"],1)

    def test_official_api_failed_second_tile_not_advanced(self):
        calls=[]
        results=[]
        def fake(req,timeout=None):
            if "/map.json" in req.full_url:
                calls.append(req.full_url)
                if len(calls)==2:
                    raise URLError("synthetic unavailable")
            return io.BytesIO(b'{"elements":[]}')
        raw=get_osm_direct(self.box,(),fake,max_tiles=2,
                           tile_start=0,tile_results=results)
        self.assertEqual(raw,[])
        self.assertEqual(results,[True,False])
        self.assertEqual(len(set(calls)),2)
        commit(self.path,self.slot,self.box,0,1)
        self.assertEqual(plan(self.path,self.slot,self.box)["start"],1)

    def test_does_not_advance_when_all_tiles_fail(self):
        results=[]
        with self.assertRaisesRegex(RuntimeError,"All direct OSM API reads failed"):
            get_osm_direct(self.box,(),lambda req,timeout=None: (_ for _ in ()).throw(
                URLError("down")),tile_start=0,tile_results=results)
        self.assertEqual(results,[False,False])
        self.assertEqual(commit(self.path,self.slot,self.box,0,0)["completed"],0)


if __name__ == "__main__":
    unittest.main()
