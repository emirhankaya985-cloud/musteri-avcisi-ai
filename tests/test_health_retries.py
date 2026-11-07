"""Read-only transient GET retries and coarse 4xx/5xx health categories."""
import io
import unittest
from urllib.error import HTTPError, URLError
from leadhunter.unified_control import SERVICES, probe_detail


class FakeResponse:
    def __init__(self, url, code=200):
        self.url, self.status = url, code
    def geturl(self):
        return self.url
    def read(self, size):
        return b'{"status":"ok","database":"ok"}'
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False


class HealthRetryTests(unittest.TestCase):
    def test_503_retries_then_recovers(self):
        url = SERVICES['isletmepilot']['url']
        calls, sleeps = [], []
        def opener(req, timeout):
            self.assertEqual(req.get_method(), 'GET')
            self.assertLessEqual(timeout, 5)
            calls.append(1)
            return FakeResponse(url, 503 if len(calls) == 1 else 200)
        self.assertEqual(probe_detail('isletmepilot', opener, sleeps.append),
                         ('http_200', 'ok'))
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [0.2])

    def test_429_is_not_retried_and_honors_provider_limit(self):
        url = SERVICES['isletmepilot']['url']
        calls = []
        def opener(req, timeout):
            calls.append(1)
            raise HTTPError(url, 429, 'busy', {}, None)
        self.assertEqual(probe_detail('isletmepilot', opener, lambda _: None),
                         ('unverified', 'http_429'))
        self.assertEqual(len(calls), 1)

    def test_400_401_403_not_retried(self):
        url = SERVICES['isletmepilot']['url']
        for code in (400, 401, 403):
            calls = []
            def opener(req, timeout):
                calls.append(1)
                raise HTTPError(url, code, 'no', {}, None)
            self.assertEqual(probe_detail('isletmepilot', opener, lambda _: None),
                             ('unverified', 'http_' + str(code)))
            self.assertEqual(len(calls), 1)

    def test_network_errors_retry_three_times_and_no_false_success(self):
        calls = []
        def opener(req, timeout):
            calls.append(1)
            raise URLError('private-hostname-never-log-this')
        self.assertEqual(probe_detail('yorumpilot', opener, lambda _: None),
                         ('unverified', 'network'))
        self.assertEqual(len(calls), 3)

    def test_network_backoff_has_two_geometric_intervals(self):
        calls, sleeps = [], []
        def opener(req, timeout):
            calls.append(1)
            raise URLError("synthetic network")
        self.assertEqual(probe_detail("yorumpilot", opener, sleeps.append),
                         ("unverified", "network"))
        self.assertEqual(sleeps, [0.2, 0.4])
        self.assertEqual(len(calls),3)

    def test_redirect_is_rejected(self):
        self.assertEqual(probe_detail('isletmepilot', lambda req, timeout:
                         FakeResponse('https://other.example/path'), lambda _: None),
                         ('unverified', 'redirect'))


if __name__ == '__main__':
    unittest.main()
