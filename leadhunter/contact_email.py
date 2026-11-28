"""Bounded contact discovery on the business's recorded public website.

Never guess addresses. Reject ambiguous contacts, private networks and redirects
outside the recorded website host. Results belong only in private mail storage.
"""
import ipaddress
import re
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit, unquote
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.robotparser import RobotFileParser
from .outreach import valid_recipient

MAX_PAGES = 8
MAX_PAGE_BYTES = 300_000
PAGE_TIMEOUT = 5
USER_AGENT = 'MusteriAvcisiAI/0.1 contact research'
CONTACT_TERMS = ('contact', 'iletisim', 'iletişim', 'hakkimizda', 'hakkımızda',
                 'about', 'kurumsal', 'bize-ulasin', 'bize-ulaşın', 'contact-us')
COMMON_CONTACT_PATHS = ('/iletisim', '/iletisim/', '/contact', '/contact/',
                        '/contact-us', '/contact-us/', '/hakkimizda', '/about')


def _canonical_host(host):
    return str(host or '').casefold().removeprefix('www.')


def _same_site(host, site_host):
    return bool(host and site_host and _canonical_host(host) == _canonical_host(site_host))


def _email_text_variants(value):
    """Normalize common, explicitly published anti-spam spellings."""
    yield value
    normalized = value
    normalized = re.sub(r'\s*(?:\[at\]|\(at\)|\{at\}|\bat\b)\s*', '@', normalized, flags=re.I)
    normalized = re.sub(r'\s*(?:\[dot\]|\(dot\)|\{dot\}|\bdot\b)\s*', '.', normalized, flags=re.I)
    if normalized != value:
        yield normalized


def _email_rank(email):
    local = email.split('@', 1)[0].casefold().split('+', 1)[0]
    role = re.split(r'[._-]', local, maxsplit=1)[0]
    priorities = {'info': 0, 'iletisim': 1, 'contact': 2, 'satis': 3,
                  'sales': 4, 'hello': 5, 'office': 6, 'destek': 7,
                  'support': 8}
    return priorities.get(role, 100)


def _choose_email(found):
    if len(found) == 1:
        return next(iter(found.items()))
    ranked = sorted((_email_rank(email), email, source)
                    for email, source in found.items())
    if not ranked or ranked[0][0] == 100:
        return None
    best = [row for row in ranked if row[0] == ranked[0][0]]
    return (best[0][1], best[0][2]) if len(best) == 1 else None


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
        attributes = dict(attrs)
        href = attributes.get('href', '')
        if href.lower().startswith('mailto:'):
            for variant in _email_text_variants(unquote(href[7:].split('?')[0]).strip().lower()):
                self.emails.update(re.findall(
                    r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
                    variant))
        elif any(term in (href + ' ' + str(attributes.get('title', ''))).casefold()
                 for term in CONTACT_TERMS):
            self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def candidates(self):
        visible = ' '.join(self.parts)
        joined = ''.join(self.parts)
        for text in (visible, joined):
            for variant in _email_text_variants(text):
                self.emails.update(re.findall(
                    r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
                    variant))
        return {x.strip().lower() for x in self.emails
                if valid_recipient(x.strip().lower())}


def public_url(url, host, resolver=socket.getaddrinfo):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not _same_site(parsed.hostname, host)
            or parsed.username or parsed.password or parsed.port not in (None, 80, 443)):
        raise ValueError('Unsupported business website URL')
    addresses = resolver(host, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError('Website must resolve to a public network')
    return url


def _read_robots_policy(client, base_url, host):
    """Read the same-host robots policy once; ``None`` means fail closed."""
    parsed = urlsplit(base_url)
    robots_url = f'{parsed.scheme}://{parsed.netloc}/robots.txt'
    public_url(robots_url, host)
    request = Request(robots_url, headers={'User-Agent': USER_AGENT})
    parser = RobotFileParser(robots_url)
    try:
        with client.open(request, timeout=PAGE_TIMEOUT) as response:
            public_url(response.geturl(), host)
            raw = response.read(MAX_PAGE_BYTES + 1)
            if len(raw) > MAX_PAGE_BYTES:
                return None
            charset = response.headers.get_content_charset() or 'utf-8'
            parser.parse(raw.decode(charset, errors='replace').splitlines())
    except HTTPError as exc:
        if exc.code in (404, 410):
            parser.parse([])
        else:
            return None
    except Exception:
        return None
    return parser


class SameHostRedirect(HTTPRedirectHandler):
    def __init__(self, host):
        self.host = host

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl, self.host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def discover_email(lead):
    if (valid_recipient(str(lead.get('email') or '').strip().lower())
            and not lead.get('_force_email_research')):
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
        path_candidates = [urljoin(url, path) for path in COMMON_CONTACT_PATHS]
        # Read robots.txt before any business page. If its policy cannot be
        # fetched safely, stop instead of bypassing a possibly restrictive rule.
        robots_policy = _read_robots_policy(client, url, host)
        if robots_policy is None:
            return lead
        while queue and len(seen) < MAX_PAGES:
            page = queue.pop(0)
            if page in seen:
                continue
            seen.add(page)
            try:
                public_url(page, host)
                try:
                    allowed = robots_policy.can_fetch(USER_AGENT, page)
                except Exception:
                    allowed = False
                if not allowed:
                    continue
                req = Request(page, headers={'User-Agent': USER_AGENT})
                with client.open(req, timeout=8) as response:
                    public_url(response.geturl(), host)
                    if 'html' not in response.headers.get('Content-Type', '').lower():
                        continue
                    raw = response.read(MAX_PAGE_BYTES + 1)
                    if len(raw) > MAX_PAGE_BYTES:
                        continue
                    parser = Contacts()
                    parser.feed(raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace'))
            except Exception:
                # A broken contact/about subpage must not discard public
                # evidence already found on the business home page. The
                # failed URL remains same-host checked, and other bounded
                # candidates may still be inspected.
                continue
            for email in parser.candidates():
                found[email] = page
            links = []
            for href in parser.links:
                candidate = urljoin(page, href)
                if _same_site(urlsplit(candidate).hostname, host) and candidate not in seen:
                    links.append(candidate)
            links.sort(key=lambda candidate: (
                not any(term in candidate.casefold() for term in CONTACT_TERMS), candidate))
            queue.extend(candidate for candidate in links if candidate not in queue)
            if not queue:
                selected_now = _choose_email(found)
                if selected_now and _email_rank(selected_now[0]) == 0:
                    break
                queue.extend(candidate for candidate in path_candidates
                             if candidate not in seen and candidate not in queue)
        # Prefer a single publicly listed role address when a site also lists
        # unrelated departments. Never construct an address from a domain.
        selected = _choose_email(found)
        if selected:
            email, source = selected
            source_host = urlsplit(source).hostname
            return {
                **lead,
                'email': email,
                'email_source': source,
                'email_source_host': _canonical_host(source_host),
                'email_source_type': 'business_website_public_contact',
                'email_retrieved_at': datetime.now(timezone.utc).isoformat(),
                'email_domain': email.rsplit('@', 1)[1].casefold(),
            }
    except Exception:
        # Research failure must never invent an address or expose private URLs.
        pass
    return lead

