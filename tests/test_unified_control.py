"""Federated owner control tests: zero live network, SMTP, or review publishing."""
import json
from pathlib import Path
import unittest
from leadhunter.unified_control import SERVICES, probe, snapshot, safe_report


class FakeResponse:
    def __init__(self, url, body, status=200):
        self.url, self.body, self.status = url, body, status
    def geturl(self):
        return self.url
    def read(self, _count):
        return json.dumps(self.body).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False


class ControlSafetyTests(unittest.TestCase):
    def test_read_only_health_checks_use_only_fixed_allowlisted_urls(self):
        visited = []
        def open_fake(req, timeout):
            self.assertEqual(req.get_method(), "GET")
            self.assertLessEqual(timeout, 6)
            self.assertNotIn("Authorization", req.headers)
            visited.append(req.full_url)
            body = ({"status":"ok","database":"ok","service":"api"}
                    if req.full_url.endswith("/health") else
                    {"status":"ok","google_mode":"mock"})
            return FakeResponse(req.full_url,body)
        status = snapshot(open_fake)
        self.assertEqual(status, {"isletmepilot":"http_200","yorumpilot":"http_200"})
        self.assertEqual(set(visited),{v["url"] for v in SERVICES.values()})
        label = safe_report(status)
        self.assertIn("OAuth/CRM yetkili kabulü: ayrıca doğrulanmadı",label)
        self.assertNotIn("@",label)

    def test_health_http_success_does_not_claim_oauth_or_ownership(self):
        url = SERVICES["yorumpilot"]["url"]
        self.assertEqual(probe("yorumpilot",lambda request,timeout:
                         FakeResponse(url,{"status":"ok","google_mode":"mock"})),
                         "http_200")

    def test_fail_closed_on_http_fail_redirect_and_empty_db(self):
        url = SERVICES["isletmepilot"]["url"]
        self.assertEqual(probe("isletmepilot",lambda request,timeout:
                         FakeResponse(url,{"status":"ok","database":"down"})),
                         "unverified")
        self.assertEqual(probe("isletmepilot",lambda request,timeout:
                         FakeResponse("https://example.org",{"status":"ok","database":"ok"})),
                         "unverified")
        self.assertEqual(probe("isletmepilot",lambda request,timeout:
                         FakeResponse(url,{"status":"ok","database":"ok"},status=503)),
                         "unverified")

    def test_workflow_guards_cannot_start_real_customer_mail(self):
        root=Path(__file__).parents[1]/".github/workflows"
        for name in ("lead-digest.yml","verified-mail-batch.yml","execute-outreach.yml"):
            source=(root/name).read_text(encoding="utf-8")
            self.assertIn("AUTO_MAIL_ENABLED: 'false'", source)
            self.assertNotIn("AUTO_MAIL_ENABLED: 'true'",source)
        self.assertIn("OWNER_VERIFIED_BATCH_APPROVED: NO_LIVE_BATCH",
                      (root/"verified-mail-batch.yml").read_text(encoding="utf-8"))
        self.assertIn("OWNER_APPROVED_MAIL_ENABLED: 'false'",
                      (root/"telegram-buttons-inbox.yml").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
