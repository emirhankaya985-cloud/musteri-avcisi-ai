"""No-network 402-tile mirror tests; no real database writes."""
import json
import tempfile
import unittest
from pathlib import Path

from leadhunter.tile_neon_sync import region_rows


class TileNeonSnapshotTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "ledger.json"

    def write(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")

    def test_all_402_tiles_exist_when_no_scan_has_run(self):
        rows = region_rows(self.path)
        self.assertEqual(len(rows), 402)
        self.assertEqual(len(set((r[0],r[1]) for r in rows)),402)
        self.assertTrue(all(r[2]=="pending" for r in rows))

    def test_progress_and_failure_are_independent_per_region(self):
        self.write({"version":1,"regions":{
            "pilot_1_of_8":{"next":2,"total":48,"cycle":0,"stalls":1},
            "pilot_2_of_8":{"next":3,"total":48,"cycle":0,"stalls":0}
        }})
        rows=region_rows(self.path)
        self.assertEqual([r[2] for r in rows if r[0]=="pilot_1_of_8"][:4],
                         ["confirmed","confirmed","retry","pending"])
        self.assertEqual([r[2] for r in rows if r[0]=="pilot_2_of_8"][:4],
                         ["confirmed","confirmed","confirmed","pending"])
        self.assertEqual(next(r[3] for r in rows if r[:2]==("pilot_1_of_8",2)),
                         "unverified_source_failure")

    def test_provider_refusal_is_blocked_not_bypassed(self):
        self.write({"version":1,"regions":{
            "pilot_1_of_8":{"next":1,"total":48,"cycle":0,"stalls":1,
                            "last_error":"provider_refusal"}
        }})
        rows=region_rows(self.path)
        self.assertEqual(rows[1][2:],
                         ("blocked","provider_refusal"))

    def test_wrong_geometry_fails_closed(self):
        self.write({"version":1,"regions":{
            "pilot_1_of_8":{"next":1,"total":30,"cycle":0,"stalls":1}
        }})
        with self.assertRaises(RuntimeError):
            region_rows(self.path)


if __name__=="__main__":
    unittest.main()
