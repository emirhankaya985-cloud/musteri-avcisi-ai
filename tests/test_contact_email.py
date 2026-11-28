import io
import unittest
from email.message import Message
from unittest.mock import call, patch
from leadhunter.contact_email import Contacts, discover_email, public_url


class Response(io.BytesIO):
    def __init__(self, body, url, content_type='text/html; charset=utf-8'):
        super().__init__(body)
        self.headers = Message()
        self.headers['Content-Type'] = content_type
        self.url = url
    def geturl(self):
        return self.url


def fake_open(pages, robots=b'User-agent: *\nAllow: /'):
    def open_page(request, timeout):
        if request.full_url == 'https://business.invalid/robots.txt':
            if robots is None:
                raise OSError('robots policy unavailable')
            return Response(robots, request.full_url, 'text/plain; charset=utf-8')
        return pages[request.full_url]
    return open_page


class ContactEmailTests(unittest.TestCase):
    def test_private_and_cross_host_urls_are_rejected(self):
        private = lambda *a, **k: [(2, 1, 6, '', ('127.0.0.1', 443))]
        for url in ('https://business.invalid/', 'https://other.invalid/', 'file:///etc/passwd'):
            with self.assertRaises(ValueError):
                public_url(url, 'business.invalid', private)

    def test_extracts_visible_and_mailto_but_ignores_scripts(self):
        p = Contacts()
        p.feed('<script>hidden@business.invalid</script><a href="mailto:info@business.invalid?subject=test">Email</a>')
        self.assertEqual(p.candidates(), {'info@business.invalid'})

    def test_extracts_obfuscated_and_html_split_public_email(self):
        p = Contacts()
        p.feed('info [at] business [dot] invalid; sales@<span>business.invalid</span>')
        self.assertEqual(p.candidates(), {'info@business.invalid', 'sales@business.invalid'})

    def test_multiple_addresses_are_not_silently_selected(self):
        with patch('leadhunter.contact_email.public_url'), patch('leadhunter.contact_email.build_opener') as client:
            client.return_value.open.side_effect = fake_open({
                'https://business.invalid/': Response(
                    b'<a href="mailto:a@business.invalid">A</a> b@business.invalid',
                    'https://business.invalid/')})
            lead = {'website': 'https://business.invalid/'}
            self.assertEqual(discover_email(lead), lead)

    def test_unique_published_address_keeps_source_privately(self):
        with patch('leadhunter.contact_email.public_url'), patch('leadhunter.contact_email.build_opener') as client:
            client.return_value.open.side_effect = fake_open({
                'https://business.invalid/': Response(
                    b'<a href="mailto:info@business.invalid">Contact</a>',
                    'https://business.invalid/')})
            result = discover_email({'website': 'https://business.invalid/'})
            self.assertEqual(result['email'], 'info@business.invalid')
            self.assertEqual(result['email_source'], 'https://business.invalid/')
            self.assertEqual(result['email_source_host'], 'business.invalid')
            self.assertEqual(result['email_source_type'], 'business_website_public_contact')
            self.assertEqual(result['email_domain'], 'business.invalid')
            self.assertTrue(result['email_retrieved_at'].endswith('+00:00'))

    def test_broken_contact_subpage_does_not_discard_homepage_email(self):
        def open_page(request, timeout):
            if request.full_url == 'https://business.invalid/robots.txt':
                return Response(b'User-agent: *\nAllow: /', request.full_url,
                                'text/plain; charset=utf-8')
            if request.full_url == 'https://business.invalid/':
                return Response(b'<a href="/iletisim">Contact</a> info@business.invalid',
                                'https://business.invalid/')
            raise OSError('synthetic contact subpage unavailable')
        with patch('leadhunter.contact_email.public_url'), patch(
                'leadhunter.contact_email.build_opener') as client:
            client.return_value.open.side_effect = open_page
            result = discover_email({'website': 'https://business.invalid/'})
        self.assertEqual(result['email'], 'info@business.invalid')
        self.assertEqual(result['email_source'], 'https://business.invalid/')

    def test_prefers_published_general_contact_over_another_department(self):
        pages = {
            'https://business.invalid/': Response(
                b'<a href="/iletisim">Contact</a><a href="/about">About</a>',
                'https://business.invalid/'),
            'https://business.invalid/iletisim': Response(
                b'<a href="mailto:info@business.invalid">info</a> sales@business.invalid',
                'https://business.invalid/iletisim'),
            'https://business.invalid/about': Response(
                b'<a href="mailto:owner@business.invalid">Owner</a>',
                'https://business.invalid/about'),
        }
        with patch('leadhunter.contact_email.public_url'), patch(
                'leadhunter.contact_email.build_opener') as client:
            client.return_value.open.side_effect = fake_open(pages)
            result = discover_email({'website': 'https://business.invalid/'})
        self.assertEqual(result['email'], 'info@business.invalid')
        self.assertEqual(result['email_source'], 'https://business.invalid/iletisim')

    def test_robots_disallow_prevents_business_page_fetch(self):
        calls = []
        def open_page(request, timeout):
            calls.append(request.full_url)
            if request.full_url == 'https://business.invalid/robots.txt':
                return Response(b'User-agent: *\nDisallow: /', request.full_url,
                                'text/plain; charset=utf-8')
            return Response(b'info@business.invalid', request.full_url)
        with patch('leadhunter.contact_email.public_url'), patch(
                'leadhunter.contact_email.build_opener') as client:
            client.return_value.open.side_effect = open_page
            lead = {'website': 'https://business.invalid/'}
            self.assertEqual(discover_email(lead), lead)
        self.assertEqual(calls, ['https://business.invalid/robots.txt'])

    def test_unreadable_robots_policy_fails_closed(self):
        calls = []
        def open_page(request, timeout):
            calls.append(request.full_url)
            raise OSError('robots policy unavailable')
        with patch('leadhunter.contact_email.public_url'), patch(
                'leadhunter.contact_email.build_opener') as client:
            client.return_value.open.side_effect = open_page
            lead = {'website': 'https://business.invalid/'}
            self.assertEqual(discover_email(lead), lead)
        self.assertEqual(calls, ['https://business.invalid/robots.txt'])

    def test_robots_policy_fetch_is_bounded_and_same_host_checked(self):
        from leadhunter.contact_email import _read_robots_policy
        class OversizedResponse(Response):
            def read(self, _amount=-1):
                return b'x' * (300_001)
        opener = type('Opener', (), {
            'open': lambda _self, _request, timeout: OversizedResponse(
                b'', 'https://business.invalid/robots.txt', 'text/plain')
        })()
        with patch('leadhunter.contact_email.public_url') as check:
            self.assertIsNone(_read_robots_policy(
                opener, 'https://business.invalid/', 'business.invalid'))
        self.assertEqual(check.call_args_list, [
            call('https://business.invalid/robots.txt', 'business.invalid'),
            call('https://business.invalid/robots.txt', 'business.invalid'),
        ])

    def test_www_and_apex_are_same_recorded_site_but_still_publicly_resolved(self):
        public = lambda *a, **k: [(2, 1, 6, '', ('93.184.216.34', 443))]
        self.assertEqual(public_url('https://www.business.invalid/contact',
                                    'business.invalid', public),
                         'https://www.business.invalid/contact')

    def test_no_site_never_guesses_an_address(self):
        self.assertEqual(discover_email({'name': 'Salon'}), {'name': 'Salon'})

