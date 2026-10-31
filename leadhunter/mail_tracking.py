"""Safe, free contact preflight and conservative business identity matching.

MX proves only that a domain advertises a mail route; it NEVER proves an inbox
exists or that a business authorized email. No SMTP verification is performed.
"""
import re
import unicodedata
from urllib.parse import urlsplit

from .outreach import valid_recipient

GENERIC_HOSTS = {
    "facebook.com", "instagram.com", "tiktok.com", "linktr.ee",
    "wa.me", "whatsapp.com", "maps.google.com",
}


def normalized_email(value):
    return str(value or "").strip().casefold()


def identity_keys(lead):
    """Strong business matches only; name alone must never block another shop."""
    keys = set()
    if not isinstance(lead, dict):
        return keys
    website = str(lead.get("website") or "").strip()
    if website:
        try:
            host = (urlsplit(website if "://" in website else "https://" + website).hostname or "").lower()
            host = host.removeprefix("www.")
            if host and "." in host and host not in GENERIC_HOSTS and not host.endswith(
                    (".facebook.com", ".instagram.com", ".google.com")):
                keys.add("site:" + host)
        except ValueError:
            pass
    phone = re.sub(r"\D", "", str(lead.get("phone") or ""))
    if 10 <= len(phone) <= 15:
        keys.add("phone:" + phone[-10:])
    name = _normalize_text(lead.get("name"))
    address = _normalize_text(lead.get("address"))
    if len(name) >= 4 and len(address) >= 8:
        keys.add("place:" + name + "|" + address)
    return keys


def _normalize_text(text):
    value = unicodedata.normalize("NFKD", str(text or "").casefold())
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.findall(r"\w+", value))


def already_contacted(candidate, prior):
    """Private immutable accepted/sending/uncertain history, incl. older records."""
    if not isinstance(prior, dict):
        return False
    current = normalized_email(candidate.get("email"))
    old_mail = prior.get("_auto_mail") or {}
    owner_mail = prior.get("_mail") or {}
    protected = (
        old_mail.get("state") in ("sending", "accepted", "uncertain")
        or owner_mail.get("state") in ("sending", "accepted", "uncertain")
    )
    if not protected:
        return False
    for record in (old_mail, owner_mail):
        previous = normalized_email(record.get("recipient"))
        if current and previous and current == previous:
            return True
    return bool(identity_keys(candidate) & identity_keys(prior))


def mx_status(domain, resolver=None):
    """Free DNS MX preflight; no recipient verification or connection to SMTP."""
    if resolver is None:
        try:
            import dns.resolver
        except ImportError:
            return "unchecked"
        resolver = dns.resolver.resolve
    try:
        answers = resolver(domain, "MX", lifetime=4)
        hosts = [str(getattr(item, "exchange", "")).strip() for item in answers]
        if not hosts or all(host == "." for host in hosts):
            return "no_mx"
        return "mx_present"
    except Exception:
        # Missing record, DNS errors and timeouts all fail closed for a send.
        return "unchecked"


def assess_contact(lead, discover=None, resolver=None):
    """Return a new lead for owner display/private storage, never fake an email."""
    value = dict(lead)
    email = normalized_email(value.get("email"))
    if not valid_recipient(email) and discover is not None and value.get("website"):
        value = discover(value)
        email = normalized_email(value.get("email"))
    if not email:
        status = "not_found"
    elif not valid_recipient(email):
        status = "invalid"
    else:
        if not value.get("email_source"):
            # A supplied OSM business contact tag is public source evidence,
            # not proof of mailbox ownership or permission to contact.
            value["email_source"] = "OSM business contact tag"
        status = mx_status(email.rsplit("@", 1)[-1], resolver=resolver)
    value["email_check"] = status
    return value


EMAIL_LABELS = {
    "not_found": "E-posta bulunamadı",
    "invalid": "E-posta biçimi geçersiz",
    "no_mx": "E-posta alanında MX yok; gönderim için uygun değil",
    "unchecked": "E-posta/MX doğrulanamadı; otomatik gönderim kapalı",
    "mx_present": "Adres biçimi ve MX var; posta kutusu doğrulanmadı",
}
