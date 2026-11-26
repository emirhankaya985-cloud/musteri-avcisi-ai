"""Optional ntfy report publisher uses only synthetic messages and fake HTTP."""
import io
import unittest
from urllib.error import HTTPError

from leadhunter.ntfy_report import _topic_url, send_daily


class NtfyReportTests(unittest.TestCase):
    def test_missing_topic_is_disabled_without_network(self):
        self.assertEqual(send_daily("aggregate only", {}, opener=None), "disabled")

    def test_only_https_ntfy_sh_single_topic_is_allowed(self):
        self.assertEqual(_topic_url("https://ntfy.sh/owner_daily"),
                         "https://ntfy.sh/owner_daily")
        for url in (
            "http://ntfy.sh/owner_daily",
            "https://ntfy.sh/topic/other",
            "https://ntfy.sh/topic?token=secret",
            "https://user:pass@ntfy.sh/topic",
            "https://example.org/topic",
            "https://ntfy.sh/a%2Fb",
        ):
            with self.subTest(url=url):
                self.assertIsNone(_topic_url(url))

    def test_publish_is_aggregate_plain_text_and_auth_is_header_only(self):
        calls = []

        class Response(io.BytesIO):
            status = 200

        class Opener:
            def open(self, request, timeout):
                calls.append((request, timeout))
                return Response(b'{"id":"synthetic"}')

        status = send_daily(
            "Günlük CRM toplamı: 10; gönderim uygunluğu: 0",
            {"NTFY_TOPIC_URL": "https://ntfy.sh/owner_daily",
             "NTFY_TOKEN": "synthetic-token"}, opener=Opener())
        self.assertEqual(status, "accepted")
        request, timeout = calls[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(request.full_url, "https://ntfy.sh/owner_daily")
        self.assertEqual(request.data.decode(),
                         "Günlük CRM toplamı: 10; gönderim uygunluğu: 0")
        self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-token")
        self.assertEqual(timeout, 10)

    def test_bad_config_oversize_or_http_failure_never_leaks_details(self):
        calls = []

        class Opener:
            def open(self, request, timeout):
                calls.append(request)
                raise HTTPError(request.full_url, 403, "synthetic", {}, None)

        self.assertEqual(send_daily("x", {"NTFY_TOPIC_URL": "https://example.org/t"}, Opener()),
                         "invalid_config")
        self.assertEqual(send_daily("x" * 4097, {"NTFY_TOPIC_URL": "https://ntfy.sh/t"}, Opener()),
                         "message_too_large")
        self.assertEqual(send_daily("aggregate", {"NTFY_TOPIC_URL": "https://ntfy.sh/t"}, Opener()),
                         "rejected")
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
