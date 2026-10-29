import io
import unittest
from email.message import Message
from unittest.mock import patch
from leadhunter.contact_email import Contacts, discover_email, public_url


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

    def test_multiple_addresses_are_not_silently_selected(self):
        class Response(io.BytesIO):
            headers = Message()
            headers['Content-Type'] = 'text/html; charset=utf-8'
            def geturl(self):
                return 'https://business.invalid/'
        with patch('leadhunter.contact_email.public_url'), patch('leadhunter.contact_email.build_opener') as client:
            client.return_value.open.return_value = Response(b'<a href="mailto:a@business.invalid">A</a> b@business.invalid')
            lead = {'website': 'https://business.invalid/'}
            self.assertEqual(discover_email(lead), lead)

    def test_unique_published_address_keeps_source_privately(self):
        class Response(io.BytesIO):
            headers = Message()
            headers['Content-Type'] = 'text/html; charset=utf-8'
            def geturl(self):
                return 'https://business.invalid/'
        with patch('leadhunter.contact_email.public_url'), patch('leadhunter.contact_email.build_opener') as client:
            client.return_value.open.return_value = Response(b'<a href="mailto:info@business.invalid">Contact</a>')
            result = discover_email({'website': 'https://business.invalid/'})
            self.assertEqual(result['email'], 'info@business.invalid')
            self.assertEqual(result['email_source'], 'https://business.invalid/')

    def test_no_site_never_guesses_an_address(self):
        self.assertEqual(discover_email({'name': 'Salon'}), {'name': 'Salon'})
