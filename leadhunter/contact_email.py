"""Bounded contact discovery on the business's recorded public website.

Never guess addresses. Reject ambiguous contacts, private networks and redirects
outside the recorded website host. Results belong only in private mail storage.
"""
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, unquote
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .outreach import valid_recipient


class Contacts(HTMLParser):
    def __init__(self):
        super().__init__()
        self.emails = set()
        self.links = []
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag != 'a':
            return
        href = dict(attrs).get('href', '')
        if href.lower().startswith('mailto:'):
            self.emails.add(unquote(href[7:].split('?')[0]).strip().lower())
        elif any(term in href.lower() for term in ('contact', 'iletisim', 'iletişim')):
            self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def candidates(self):
        visible = ' '.join(self.parts)
        self.emails.update(re.findall(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', visible))
        return {x.lower() for x in self.emails if valid_recipient(x.lower())}


def public_url(url, host, resolver=socket.getaddrinfo):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or parsed.hostname != host
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError('Unsupported business website URL')
    addresses = resolver(host, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('Website must resolve to a public network')
    return url


class SameHostRedirect(HTTPRedirectHandler):
    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl, self.host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def discover_email(lead):
    if valid_recipient(str(lead.get('email') or '').strip().lower()):
        return lead
    url = str(lead.get('website') or '').strip()
    if not url:
        return lead
    if '://' not in url:
        url = 'https://' + url
    try:
        host = urlsplit(url).hostname
        if not host or host in ('facebook.com', 'www.facebook.com', 'instagram.com', 'www.instagram.com'):
            return lead
        client = build_opener(SameHostRedirect(host))
        queue = [url]
        seen = set()
        found = {}
        while queue and len(seen) < 3:
            page = queue.pop(0)
            if page in seen:
                continue
            public_url(page, host)
            seen.add(page)
            req = Request(page, headers={'User-Agent': 'MusteriAvcisiAI/0.1 contact research'})
            with client.open(req, timeout=8) as response:
                public_url(response.geturl(), host)
                if 'html' not in response.headers.get('Content-Type', '').lower():
                    continue
                raw = response.read(500001)
                if len(raw) > 500000:
                    continue
                parser = Contacts()
                parser.feed(raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace'))
            for email in parser.candidates():
                found[email] = page
            for href in parser.links:
                candidate = urljoin(page, href)
                if urlsplit(candidate).hostname == host and candidate not in seen:
                    queue.append(candidate)
        # A unique address published by the recorded business site is required.
        if len(found) == 1:
            email, source = next(iter(found.items()))
            return {**lead, 'email': email, 'email_source': source}
    except Exception:
        # Research failure must never invent an address or expose private URLs.
        pass
    return lead
