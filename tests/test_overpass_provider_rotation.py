"""Synthetic regressions for compliant next-visit Overpass recovery."""
import io
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

from leadhunter.osm_direct import OSMProviderStop
from leadhunter.osm_overpass_tiles import READONLY_PROVIDERS, get_overpass_tiles


BOX = (40.982, 29.015, 41.008, 29.055)


class NextVisitProviderTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state = Path(folder.name) / "provider.json"

    def query(self, opener, **kwargs):
        return get_overpass_tiles(
            BOX, opener, day=date(2026, 11, 14), hour=0, max_tiles=2,
            tile_start=0, provider_state_path=self.state, **kwargs)

    def test_5xx_switches_only_on_next_visit(self):
        calls = []

        def failed(req, timeout=None):
            calls.append(req.full_url)
            raise HTTPError(req.full_url, 503, "synthetic", None, None)

        with self.assertRaisesRegex(RuntimeError, "No confirmed"):
            self.query(failed, tile_results=[])
        self.assertEqual(calls, [READONLY_PROVIDERS[0]])
        self.assertEqual(json.loads(self.state.read_text())["provider_index"], 1)

        calls.clear()

        def healthy(req, timeout=None):
            calls.append(req.full_url)
            return io.BytesIO(b'{"elements":[]}')

        rows = self.query(healthy, tile_results=[])
        self.assertEqual(rows, [])
        self.assertEqual(calls, [READONLY_PROVIDERS[1]] * 2)
        state = json.loads(self.state.read_text())
        self.assertEqual(state["provider_index"], 1)
        self.assertEqual(state["last_result"], "ok")

    def test_explicit_429_never_rotates_or_retries(self):
        calls = []

        def denied(req, timeout=None):
            calls.append(req.full_url)
            raise HTTPError(req.full_url, 429, "synthetic", None, None)

        with self.assertRaises(OSMProviderStop):
            self.query(denied, tile_results=[])
        self.assertEqual(calls, [READONLY_PROVIDERS[0]])
        self.assertFalse(self.state.exists())

    def test_partial_tile_success_keeps_prefix_and_rotates_next_visit(self):
        calls = []
        results = []

        def partial(req, timeout=None):
            calls.append(req.full_url)
            if len(calls) == 2:
                raise TimeoutError("synthetic")
            return io.BytesIO(b'{"elements":[]}')

        rows = self.query(partial, tile_results=results)
        self.assertEqual(rows, [])
        self.assertEqual(results, [True, False])
        self.assertEqual(calls, [READONLY_PROVIDERS[0]] * 2)
        self.assertEqual(json.loads(self.state.read_text())["provider_index"], 1)

    def test_corrupted_state_fails_before_any_public_request(self):
        self.state.write_text('{"version":1,"provider_index":"invalid"}')
        calls = []
        with self.assertRaisesRegex(RuntimeError, "Invalid Overpass provider state"):
            self.query(lambda req, timeout=None: calls.append(req), tile_results=[])
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
