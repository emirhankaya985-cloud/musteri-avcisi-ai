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


def probe(name, opener=urlopen):
    """GET fixed public health routes only. No tokens, data writes, redirects or URL input."""
    entry = SERVICES[name]
    url = entry["url"]
    request = Request(url, headers={"User-Agent": "MusteriAvcisi-HealthCheck/1"},
                      method="GET")
    try:
        with opener(request, timeout=6) as response:
            if response.geturl() != url or response.status != 200:
                return "unverified"
            content = response.read(2049)
            if len(content) > 2048:
                return "unverified"
            parsed = json.loads(content)
            if parsed.get("status") != "ok":
                return "unverified"
            if name == "isletmepilot" and parsed.get("database") != "ok":
                return "unverified"
            # Never infer OAuth, review sync, customer ownership, or business
            # authorization from one successful unauthenticated HTTP GET.
            return "http_200"
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return "unverified"


def snapshot(opener=urlopen):
    # Explicitly do not inspect or copy target CRM/review rows.
    return {name: probe(name, opener) for name in SERVICES}


def safe_report(states):
    # Stable label-only summary, no URLs, credentials, PII or response bodies.
    return ("İşletmePilot HTTP: " + states["isletmepilot"] +
            " | YorumPilot HTTP: " + states["yorumpilot"] +
            " | OAuth/CRM yetkili kabulü: ayrıca doğrulanmadı")


def run(opener=urlopen):
    result = snapshot(opener)
    print("CONTROL_CENTER: " + safe_report(result) + "; smtp_sent=0; google_replies_published=0")
    return result


if __name__ == "__main__":
    run()
