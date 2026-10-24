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

    def test_overpass_timeout_falls_back_once(self):
        from leadhunter.core import get_osm
        calls = []
        def fake_open(request, timeout=None):
            calls.append(request.full_url)
            if len(calls) == 1:
                raise TimeoutError('provider temporarily busy')
            return io.BytesIO(json.dumps({'elements': [self.osm]}).encode())
        self.assertEqual(get_osm((40.98, 29, 41, 29.02), fake_open), [self.osm])
        self.assertEqual(len(calls), 2)
        self.assertNotEqual(calls[0], calls[1])

    def test_overpass_all_unavailable_fails_safely(self):
        from leadhunter.core import get_osm
        def fail(_request, timeout=None):
            raise TimeoutError('timeout')
        with self.assertRaisesRegex(RuntimeError, 'Overpass instances unavailable'):
            get_osm((40.98, 29, 41, 29.02), fail)

    def test_red_website_when_osm_website_missing(self):
        from leadhunter.core import recommend
        lead = lead_from_osm(self.osm)
        result = recommend(lead)
        self.assertEqual(result['focus'], 'website')
        self.assertIn('🔴 WEB SİTESİ', format_telegram(lead))
        self.assertIn('manuel doğrula', result['evidence'])
        self.assertNotIn('kesinlikle', result['evidence'])

    def test_green_automation_when_osm_website_recorded(self):
        from leadhunter.core import recommend
        self.osm['tags']['website'] = 'https://example.com'
        lead = lead_from_osm(self.osm)
        result = recommend(lead)
        self.assertEqual(result['focus'], 'automation')
        self.assertIn('🟢 OTOMASYON', format_telegram(lead))
        self.assertIn('mevcut sistemleri bilinmiyor', result['evidence'])

    def test_vertical_specific_website_offers(self):
        from leadhunter.core import recommend
        ideas = []
        for field, value in [('amenity', 'car_wash'), ('shop', 'hairdresser'),
                             ('shop', 'beauty')]:
            tags = {'name': 'Örnek', field: value}
            result = lead_from_osm({'type': 'node', 'id': 12, 'tags': tags})
            ideas.append(recommend(result)['idea'])
        self.assertEqual(len(set(ideas)), 3)

    def test_vertical_specific_automation_offers(self):
        from leadhunter.core import recommend
        ideas = []
        for field, value in [('amenity', 'car_wash'), ('shop', 'hairdresser'),
                             ('shop', 'beauty')]:
            tags = {'name': 'Örnek', field: value, 'website': 'https://example.com'}
            result = lead_from_osm({'type': 'node', 'id': 12, 'tags': tags})
            ideas.append(recommend(result)['idea'])
        self.assertEqual(len(set(ideas)), 3)

    def test_offer_changes_with_business_identity_and_signals(self):
        lead = lead_from_osm(self.osm)
        text1 = offer(lead)
        self.osm['tags']['name'] = 'Yeni Kuaför'
        self.osm['tags']['shop'] = 'hairdresser'
        self.osm['tags'].pop('amenity')
        self.osm['tags']['website'] = 'https://example.com'
        text2 = offer(lead_from_osm(self.osm))
        self.assertNotEqual(text1, text2)
        self.assertIn('Test & Wash', text1)
        self.assertIn('Yeni Kuaför', text2)

    def test_recommendation_does_not_change_dedupe_or_autosend(self):
        lead = lead_from_osm(self.osm)
        self.assertEqual(select_leads([self.osm], {lead['id']}), [])
        self.assertIn('manuel kullanım', format_telegram(lead))

    def test_escaped_customized_output(self):
        self.osm['tags']['name'] = '<Firma & Özel>'
        lead = lead_from_osm(self.osm)
        message = format_telegram(lead)
        self.assertIn('&lt;Firma &amp; Özel&gt;', message)
        self.assertNotIn('<Firma & Özel>', message)

    def test_overpass_three_independent_endpoints_no_busy_loop(self):
        from leadhunter.core import get_osm, OVERPASS_ENDPOINTS
        calls = []
        def fail(req, timeout=None):
            calls.append((req.full_url, timeout))
            raise TimeoutError('busy')
        with self.assertRaisesRegex(RuntimeError, 'Overpass instances unavailable'):
            get_osm((40.98, 29, 41, 29.02), fail)
        self.assertEqual(len(calls), len(OVERPASS_ENDPOINTS))
        self.assertEqual(len({url for url, _ in calls}), 3)
        self.assertTrue(all(timeout <= 25 for _, timeout in calls))

    def test_premium_scope_by_sector(self):
        from leadhunter.core import recommend
        cases = [
            ('amenity', 'car_wash', 'yıkama paketleri'),
            ('shop', 'hairdresser', 'galerisi'),
            ('shop', 'beauty', 'seans'),
        ]
        for field, value, expected in cases:
            with self.subTest(sector=value):
                lead = lead_from_osm({'type':'node', 'id':123,
                        'tags':{'name':'Deneme',field:value}})
                rec = recommend(lead)
                self.assertEqual(rec['focus'], 'website')
                self.assertIn(expected, rec['premium_scope'])
                self.assertIn('premium bir web sitesi', offer(lead))
                self.assertIn('Premium web sitesi kapsamı', format_telegram(lead))

    def test_outreach_requires_manual_review_no_unverified_site_claim(self):
        from leadhunter.core import recommend
        lead = lead_from_osm(self.osm)
        rec = recommend(lead)
        self.assertIn('manuel doğrula', rec['next_step'])
        self.assertIn('yanıt yoksa ısrar etme', rec['next_step'])
        self.assertNotIn('web siteniz yok', offer(lead).lower())
        self.assertIn('Sonraki adım:', format_telegram(lead))

    def test_automation_has_no_premium_website_pitch(self):
        from leadhunter.core import recommend
        self.osm['tags']['website'] = 'https://example.com'
        lead = lead_from_osm(self.osm)
        rec = recommend(lead)
        self.assertEqual(rec['focus'], 'automation')
        self.assertIsNone(rec['premium_scope'])
        self.assertNotIn('Premium web sitesi kapsamı', format_telegram(lead))
        self.assertIn('mevcut sistemlerinize', offer(lead).lower())

    def test_premium_draft_is_safe_from_html_injection(self):
        self.osm['tags']['name'] = '<img src=x onerror=alert(1)>'
        lead = lead_from_osm(self.osm)
        message = format_telegram(lead)
        self.assertIn('&lt;img', message)
        self.assertNotIn('<img', message)
        self.assertIn('otomatik mesaj', message)

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

    def test_discovery_stats_explains_zero_new_opportunities(self):
        from leadhunter.core import discovery_stats
        copy = dict(self.osm)
        invalid = {'type': 'node', 'id': 99, 'tags': {'amenity': 'car_wash'}}
        stats = discovery_stats([self.osm, copy, invalid], {'node/42'})
        self.assertEqual(stats, {
            'fetched': 3, 'eligible': 1, 'rejected': 1,
            'duplicates': 1, 'already_seen': 1, 'new': 0,
        })

    def test_discovery_stats_prints_safe_counts_to_summary(self):
        from leadhunter.core import emit_discovery_summary
        from leadhunter.core import discovery_stats
        with tempfile.TemporaryDirectory() as d:
            summary = Path(d) / 'summary.md'
            lines = []
            stats = discovery_stats([self.osm], set())
            emit_discovery_summary(stats, 1, {'GITHUB_STEP_SUMMARY': str(summary)}, lines.append)
            self.assertIn('1 yeni aday', lines[0])
            self.assertEqual(lines[1], 'Gönderilen yeni fırsat: 1')
            result = summary.read_text(encoding='utf-8')
            self.assertIn('Telegram gönderimi', result)
            self.assertIn('\n| Ham |', result)
            self.assertNotIn('Test & Wash', result)
            self.assertNotIn('123', result)

    def test_partial_failure_still_reports_confirmed_send_count(self):
        from urllib.error import HTTPError
        lines = []
        sends = []
        rows = [self.osm, {'type':'node', 'id':43, 'tags':{'name':'Second', 'amenity':'car_wash'}}]
        def fake_open(req, timeout=None):
            if req.full_url.startswith('https://api.telegram.org/'):
                sends.append(1)
                if len(sends) > 1:
                    raise HTTPError(req.full_url, 500, 'failure', {}, None)
                return io.BytesIO(b'{"ok": true, "result": {"message_id": 4}}')
            return io.BytesIO(json.dumps({'elements': rows}).encode())
        with tempfile.TemporaryDirectory() as d:
            state = Path(d) / 'seen.json'
            env = {'TELEGRAM_BOT_TOKEN':'fake-test-token',
                   'TELEGRAM_CHAT_ID':'test-owner', 'STATE_FILE':str(state)}
            with self.assertRaisesRegex(RuntimeError, 'Telegram API HTTP 500'):
                live(env=env, opener=fake_open, output=lines.append)
            self.assertIn('Gönderilen yeni fırsat: 1', lines)
            self.assertEqual(len(read_seen(state)), 1)


    def test_empty_overpass_result_falls_back_to_another_provider(self):
        from leadhunter.core import get_osm
        calls = []
        def fake_open(req, timeout=None):
            calls.append(req.full_url)
            data = {'elements': []} if len(calls) == 1 else {'elements': [self.osm]}
            return io.BytesIO(json.dumps(data).encode())
        self.assertEqual(get_osm((40.98, 29, 41, 29.02), fake_open), [self.osm])
        self.assertEqual(len(calls), 2)

    def test_overpass_200_error_remark_is_not_empty_success(self):
        from leadhunter.core import get_osm
        calls = []
        def fake_open(req, timeout=None):
            calls.append(req.full_url)
            data = {'remark': 'runtime error: timeout', 'elements': []} if len(calls) == 1 else {'elements': [self.osm]}
            return io.BytesIO(json.dumps(data).encode())
        self.assertEqual(get_osm((40.98, 29, 41, 29.02), fake_open), [self.osm])
        self.assertEqual(len(calls), 2)

    def test_all_overpass_sources_truly_empty_return_no_leads(self):
        from leadhunter.core import get_osm, OVERPASS_ENDPOINTS
        calls = []
        def fake_open(req, timeout=None):
            calls.append(req.full_url)
            return io.BytesIO(b'{"elements": []}')
        self.assertEqual(get_osm((40.98, 29, 41, 29.02), fake_open), [])
        self.assertEqual(len(calls), len(OVERPASS_ENDPOINTS))

    def test_telegram_requires_positive_message_id(self):
        from leadhunter.core import send_telegram
        def fake_open(req, timeout=None):
            return io.BytesIO(b'{"ok": true, "result": {}}')
        with self.assertRaisesRegex(RuntimeError, 'gönderim onayı eksik'):
            send_telegram('test', 'fake-token', 'owner', opener=fake_open)

if __name__ == '__main__':
    unittest.main()
