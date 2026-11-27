"""Safe batch research tests; no network, database, or SMTP access."""
import json
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

from leadhunter.historical_contact_research import (
    RESEARCHER_VERSION, _eligible, _public_email_draft_lead, run)


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        if sql.startswith("SELECT pg_try_advisory_lock"):
            self.db.reply = (True,)
        elif sql.startswith("SELECT pg_advisory_unlock"):
            self.db.reply = (True,)
        elif sql.startswith("SELECT count(*) FROM owner_leads"):
            self.db.reply = (sum(
                1 for value in self.db.rows.values()
                if value[1] == "review"
                and value[0].get("email_research", {}).get("status") == "public_address_found"
                and value[0].get("_auto_mail", {}).get("state") == "skipped"
                and value[0].get("_auto_mail", {}).get("email_check") == "no_mx"),)
        elif "email_research'->>'status'='public_address_found'" in sql:
            self.db.reply = [
                (key, value[0], value[1]) for key, value in self.db.rows.items()
                if value[0].get("email_research", {}).get("status") == "public_address_found"
                and value[1] == "review"
            ][:params[0]]
        elif sql.startswith("SELECT osm_id,lead_data,status"):
            self.db.reply = [(key, value[0], value[1])
                             for key, value in self.db.rows.items()]
        elif sql.startswith("UPDATE owner_leads"):
            raw, lead_id, website = params
            row = self.db.rows.get(lead_id)
            if row and row[1] == "review":
                data = row[0]
                if (data.get("website", "") == website
                        and (not str(data.get("email") or "").strip()
                             or data.get("email_check") == "no_mx"
                             or data.get("_auto_mail", {}).get("email_check") == "no_mx")
                        and data.get("_auto_mail", {}).get("state") not in
                        ("sending", "accepted", "uncertain")
                        and data.get("_mail", {}).get("state") not in
                        ("sending", "accepted", "uncertain")
                        and data.get("marketing_eligibility", {}).get("opted_out") is not True):
                    data.update(json.loads(raw))
                    self.rowcount = 1
                else:
                    self.rowcount = 0
            else:
                self.rowcount = 0
            self.db.reply = None
        else:
            raise AssertionError("Unexpected SQL")

    def fetchone(self):
        return self.db.reply

    def fetchall(self):
        return self.db.reply


class FakeDB:
    def __init__(self, rows):
        self.rows = dict(rows)
        self.reply = None

    @contextmanager
    def cursor(self):
        yield FakeCursor(self)

    def close(self):
        pass


def make(lead_id, **data):
    return lead_id, (data, "review")


class HistoricalResearchTests(unittest.TestCase):
    def test_existing_draft_candidate_requires_same_host_source_and_public_research(self):
        base = {
            "website": "https://shop.example",
            "email": "info@shop.example",
            "email_source": "https://shop.example/iletisim",
            "email_research": {"status": "public_address_found"},
        }
        self.assertEqual(_public_email_draft_lead(("node/1", base, "review"))["id"], "node/1")
        self.assertIsNone(_public_email_draft_lead(("node/2", {
            **base, "email_source": "https://other.example/contact"}, "review")))
        self.assertIsNone(_public_email_draft_lead(("node/3", {
            **base, "marketing_eligibility": {"opted_out": True}}, "review")))

    def test_persists_only_unique_official_source_and_never_changes_mail_state(self):
        db = FakeDB([make("node/1", name="Kafe", website="shop.example")])
        calls = []

        def discover(lead):
            calls.append(lead["id"])
            return {**lead, "email": "info@shop.example",
                    "email_source": "https://shop.example/iletisim",
                    "email_check": "mx_present"}

        with patch("leadhunter.automatic_mail.AutoMailStore") as auto_store:
            auto_store.return_value.prepare.return_value = {"state": "draft"}
            out = run(db, discover=discover,
                      now=datetime(2026, 11, 26, tzinfo=timezone.utc),
                      output=lambda _: None)
        self.assertEqual(out["addresses_found"], 1)
        self.assertEqual(out["drafts_prepared"], 1)
        self.assertEqual(calls, ["node/1"])
        data = db.rows["node/1"][0]
        self.assertEqual(data["email"], "info@shop.example")
        self.assertEqual(data["email_source"], "https://shop.example/iletisim")
        self.assertEqual(data["email_research"]["status"], "public_address_found")
        self.assertIsNone(data["email_check"])
        self.assertNotIn("_auto_mail", data)
        self.assertNotIn("marketing_eligibility", data)

    def test_no_unique_address_is_recorded_without_guessing(self):
        db = FakeDB([make("node/2", website="shop.example")])
        out = run(db, discover=lambda lead: lead,
                  now=datetime(2026, 11, 26, tzinfo=timezone.utc),
                  output=lambda _: None)
        self.assertEqual(out["not_found"], 1)
        data = db.rows["node/2"][0]
        self.assertNotIn("email", data)
        self.assertEqual(data["email_research"]["status"],
                         "no_unique_public_address")

    def test_new_research_version_retries_old_host_and_replaces_only_no_mx_email(self):
        old = make("node/8", website="shop.example", email="old@unreachable.invalid",
                   _auto_mail={"state": "skipped", "email_check": "no_mx"},
                   email_research={"status": "public_address_found",
                                   "checked_at": "2026-11-26T00:00:00+00:00"})
        self.assertTrue(_eligible((old[0], old[1][0], old[1][1]))["_force_email_research"])
        db = FakeDB([old])
        with patch("leadhunter.automatic_mail.AutoMailStore") as auto_store:
            auto_store.return_value.prepare.return_value = {"state": "draft"}
            out = run(db, discover=lambda lead: {
                **lead, "email": "info@gmail.com",
                "email_source": "https://shop.example/iletisim",
                "email_check": "mx_present"},
                now=datetime(2026, 11, 27, tzinfo=timezone.utc),
                output=lambda _: None)
        self.assertEqual(out["addresses_found"], 1)
        data = db.rows["node/8"][0]
        self.assertEqual(data["email"], "info@gmail.com")
        self.assertEqual(data["email_research"]["researcher_version"], RESEARCHER_VERSION)
        self.assertNotIn("_force_email_research", data)

    def test_same_host_cooldown_limits_repeat_fetches_across_branches(self):
        db = FakeDB([make("node/3", website="www.shop.example", email_research_attempt={
            "status": "no_unique_public_address",
            "researcher_version": RESEARCHER_VERSION,
            "checked_at": "2026-11-25T00:00:00+00:00"}),
            make("node/4", website="shop.example/branch")])
        calls = []
        out = run(db, discover=lambda lead: calls.append(lead["id"]) or lead,
                  now=datetime(2026, 11, 26, tzinfo=timezone.utc),
                  output=lambda _: None)
        self.assertEqual(out["host_cooldown"], 2)
        self.assertEqual(calls, [])

    def test_unsafe_or_already_contacted_records_are_not_researched(self):
        db = FakeDB([
            make("node/5", website="shop.example", email="existing@shop.example"),
            make("node/6", website="shop.example", marketing_eligibility={"opted_out": True}),
            make("node/7", website="shop.example", _auto_mail={"state": "accepted"}),
        ])
        called = []
        out = run(db, discover=lambda lead: called.append(lead["id"]) or lead,
                  now=datetime(2026, 11, 26, tzinfo=timezone.utc),
                  output=lambda _: None)
        self.assertEqual(called, [])
        self.assertEqual(out["researched"], 0)

    def test_batch_limit_is_bounded(self):
        with self.assertRaises(ValueError):
            run(FakeDB([]), batch_size=51, output=lambda _: None)


if __name__ == "__main__":
    unittest.main()
