import base64
from email import message_from_bytes
import io
import json
import unittest
from urllib.parse import parse_qs

from leadhunter.gmail_api import SCOPE, SEND_URL, TOKEN_URL, send_message


def response(value):
    return io.BytesIO(json.dumps(value).encode("utf-8"))


def enabled_env():
    return {
        "GMAIL_API_ENABLED": "true",
        "GMAIL_SENDER_ADDRESS": "owner@gmail.com",
        "GMAIL_OAUTH_SCOPE": SCOPE,
        "GMAIL_OAUTH_CLIENT_ID": "client-id",
        "GMAIL_OAUTH_CLIENT_SECRET": "client-secret",
        "GMAIL_OAUTH_REFRESH_TOKEN": "refresh-secret",
    }


class GmailApiTests(unittest.TestCase):
    def test_disabled_by_default_and_no_network(self):
        calls = []
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            send_message("owner@gmail.com", "subject", "body", {},
                         opener=lambda *args, **kwargs: calls.append(args))
        self.assertEqual(calls, [])

    def test_rejects_scope_mismatch_before_network(self):
        env = enabled_env()
        env["GMAIL_OAUTH_SCOPE"] = "https://mail.google.com/"
        calls = []
        with self.assertRaisesRegex(RuntimeError, "scope"):
            send_message("owner@gmail.com", "subject", "body", env,
                         opener=lambda *args, **kwargs: calls.append(args))
        self.assertEqual(calls, [])

    def test_success_requires_real_api_id_and_uses_bearer_refresh_flow(self):
        calls = []

        def opener(request, timeout=None):
            calls.append(request)
            if request.full_url == TOKEN_URL:
                form = parse_qs(request.data.decode("ascii"))
                self.assertEqual(form["grant_type"], ["refresh_token"])
                self.assertEqual(form["client_id"], ["client-id"])
                self.assertEqual(form["refresh_token"], ["refresh-secret"])
                self.assertEqual(timeout, 30)
                return response({"access_token": "short-lived-token",
                                 "token_type": "Bearer"})
            self.assertEqual(request.full_url, SEND_URL)
            self.assertEqual(request.get_header("Authorization"),
                             "Bearer short-lived-token")
            self.assertEqual(timeout, 30)
            payload = json.loads(request.data.decode("ascii"))
            raw = payload["raw"]
            raw += "=" * (-len(raw) % 4)
            message = message_from_bytes(base64.urlsafe_b64decode(raw))
            self.assertEqual(message["To"], "customer@example.test")
            self.assertEqual(message["Subject"], "Hello")
            return response({"id": "gmail-message-123", "threadId": "thread-9"})

        result = send_message("customer@example.test", "Hello", "Body text",
                              enabled_env(), opener)
        self.assertEqual(result, "gmail-message-123")
        self.assertEqual([call.full_url for call in calls], [TOKEN_URL, SEND_URL])

    def test_send_errors_are_redacted(self):
        env = enabled_env()
        sequence = iter((response({"access_token": "token-secret"}),
                         response({"error": "recipient address secret"})))
        with self.assertRaises(RuntimeError) as raised:
            send_message("customer@example.test", "Hello", "Body", env,
                         lambda *_args, **_kwargs: next(sequence))
        self.assertEqual(str(raised.exception),
                         "Gmail API accepted no verifiable message ID")
        self.assertNotIn("recipient address", str(raised.exception))
        self.assertNotIn("token-secret", str(raised.exception))

    def test_invalid_header_rejected_before_oauth(self):
        calls = []
        with self.assertRaises(ValueError):
            send_message("customer@example.test", "bad\nsubject", "body",
                         enabled_env(), lambda *args, **kwargs: calls.append(args))
        self.assertEqual(calls, [])

    def test_refresh_failure_does_not_expose_secrets(self):
        def fail(*_args, **_kwargs):
            raise RuntimeError("refresh-secret client-secret")
        with self.assertRaises(RuntimeError) as raised:
            send_message("customer@example.test", "Hello", "Body",
                         enabled_env(), fail)
        self.assertEqual(str(raised.exception),
                         "Gmail OAuth token refresh failed; details redacted")
        self.assertNotIn("secret", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
