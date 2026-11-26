"""The remediation report is aggregate-only and cannot unlock or send."""
import unittest

from leadhunter.mail_outcome import REASON_KEYS
from leadhunter.mail_recovery import remediation_report, run


def reasons(**changes):
    result = dict.fromkeys(REASON_KEYS, 0)
    result.update(changes)
    return result


class DummyCursor:
    def execute(self, sql):
        self.grouped = "GROUP BY 1" in sql

    def fetchone(self):
        return (15, 4, 0, 0)

    def fetchall(self):
        return [("dns_nxdomain", 1), ("mailbox_missing", 1),
                ("relay_denied", 1), ("connection_refused", 1)]

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class DummyConnection:
    def cursor(self):
        return DummyCursor()


class MailRecoveryTests(unittest.TestCase):
    def test_current_sender_state_has_reasoned_actions_but_never_unlocks(self):
        result = remediation_report(
            {"accepted": 15, "failed": 4, "delayed": 0, "replies": 0},
            reasons(dns_nxdomain=1, mailbox_missing=1,
                    relay_denied=1, connection_refused=1))
        self.assertTrue(result["paused"])
        self.assertEqual(result["unverified_delivery"], 11)
        self.assertFalse(result["unlock_authorized"])
        self.assertEqual(result["smtp_attempts"], 0)
        self.assertFalse(result["recipient_details_included"])
        self.assertEqual([x["reason"] for x in result["actions"]],
                         ["dns_nxdomain", "mailbox_missing",
                          "relay_denied", "connection_refused"])

    def test_every_failure_class_has_a_non_retry_remediation(self):
        result = remediation_report(
            {"accepted": 10, "failed": 1, "delayed": 0, "replies": 1},
            reasons(unknown=1))
        self.assertFalse(result["paused"])
        self.assertIn("do not", result["actions"][0]["action"].lower())
        self.assertFalse(result["unlock_authorized"])

    def test_zero_failure_audit_still_does_not_self_authorize_unlock(self):
        result = remediation_report(
            {"accepted": 0, "failed": 0, "delayed": 0, "replies": 0},
            reasons())
        self.assertFalse(result["paused"])
        self.assertFalse(result["unlock_authorized"])
        self.assertEqual(result["smtp_attempts"], 0)

    def test_inconsistent_or_unsafe_aggregates_fail_closed(self):
        valid = {"accepted": 15, "failed": 4, "delayed": 0, "replies": 0}
        for counts, reason_counts in (
            ({**valid, "failed": 5}, reasons(dns_nxdomain=1)),
            ({**valid, "accepted": 3}, reasons(
                dns_nxdomain=1, mailbox_missing=1,
                relay_denied=1, connection_refused=1)),
            (valid, {**reasons(), "dns_nxdomain": True}),
            (valid, {"dns_nxdomain": 4}),
        ):
            with self.subTest(counts=counts, reason_counts=reason_counts):
                with self.assertRaises(ValueError):
                    remediation_report(counts, reason_counts)

    def test_run_outputs_no_private_addresses_or_message_content(self):
        messages = []
        report = run(env={}, connection=DummyConnection(), output=messages.append)
        joined = "\n".join(messages)
        self.assertEqual(report["failed"], 4)
        self.assertIn("sender_paused=True", messages[0])
        self.assertIn("smtp_attempts=0", messages[0])
        self.assertIn("reason=dns_nxdomain; count=1", joined)
        self.assertNotIn("@", joined)
        self.assertNotIn("password", joined.lower())


if __name__ == "__main__":
    unittest.main()
