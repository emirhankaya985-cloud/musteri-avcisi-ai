"""Mail watcher lifecycle bridge tests; no DB or mail service calls."""
import unittest
from unittest.mock import patch

from leadhunter.mail_lifecycle import record_matched_reply, record_smtp_acceptance


class Cursor:
    def __init__(self, exists=True):
        self.exists = exists
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def execute(self, query):
        self.query = query
    def fetchone(self):
        return ("owner_lead_lifecycle_state",) if self.exists else (None,)


class Connection:
    def __init__(self, exists=True):
        self.cur = Cursor(exists)
    def cursor(self):
        return self.cur


class MailLifecycleTests(unittest.TestCase):
    def test_explicit_matched_optout_records_dnc_with_redacted_evidence(self):
        db = Connection()
        with patch("leadhunter.mail_lifecycle.record_transition",
                   return_value={"changed": True, "replayed": False}) as record:
            result = record_matched_reply(
                db, "node/1", sender="business@example.invalid",
                reply_reference="reply:<frozen-message-id@gmail.invalid>",
                intent="opt_out")
        self.assertEqual(result["stage"], "do_not_contact")
        args, kwargs = record.call_args
        self.assertEqual(args[2], "do_not_contact")
        self.assertNotIn("@", kwargs["evidence_refs"][0])
        self.assertTrue(kwargs["idempotency_key"].startswith("gmail-optout:"))

    def test_reply_advances_only_existing_email_sent_lifecycle(self):
        db = Connection()
        with patch("leadhunter.mail_lifecycle.read_stage",
                   return_value={"stage": "email_sent"}), patch(
                       "leadhunter.mail_lifecycle.record_transition",
                       return_value={"changed": True, "replayed": False}) as record:
            result = record_matched_reply(
                db, "node/2", sender="business@example.invalid",
                reply_reference="reply:<frozen-message-id@gmail.invalid>",
                intent="positive_review")
        self.assertEqual(result["stage"], "replied")
        self.assertEqual(record.call_args.args[2], "replied")

    def test_reply_does_not_backfill_missing_email_sent_history(self):
        db = Connection()
        with patch("leadhunter.mail_lifecycle.read_stage", return_value=None), patch(
                "leadhunter.mail_lifecycle.record_transition") as record:
            result = record_matched_reply(
                db, "node/3", sender="business@example.invalid",
                reply_reference="reply:<frozen-message-id@gmail.invalid>",
                intent="needs_review")
        self.assertFalse(result["recorded"])
        self.assertEqual(result["reason"], "no_email_sent_lifecycle_evidence")
        record.assert_not_called()

    def test_missing_migration_and_unsupported_intent_fail_closed(self):
        with patch("leadhunter.mail_lifecycle.record_transition") as record:
            missing = record_matched_reply(
                Connection(False), "node/4", sender="business@example.invalid",
                reply_reference="reply:<frozen-message-id@gmail.invalid>",
                intent="opt_out")
            invalid = record_matched_reply(
                Connection(True), "node/4", sender="business@example.invalid",
                reply_reference="reply:<frozen-message-id@gmail.invalid>",
                intent="unknown")
        self.assertEqual(missing["reason"], "lifecycle_schema_missing")
        self.assertEqual(invalid["reason"], "unsupported_intent")
        record.assert_not_called()

    def test_smtp_acceptance_advances_only_existing_prepared_proposal(self):
        db = Connection()
        with patch("leadhunter.mail_lifecycle.read_stage",
                   return_value={"stage": "proposal_prepared"}), patch(
                       "leadhunter.mail_lifecycle.record_transition",
                       return_value={"changed": True, "replayed": False}) as record:
            result = record_smtp_acceptance(db, "node/5", claim_id="a" * 24)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["reason"], "smtp_accepted_not_delivery_confirmed")
        self.assertEqual(record.call_args.args[2], "email_sent")
        self.assertTrue(record.call_args.kwargs["evidence_refs"][0].startswith(
            "smtp-claim://sha256/"))
        self.assertNotIn("@", record.call_args.kwargs["evidence_refs"][0])

    def test_smtp_acceptance_does_not_backfill_or_skip_prepared_stage(self):
        for stage in (None, {"stage": "communication_eligible"},
                      {"stage": "do_not_contact"}):
            with self.subTest(stage=stage), patch(
                    "leadhunter.mail_lifecycle.read_stage", return_value=stage), patch(
                        "leadhunter.mail_lifecycle.record_transition") as record:
                result = record_smtp_acceptance(
                    Connection(), "node/6", claim_id="b" * 24)
            self.assertFalse(result["recorded"])
            record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
