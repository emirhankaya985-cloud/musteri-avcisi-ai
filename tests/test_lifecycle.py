import unittest

from leadhunter.lifecycle import (
    IdempotencyConflict,
    LifecycleError,
    OptOutProtected,
    first_stage,
    validate_event,
    validate_transition,
)
from leadhunter.lifecycle_store import _opted_out


class LifecycleTests(unittest.TestCase):
    def test_requested_sales_stages_are_supported(self):
        from leadhunter.lifecycle import STAGES

        self.assertEqual(STAGES, (
            "new_discovered", "researched", "need_verified",
            "communication_eligible", "proposal_prepared", "email_sent",
            "replied", "meeting_scheduled", "offer_made", "won", "lost",
            "do_not_contact",
        ))

    def test_normal_sales_path_is_explicit_and_non_skippable(self):
        path = (
            "new_discovered", "researched", "need_verified",
            "communication_eligible", "proposal_prepared", "email_sent",
            "replied", "meeting_scheduled", "offer_made", "won",
        )
        for before, after in zip(path, path[1:]):
            self.assertEqual(validate_transition(before, after), (before, after))
        with self.assertRaises(LifecycleError):
            validate_transition("new_discovered", "email_sent")

    def test_communication_eligible_label_is_not_mail_authorization(self):
        # The lifecycle rules contain no consent shortcut; this label only
        # advances CRM stage. The actual recipient gate is a separate module.
        self.assertEqual(
            validate_transition("need_verified", "communication_eligible"),
            ("need_verified", "communication_eligible"),
        )

    def test_opt_out_dominates_any_stage_including_won(self):
        for current in ("new_discovered", "email_sent", "won", "lost"):
            with self.subTest(current=current):
                self.assertEqual(
                    validate_transition(current, "do_not_contact", opted_out=True),
                    (current, "do_not_contact"),
                )
        with self.assertRaises(OptOutProtected):
            validate_transition("researched", "communication_eligible", opted_out=True)
        with self.assertRaises(LifecycleError):
            validate_transition("do_not_contact", "researched")

    def test_terminal_won_and_lost_cannot_be_reopened(self):
        for current in ("won", "lost"):
            with self.subTest(current=current):
                with self.assertRaises(LifecycleError):
                    validate_transition(current, "researched")

    def test_first_stage_respects_existing_opt_out(self):
        self.assertEqual(first_stage(opted_out=False), "new_discovered")
        self.assertEqual(first_stage(opted_out=True), "do_not_contact")
        with self.assertRaises(LifecycleError):
            first_stage(opted_out=None)

    def test_event_requires_safe_evidence_and_idempotency(self):
        self.assertEqual(validate_event(
            idempotency_key="research:lead-123", reason="Site checked",
            evidence_refs=["https://example.org/contact"])[2],
            ("https://example.org/contact",))
        bad = (
            {"idempotency_key": "short", "reason": "Research",
             "evidence_refs": ["https://example.org"]},
            {"idempotency_key": "research:lead-123", "reason": " ",
             "evidence_refs": ["https://example.org"]},
            {"idempotency_key": "research:lead-123", "reason": "Research",
             "evidence_refs": []},
            {"idempotency_key": "research:lead-123", "reason": "Research",
             "evidence_refs": ["smtp://example.org"]},
            {"idempotency_key": "research:lead-123", "reason": "Research",
             "evidence_refs": ["https://example.org/contact?email=a@example.org"]},
        )
        for event in bad:
            with self.subTest(event=event), self.assertRaises(LifecycleError):
                validate_event(**event)

    def test_opt_out_can_be_read_from_existing_private_crm_shapes(self):
        self.assertTrue(_opted_out(
            {"marketing_eligibility": {"opted_out": True}}, "review"))
        self.assertTrue(_opted_out(
            {"_auto_mail": {"reply_feedback": {"intent": "opt_out"}}}, "review"))
        self.assertTrue(_opted_out({}, "rejected"))
        self.assertFalse(_opted_out({}, "review"))


if __name__ == "__main__":
    unittest.main()
