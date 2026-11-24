"""Evidence-backed commercial scoring and service matching.

Missing evidence remains unknown. Existing OSM completeness score is kept
separate as `research_score`; it is never treated as a commercial score.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

WEIGHTS = {
    "service_need": 30,
    "contact_accuracy": 20,
    "service_fit": 20,
    "commercial_potential": 15,
    "digital_gap": 10,
    "data_freshness": 5,
}


def _valid_evidence(component, now):
    if not isinstance(component, dict):
        return False
    value = component.get("value")
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not 0 <= value <= 100):
        return False
    reference = component.get("evidence_ref")
    if not isinstance(reference, str) or len(reference) < 8:
        return False
    parsed = urlsplit(reference)
    if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.username or parsed.password:
        return False
    try:
        verified = datetime.fromisoformat(
            str(component.get("verified_at") or "").replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return False
    if verified.tzinfo is None:
        return False
    age = now - verified.astimezone(timezone.utc)
    return timedelta(0) <= age <= timedelta(days=90)


def score_prospect(lead, now=None):
    """Return a score interval and band; do not fill missing components with 0.

    A point score is emitted only with evidence for all 100 weight points.
    With partial evidence, lower/upper bounds make uncertainty visible.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Scoring clock must be timezone-aware")
    qualification = lead.get("qualification") if isinstance(lead, dict) else None
    components = (qualification.get("commercial_components")
                  if isinstance(qualification, dict) else None)
    components = components if isinstance(components, dict) else {}
    observed_weighted = 0.0
    observed_weight = 0
    for name, weight in WEIGHTS.items():
        component = components.get(name)
        if _valid_evidence(component, now):
            observed_weighted += weight * float(component["value"]) / 100
            observed_weight += weight
    lower = round(observed_weighted)
    upper = round(observed_weighted + (100 - observed_weight))
    if lower >= 80:
        band = "high"
    elif upper < 60:
        band = "low"
    else:
        band = "review"
    complete = observed_weight == 100
    return {
        "score": lower if complete else None,
        "score_min": lower,
        "score_max": upper,
        "coverage": observed_weight,
        "band": (band if complete or band == "high" else
                 "low_unverified_range" if band == "low" else "review"),
        "components": {
            name: (components[name].get("value") if name in components
                   and _valid_evidence(components[name], now) else None)
            for name in WEIGHTS
        },
    }


def _fresh_signal(qualification, signal, now):
    if qualification.get(signal) is not True:
        return False
    evidence = qualification.get(f"{signal}_evidence_url")
    parsed = urlsplit(str(evidence or ""))
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username or parsed.password:
        return False
    try:
        verified = datetime.fromisoformat(
            str(qualification.get(f"{signal}_verified_at") or "").replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return False
    if verified.tzinfo is None:
        return False
    age = now - verified.astimezone(timezone.utc)
    return timedelta(0) <= age <= timedelta(days=30)


def match_service(lead, now=None):
    """Match only confirmed signals to the user's three service categories."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Matching clock must be timezone-aware")
    q = lead.get("qualification") if isinstance(lead, dict) else None
    q = q if isinstance(q, dict) else {}
    if _fresh_signal(q, "whatsapp_automation_need_verified", now):
        return {"category": 2, "service": "WhatsApp müşteri desteği otomasyonu",
                "evidence_status": "verified"}
    if _fresh_signal(q, "website_absence_verified", now):
        return {"category": 1, "service": "Profesyonel web sitesi",
                "evidence_status": "verified"}
    if (all(_fresh_signal(q, signal, now) for signal in (
            "website_presence_verified", "whatsapp_presence_verified",
            "automation_need_verified"))
            and score_prospect(lead, now).get("score") is not None
            and score_prospect(lead, now)["score"] >= 75):
        return {"category": 3, "service": "AI, CRM ve iş süreçleri otomasyonu",
                "evidence_status": "verified"}
    return {"category": None, "service": None,
            "evidence_status": "unknown_requires_verification"}
