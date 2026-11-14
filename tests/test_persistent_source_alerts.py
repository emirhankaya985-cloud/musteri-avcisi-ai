"""No-network owner alert policy: only persistent temporary source faults."""
import tempfile
import unittest
from pathlib import Path

from leadhunter.daily_scan import actionable_failure, run
from leadhunter.scan_attempts import begin, note_failure
from leadhunter.tile_progress import commit
from leadhunter.scan_regions import PILOT_BBOXES
from leadhunter.core import bbox_parse


class PersistentSourceAlertTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ledger=Path(tmp.name)/"tiles.json"
        self.env={
            "GITHUB_RUN_ID":"43634315993","OSM_SOURCE_MODE":"coverage",
            "SCAN_TILE_LEDGER":"true","SCAN_OBSERVATION_FILE":str(Path(tmp.name)/"observation.json"),
            "TILE_PROGRESS_FILE":str(self.ledger),
            "TELEGRAM_BOT_TOKEN":"dummy","TELEGRAM_CHAT_ID":"123"
        }
        self.slot="pilot_1_of_8"
        self.box=bbox_parse(PILOT_BBOXES[0])

    def observed_failure(self, reason="http_5xx",code=None):
        self.assertTrue(begin(self.env,self.slot,0,0))
        self.assertTrue(note_failure(self.env,reason,code))
        commit(self.ledger,self.slot,self.box,0,0,attempted=1,
               last_error=reason,last_http_status=code)

    def test_first_two_transient_failures_are_silent_third_is_critical(self):
        self.observed_failure()
        self.assertFalse(actionable_failure(self.env))
        self.observed_failure()
        self.assertFalse(actionable_failure(self.env))
        self.observed_failure()
        self.assertTrue(actionable_failure(self.env))

    def test_429_temporary_silent_and_403_hard_refusal_critical(self):
        self.observed_failure("provider_refusal",429)
        self.assertFalse(actionable_failure(self.env))
        self.assertTrue(note_failure(self.env,"provider_refusal",403))
        self.assertTrue(actionable_failure(self.env))

    def test_source_failure_never_triggers_telegram_if_below_threshold(self):
        self.observed_failure()
        sent=[]
        def failed(**kwargs):
            raise RuntimeError("synthetic temporary HTTP 5xx")
        with self.assertRaisesRegex(RuntimeError,"temporary"):
            run(env=self.env,handler=failed,
                sender=lambda *args:sent.append(args),output=lambda _:None,
                today="2026-11-14")
        self.assertEqual(sent,[])

    def test_unknown_failure_immediately_actionable(self):
        self.assertTrue(actionable_failure(self.env))
        self.assertTrue(begin(self.env,self.slot,0,0))
        self.assertTrue(actionable_failure(self.env))


if __name__=="__main__":
    unittest.main()
