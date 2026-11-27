"""Owner-only Telegram control without a web panel or second polling consumer."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from leadhunter.telegram_buttons import (
    poll, process_owner_command, status_message,
)


def opener_for(calls, updates=(), accepted_id=88):
    def open_(req, timeout=None):
        method = req.full_url.rsplit("/", 1)[-1]
        payload = json.loads(req.data)
        calls.append((method, payload))
        if method == "getWebhookInfo":
            result = {"url": ""}
        elif method == "getUpdates":
            result = list(updates)
        elif method == "sendMessage":
            result = {"message_id": accepted_id}
        else:
            raise AssertionError("Unexpected Telegram method " + method)
        return io.BytesIO(json.dumps({"ok": True, "result": result}).encode())
    return open_


def message(command="/durum", owner_id=123):
    return {"message": {
        "chat": {"type": "private", "id": owner_id},
        "from": {"id": owner_id, "is_bot": False},
        "text": command,
    }}


class TelegramOwnerOnlyTests(unittest.TestCase):
    def test_durum_counts_only_public_osm_seen_and_verified_report_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            seen = Path(tmp) / "seen.json"
            seen.write_text(json.dumps({"seen_ids": ["node/4", "way/11"]}), encoding="utf-8")
            date = Path(tmp) / "date.json"
            date.write_text('{"last_sent_date":"2026-10-30"}', encoding="utf-8")
            text = status_message({"STATE_FILE": str(seen), "DIGEST_DAY_STATE_FILE": str(date)})
            self.assertIn("görülen kayıt: 2", text)
            self.assertIn("saatte bir", text)
            self.assertIn("15 dakikada bir", text)
            self.assertNotIn("Son günlük rapor", text)
            self.assertIn("belgeli alıcı uygunluğu", text)
            self.assertIn("ayrı CRM", text)
            self.assertNotIn("TELEGRAM_BOT_TOKEN", text)

    def test_only_actual_owner_private_chat_can_run_commands(self):
        calls = []
        send = opener_for(calls)
        env = {"TELEGRAM_BOT_TOKEN": "CI-fixture", "TELEGRAM_CHAT_ID": "123"}
        self.assertTrue(process_owner_command(message(), "fixture-token", "123", env, send))
        self.assertEqual([x[0] for x in calls], ["sendMessage"])
        self.assertEqual(calls[0][1]["chat_id"], "123")
        self.assertIn("Müşteri Avcısı", calls[0][1]["text"])
        for forged in (
            message(owner_id=444),
            {**message(), "message": {**message()["message"], "from": {"id": 444}}},
            {**message(), "message": {**message()["message"], "chat": {"id": 123, "type": "group"}}},
            {**message(), "message": {**message()["message"], "from": {"id": 123, "is_bot": True}}},
            message(command="/unknown"),
            {**message(), "message": {**message()["message"], "date": 1}},
        ):
            self.assertFalse(process_owner_command(forged, "fixture-token", "123", env, send))
        self.assertEqual(len(calls), 1)

    def test_private_owner_commands_are_readonly_and_ack_is_required(self):
        calls = []
        env = {}
        for cmd in ("/durum", "/yardim", "/start"):
            self.assertTrue(process_owner_command(message(cmd), "fixture", "123", env,
                                                  opener_for(calls)))
        self.assertEqual([x[0] for x in calls], ["sendMessage"] * 3)
        self.assertTrue(all("chat_id" in p for _, p in calls))
        with self.assertRaisesRegex(RuntimeError, "not confirmed"):
            process_owner_command(message(), "fixture", "123", env,
                                  opener_for([], accepted_id=0))

    def test_crm_stage_command_is_owner_only_audited_and_never_sends_email(self):
        from unittest.mock import Mock, patch
        update = {"update_id": 123456789, **message(
            "/crm node/12345678 researched osm://node/12345678 official-site-reviewed")}
        review = Mock()
        review.db = object()
        result = {"previous_stage": "new_discovered", "current_stage": "researched",
                  "event_id": 17, "changed": True}
        calls = []
        with patch("leadhunter.lifecycle_store.record_transition", return_value=result) as record:
            self.assertTrue(process_owner_command(
                update, "fixture", "123", {}, opener_for(calls), review_store=review))
        record.assert_called_once_with(
            review.db, "node/12345678", "researched",
            idempotency_key="telegram-crm:123456789",
            reason="official-site-reviewed",
            evidence_refs=("osm://node/12345678",), actor="owner_telegram")
        self.assertEqual([method for method, _ in calls], ["sendMessage"])
        self.assertIn("e-posta göndermedi", calls[0][1]["text"])

        forged_owner = {"update_id": 123456790, **message(
            "/crm node/12345678 researched osm://node/12345678 owner-change", owner_id=444)}
        self.assertFalse(process_owner_command(
            forged_owner, "fixture", "123", {}, opener_for([]), review_store=review))
        invalid_evidence = {"update_id": 123456791, **message(
            "/crm node/12345678 researched https://example.invalid/ref owner-change")}
        self.assertTrue(process_owner_command(
            invalid_evidence, "fixture", "123", {}, opener_for([]), review_store=review))
        self.assertEqual(record.call_count, 1)

    def test_crm_command_receipt_logs_command_name_only(self):
        from unittest.mock import Mock, patch
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            env = {"TELEGRAM_BOT_TOKEN": "fixture", "TELEGRAM_CHAT_ID": "123",
                   "REVIEW_DATABASE_URL": "postgresql://synthetic/?sslmode=require",
                   "CALLBACK_OFFSET_FILE": str(Path(tmp) / "cursor.json"),
                   "OWNER_COMMAND_RECEIPT_FILE": str(Path(tmp) / "receipt.json")}
            update = {"update_id": 371, **message(
                "/crm node/12345678 researched osm://node/12345678 private-sensitive-reason")}
            log = []
            with patch("leadhunter.review_private.connect_private_database", return_value=Mock()), \
                 patch("leadhunter.review_private.ReviewStore") as store_class, \
                 patch("leadhunter.lifecycle_store.record_transition", return_value={
                     "previous_stage": "new_discovered", "current_stage": "researched",
                     "event_id": 17, "changed": True}):
                store_class.return_value.db = object()
                self.assertEqual(poll(env, opener_for(calls, [update]), output=log.append), 1)
            receipt = json.loads(Path(env["OWNER_COMMAND_RECEIPT_FILE"]).read_text())
            self.assertEqual(receipt["command"], "crm")
            self.assertTrue(all("private-sensitive-reason" not in entry for entry in log))

    def test_old_review_buttons_are_not_required_or_processed(self):
        from unittest.mock import Mock, patch
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            env = {"TELEGRAM_BOT_TOKEN": "fixture", "TELEGRAM_CHAT_ID": "123",
                   "OWNER_APPROVED_MAIL_ENABLED": "false",
                   "LEGACY_REVIEW_BUTTONS_ENABLED": "false",
                   "REVIEW_DATABASE_URL": "postgresql://synthetic/?sslmode=require",
                   "CALLBACK_OFFSET_FILE": str(Path(tmp) / "cursor.json")}
            callback = {"update_id": 61, "callback_query": {
                "id": "synthetic-cb", "data": "lead:v1:yes:node/42",
                "from": {"id": 123}, "message": {"chat": {"type": "private", "id": 123},
                "message_id": 73, "text": "old synthetic opportunity"}}}
            db = Mock()
            review = Mock()
            review.decide.side_effect = AssertionError("Old approval cannot modify CRM")
            with patch("leadhunter.review_private.connect_private_database", return_value=db), patch(
                 "leadhunter.review_private.ReviewStore", return_value=review):
                self.assertEqual(poll(env, opener_for(calls, [callback]),
                                      output=lambda *_: None), 0)
            self.assertEqual([m for m, _ in calls], ["getWebhookInfo", "getUpdates"])
            review.decide.assert_not_called()
            self.assertEqual(json.loads(Path(env["CALLBACK_OFFSET_FILE"]).read_text()),
                             {"next_offset": 62})

    def test_single_existing_poll_consumer_handles_commands_and_preserves_cursor(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls = []
            env = {"TELEGRAM_BOT_TOKEN": "fixture", "TELEGRAM_CHAT_ID": "123",
                   "CALLBACK_OFFSET_FILE": str(Path(tmp) / "cursor.json"),
                   "STATE_FILE": str(Path(tmp) / "seen.json"),
                   "DIGEST_DAY_STATE_FILE": str(Path(tmp) / "digest.json"),
                   "OWNER_COMMAND_RECEIPT_FILE": str(Path(tmp) / "receipt.json")}
            updates = [
                {"update_id": 37, **message()},
                {"update_id": 38, **message(owner_id=444)},
            ]
            self.assertEqual(poll(env, opener_for(calls, updates), output=lambda *_: None), 1)
            self.assertEqual([m for m, _ in calls], ["getWebhookInfo", "getUpdates", "sendMessage"])
            self.assertEqual(calls[1][1]["allowed_updates"], ["callback_query", "message"])
            self.assertEqual(json.loads(Path(env["CALLBACK_OFFSET_FILE"]).read_text()),
                             {"next_offset": 39})
            metadata = json.loads(Path(env["OWNER_COMMAND_RECEIPT_FILE"]).read_text())
            self.assertEqual(metadata, {"update_id":37, "command":"durum",
                                       "telegram_message_id":88})
            self.assertNotIn("chat_id", metadata)
            self.assertNotIn("token", metadata)


if __name__ == "__main__":
    unittest.main()
