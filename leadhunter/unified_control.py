"""Read-only federated control plane for the existing Müşteri Avcısı ecosystem.

No database copying, no customer messages, no SMTP, no review publishing.
A healthy HTTP endpoint is NOT evidence of CRM authorization or Google OAuth.
Source-of-truth ownership stays with the current production applications:
* Müşteri Avcısı: prospect + mail consent/claim/reply ledger
* İşletmePilot: authorized site/SSL monitors + existing CRM archive
* YorumPilot: Google location/review cache + reply draft state
"""
import json
from urllib.request import Request, urlopen
from urllib.parse import urlsplit

SERVICES = {
    "isletmepilot": {
        "url": "https://sitenobet-api-free.onrender.com/health",
        "owner": "site-nobet-ai",
    },
    "yorumpilot": {
        "url": "https://yorumpilot-api.onrender.com/healthz",
        "owner": "yorum-pilot.ai",
    },
}


def _failure_class(code):
    if code in (400, 401, 403, 404, 429):
        return "http_" + str(code)
    if 500 <= code <= 599:
        return "http_5xx"
    return "http_other"


def probe_detail(name, opener=urlopen, sleeper=None):
    """Three read-only GET attempts max; 5xx/network only, exponential backoff."""
    from urllib.error import HTTPError, URLError
    from time import sleep
    if sleeper is None:
        sleeper = sleep
    url = SERVICES[name]["url"]
    request = Request(url, headers={"User-Agent": "MusteriAvcisi-HealthCheck/1"},
                      method="GET")
    for attempt in range(3):
        retry = False
        reason = "unverified"
        try:
            with opener(request, timeout=5) as response:
                if response.geturl() != url:
                    return "unverified", "redirect"
                code = response.status
                if code == 200:
                    content = response.read(2049)
                    if len(content) > 2048:
                        return "unverified", "oversize"
                    try:
                        parsed = json.loads(content)
                    except (ValueError, TypeError):
                        return "unverified", "invalid_json"
                    if not isinstance(parsed, dict) or parsed.get("status") != "ok":
                        return "unverified", "invalid_health"
                    if name == "isletmepilot" and parsed.get("database") != "ok":
                        return "unverified", "database_unverified"
                    # HTTP readiness is not CRM or OAuth business authorization.
                    return "http_200", "ok"
                reason = _failure_class(code)
                retry = code >= 500
        except HTTPError as exc:
            reason = _failure_class(exc.code)
            retry = exc.code >= 500
        except (URLError, OSError, TimeoutError):
            reason = "network"
            retry = True
        if not retry or attempt == 2:
            return "unverified", reason
        sleeper(0.2 * (2 ** attempt))
    return "unverified", "unverified"


def probe(name, opener=urlopen):
    """Compatibility: only confirmed 200 + healthy JSON can be reported up."""
    return probe_detail(name, opener=opener)[0]


def snapshot(opener=urlopen):
    # Explicitly do not inspect or copy target CRM/review rows.
    return {name: probe(name, opener) for name in SERVICES}


def safe_report(states):
    # Stable label-only summary, no URLs, credentials, PII or response bodies.
    return ("İşletmePilot HTTP: " + states["isletmepilot"] +
            " | YorumPilot HTTP: " + states["yorumpilot"] +
            " | OAuth/CRM yetkili kabulü: ayrıca doğrulanmadı")


def run(opener=urlopen):
    details = {name: probe_detail(name, opener=opener) for name in SERVICES}
    result = {name: item[0] for name, item in details.items()}
    # Restricted categories only. No URLs, private response bodies or credentials.
    failures = " | ".join(name + "=" + item[1] for name, item in details.items())
    print("CONTROL_CENTER: " + safe_report(result) + "; diagnosis: " + failures +
          "; smtp_sent=0; google_replies_published=0")
    return result


if __name__ == "__main__":
    run()
