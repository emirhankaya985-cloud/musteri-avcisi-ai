"""Safe offline Telegram inline-keyboard checks."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from leadhunter.telegram_buttons import api, send_test, process_update, poll, OPTIONS


def response(value, calls):
    def open_(req, timeout=None):
        name = req.full_url.split("/")[-1]
        body = json.loads(req.data)
        calls.append((name, body))
        return io.BytesIO(json.dumps({"ok": True, "result": value}).encode())
    return open_


class TelegramButtonTests(unittest.TestCase):
    def test_three_demo_buttons_owner_only(self):
        calls = []
        send_test({"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "123"},
                  opener=response({"message_id": 42}, calls), output=lambda _: None)
        self.assertEqual(calls[0][0], "sendMessage")
        self.assertEqual(calls[0][1]["chat_id"], "123")
        keyboard = calls[0][1]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([x["callback_data"] for x in keyboard], list(OPTIONS))
        self.assertEqual(len(keyboard), 3)
        self.assertIn("gerçek işletme değil", calls[0][1]["text"])

    def test_send_requires_ack(self):
        with self.assertRaisesRegex(RuntimeError, "not confirmed"):
            send_test({"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "123"},
                      opener=response({}, []), output=lambda _: None)

    def test_callback_updates_only_owner_demo_and_disables_buttons(self):
        calls = []
        cb = {"callback_query": {
            "id": "q", "data": "demo:v1:later", "from": {"id": 123},
            "message": {"message_id": 42,
                        "text": "🧪 Müşteri Avcısı AI — Buton Testi\nDemo",
                        "chat": {"id": 123, "type": "private"}}}}
        self.assertTrue(process_update(cb, "fake", "123", response(True, calls)))
        self.assertEqual([n for n, _ in calls], ["editMessageText", "answerCallbackQuery"])
        self.assertIn("BEKLET", calls[0][1]["text"])
        self.assertEqual(calls[0][1]["reply_markup"]["inline_keyboard"], [])
        cb["callback_query"]["from"]["id"] = 321
        self.assertFalse(process_update(cb, "fake", "123", response(True, calls)))
        self.assertEqual(len(calls), 2)

    def test_no_unknown_action_or_foreign_message(self):
        calls = []
        cb = {"callback_query": {
            "id": "q", "data": "demo:v1:yes", "from": {"id": 123},
            "message": {"message_id": 10, "text": "unrelated message",
                        "chat": {"id": 123, "type": "private"}}}}
        self.assertFalse(process_update(cb, "fake", "123", response(True, calls)))
        self.assertEqual(calls, [])

    def test_api_error_redacts_token(self):
        def fail(req, timeout=None):
            raise HTTPError(req.full_url, 403, "forbidden", {}, None)
        with self.assertRaisesRegex(RuntimeError, "credentials redacted") as exc:
            api("TOP_SECRET", "sendMessage", {}, opener=fail)
        self.assertNotIn("TOP_SECRET", str(exc.exception))

    def test_poll_stores_only_numeric_cursor(self):
        def open_(req, timeout=None):
            name = req.full_url.split("/")[-1]
            result = {"url": ""} if name == "getWebhookInfo" else [
                {"update_id": 99, "message": {"text": "ignore"}}]
            return io.BytesIO(json.dumps({"ok": True, "result": result}).encode())
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "offset.json"
            env = {"TELEGRAM_BOT_TOKEN": "fake", "TELEGRAM_CHAT_ID": "123",
                   "CALLBACK_OFFSET_FILE": str(path)}
            self.assertEqual(poll(env, open_, lambda _: None), 0)
            self.assertEqual(json.loads(path.read_text()), {"next_offset": 100})


    def test_expired_callback_query_ack_does_not_erase_saved_choice(self):
        calls = []
        cb = {"callback_query": {
            "id": "expired", "data": "demo:v1:no", "from": {"id": 123},
            "message": {"message_id": 42,
                        "text": "🧪 Müşteri Avcısı AI — Buton Testi",
                        "chat": {"id": 123, "type": "private"}}}}
        def opener(req, timeout=None):
            method = req.full_url.split("/")[-1]
            calls.append(method)
            if method == "answerCallbackQuery":
                raise HTTPError(req.full_url, 400, "query is too old", {}, None)
            return io.BytesIO(b'{"ok": true, "result": true}')
        self.assertTrue(process_update(cb, "fake", "123", opener))
        self.assertEqual(calls, ["editMessageText", "answerCallbackQuery"])
