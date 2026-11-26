"""Optional owner-only ntfy delivery for aggregate daily status messages.

No CRM rows, recipient addresses, or message bodies are included. A missing
topic disables this integration. A 2xx response means ntfy accepted a publish,
not that a phone or desktop actually displayed it.
"""
from __future__ import annotations

import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

_TOPIC = re.compile(r"[A-Za-z0-9_-]{1,128}\Z", re.ASCII)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _topic_url(value):
    if not isinstance(value, str) or len(value) > 512:
        return None
    try:
        parsed = urlsplit(value.strip())
        topic = parsed.path.strip("/")
        if (parsed.scheme != "https" or parsed.hostname != "ntfy.sh"
                or parsed.username or parsed.password or parsed.port not in (None, 443)
                or parsed.query or parsed.fragment or "/" in topic
                or not _TOPIC.fullmatch(topic)):
            return None
    except ValueError:
        return None
    return f"https://ntfy.sh/{topic}"


def send_daily(message, env, opener=None):
    """Publish one aggregate report; return a safe status without raising."""
    raw_url = env.get("NTFY_TOPIC_URL")
    if not raw_url:
        return "disabled"
    url = _topic_url(raw_url)
    if not url or not isinstance(message, str) or not message.strip():
        return "invalid_config"
    if len(message.encode("utf-8")) > 4096:
        return "message_too_large"
    headers = {
        "Title": "Müşteri Avcısı AI günlük raporu",
        "Priority": "default",
        "Content-Type": "text/plain; charset=utf-8",
    }
    token = env.get("NTFY_TOKEN")
    if token:
        if not isinstance(token, str) or len(token) > 2048 or "\r" in token or "\n" in token:
            return "invalid_config"
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=message.encode("utf-8"), headers=headers, method="POST")
    client = opener or build_opener(_NoRedirect())
    try:
        with client.open(request, timeout=10) as response:
            return "accepted" if 200 <= response.status < 300 else "rejected"
    except HTTPError as error:
        return "rejected" if error.code < 500 else "unavailable"
    except (URLError, TimeoutError, OSError):
        return "unavailable"
    except Exception:
        return "unavailable"
