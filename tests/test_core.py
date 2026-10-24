import tempfile
import json
import io
import unittest
from urllib.error import HTTPError, URLError
from pathlib import Path
from leadhunter.core import (bbox_parse, lead_from_osm, select_leads, format_telegram,
                             read_seen, save_seen, live, offer)

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.osm = {'type':'node','id':42,'tags':{'name':'Test & Wash','amenity':'car_wash','phone':'123'}}

    def test_bbox(self):
        self.assertEqual(len(bbox_parse('40.98,29.00,41,29.02')), 4)
        with self.assertRaises(ValueError): bbox_parse('1,2,3')
        with self.assertRaises(ValueError): bbox_parse('1,2,3,4')

    def test_lead(self):
        lead = lead_from_osm(self.osm)
        self.assertEqual(lead['score'], 90)
        self.assertEqual(lead['id'], 'node/42')

    def test_missing_name_rejected(self):
        self.assertIsNone(lead_from_osm({'type':'node','id':3,'tags':{'shop':'beauty'}}))

    def test_escapes_html(self):
        msg = format_telegram(lead_from_osm(self.osm))
        self.assertIn('Test &amp; Wash', msg)
        self.assertIn('ayrıca doğrula', msg)

    def test_known_website(self):
        self.osm['tags']['website'] = 'https://example.com'
        self.assertIn('web sitesi var', format_telegram(lead_from_osm(self.osm)))

    def test_dedupe(self):
        self.assertEqual(len(select_leads([self.osm, self.osm], set())), 1)
        self.assertEqual(select_leads([self.osm], {'node/42'}), [])

    def test_no_website_claim(self):
        self.assertNotIn('web sitesi kesinlikle yok', format_telegram(lead_from_osm(self.osm)))

    def test_state(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'seen.json'
            self.assertEqual(read_seen(p), set())
            save_seen(p, {'node/42', 'way/12'})
            self.assertEqual(read_seen(p), {'node/42', 'way/12'})

    def test_offer(self):
        self.assertIn('Örnek', offer({'name':'Örnek'}))

    def test_end_to_end_mock_telegram(self):
        calls = []
        def fake_open(request, timeout=None):
            if 'overpass' in request.full_url:
                payload = {'elements':[self.osm]}
            else:
                calls.append(json.loads(request.data.decode()))
                payload = {'ok':True, 'result':{'message_id':17}}
            return io.BytesIO(json.dumps(payload).encode())
        with tempfile.TemporaryDirectory() as d:
            env = {'TELEGRAM_BOT_TOKEN':'test-not-real', 'TELEGRAM_CHAT_ID':'123',
                   'STATE_FILE':str(Path(d) / 'seen.json')}
            self.assertEqual(live(env=env, opener=fake_open, output=lambda _:None), 1)
            self.assertEqual(read_seen(Path(d) / 'seen.json'), {'node/42'})
            self.assertEqual(len(calls), 1)
            self.assertIn('Test &amp; Wash', calls[0]['text'])
            self.assertEqual(live(env=env, opener=fake_open, output=lambda _:None), 0)
            self.assertEqual(len(calls), 1)

    def test_telegram_http_error_never_exposes_bot_token(self):
        from leadhunter.core import send_telegram
        secret = 'SUPER_PRIVATE_BOT_TOKEN'
        def failed_open(req, timeout=None):
            raise HTTPError(req.full_url, 403, 'Forbidden', {}, None)
        with self.assertRaisesRegex(RuntimeError, 'Telegram API HTTP 403') as caught:
            send_telegram('test', secret, '123', opener=failed_open)
        self.assertNotIn(secret, str(caught.exception))

    def test_telegram_network_error_has_generic_message(self):
        from leadhunter.core import send_telegram
        def failed_open(req, timeout=None):
            raise URLError('bad connection')
        with self.assertRaisesRegex(RuntimeError, 'connection failed'):
            send_telegram('test', 'SECRET', '123', opener=failed_open)

    def test_live_no_token(self):
        with self.assertRaisesRegex(RuntimeError, 'TELEGRAM'):
            live(env={})

if __name__ == '__main__':
    unittest.main()
