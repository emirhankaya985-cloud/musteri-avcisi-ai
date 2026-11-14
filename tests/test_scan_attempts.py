"""No-network source attempt diagnostics and idempotent data contract."""
import json
import tempfile
import unittest
from pathlib import Path
from leadhunter.scan_attempts import begin,note_failure,collect


class ScanAttemptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"observation.json"
        self.ledger=Path(self.tmp.name)/"tiles.json"
        self.env={
            "GITHUB_RUN_ID":"43634315993",
            "SCAN_STEP_OUTCOME":"success",
            "MIRROR_STEP_OUTCOME":"success",
            "SCAN_OBSERVATION_FILE":str(self.path)
        }

    def write_tiles(self,next=1):
        self.ledger.write_text(json.dumps({"version":1,"regions":{
            "pilot_7_of_8":{"cycle":0,"next":next,"total":54,"stalls":1,
                            "last_error":"http_5xx"}}}),encoding="utf-8")

    def test_partial_source_outage_preserves_known_prefix(self):
        self.assertTrue(begin(self.env,"pilot_7_of_8",0,1))
        self.assertTrue(note_failure(self.env,"http_5xx"))
        self.write_tiles(1)
        row=collect(self.env,self.ledger)
        self.assertEqual(row[:8],(
            "43634315993","pilot_7_of_8","partial","http_5xx",
            None,1,0,1))
        self.assertEqual(row[8],"success")
        self.assertNotIn("email",self.path.read_text())
        self.assertNotIn("token",self.path.read_text())

    def test_429_retry_is_visible_with_no_mirror_hop(self):
        self.assertTrue(begin(self.env,"pilot_7_of_8",0,2))
        self.assertTrue(note_failure(self.env,"provider_refusal",429))
        self.write_tiles(1)
        row=collect(self.env,self.ledger)
        self.assertEqual(row[3:6],("provider_refusal",429,2))
        self.assertEqual(row[2],"partial")

    def test_missing_source_capture_does_not_fabricate_success(self):
        self.env["SCAN_STEP_OUTCOME"]="failure"
        row=collect(self.env,self.ledger)
        self.assertEqual(row[1:4],(None,"failure","unverified"))
        self.assertIsNone(row[6])
        self.assertIsNone(row[7])

    def test_preexisting_legacy_result_is_unverified_if_no_marker(self):
        row=collect(self.env,self.ledger)
        self.assertEqual(row[2],"success")
        self.assertEqual(row[3],"unverified")
        self.assertIsNone(row[7])

    def test_invalid_metadata_fails_closed(self):
        self.assertFalse(begin(self.env,"pilot_9_of_8",0,0))
        self.assertFalse(self.path.exists())
        with self.assertRaises(ValueError):
            note_failure(self.env,"secret raw HTTP response")
        self.assertTrue(begin(self.env,"pilot_7_of_8",0,0))
        with self.assertRaises(ValueError):
            note_failure(self.env,"http_5xx",429)
        self.env["SCAN_STEP_OUTCOME"]="unknown"
        with self.assertRaises(RuntimeError):
            collect(self.env,self.ledger)

    def test_observation_id_mismatch_is_not_reused(self):
        self.assertTrue(begin(self.env,"pilot_7_of_8",0,0))
        self.env["GITHUB_RUN_ID"]="43634315994"
        self.assertFalse(note_failure(self.env,"timeout"))
        row=collect(self.env,self.ledger)
        self.assertEqual(row[3],"none")
        self.assertIsNone(row[1])


if __name__=="__main__":
    unittest.main()
