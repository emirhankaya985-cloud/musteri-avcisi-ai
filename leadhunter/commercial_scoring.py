"""Evidence-backed commercial scoring and service matching.

OSM record completeness is a research aid, never a commercial score.  A
component contributes only when its value, source, observation, timestamp,
confidence, and rationale are all recorded and fresh.  Rejected evidence is
reported as unknown with a reason; it is not silently converted to zero.
"""
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlsplit

WEIGHTS = {
    "service_need": 30,
    "contact_accuracy": 20,
    "service_fit": 20,
    "commercial_potential": 15,
    "digital_gap": 10,
    "data_freshness": 5,
}

MAX_EVIDENCE_AGE = timedelta(days=90)
MAX_SIGNAL_AGE = timedelta(days=30)
ALLOWED_SOURCE_TYPES = frozenset({
    "business_first_party",
    "official_registry",
    "authorized_directory",
    "documented_human_review",
})


def _clock(now):
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Scoring clock must be timezone-aware")
    return now.astimezone(timezone.utc)


def _parse_timestamp(value):
    try:
        stamp = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError, OverflowError):
        return None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return None
    return stamp.astimezone(timezone.utc)


def _http_url(value):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlsplit(value.strip())
        # Requiring a DNS-style host and forbidding credentials avoids treating
        # opaque schemes, local paths, and embedded secrets as source evidence.
        return (parsed.scheme.lower() in ("http", "https")
                and bool(parsed.hostname) and parsed.username is None
                and parsed.password is None and parsed.port != 0)
    except ValueError:
        return False


def _bounded_confidence(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        value = float(value)
    except (ValueError, OverflowError):
        return False
    return math.isfinite(value) and 0 < value <= 100


def _score_value(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (ValueError, OverflowError):
        return None
    return value if math.isfinite(value) and 0 <= value <= 100 else None


def _evidence_state(component, now, max_age=MAX_EVIDENCE_AGE):
    """Validate a component and return an auditable status/details object."""
    if not isinstance(component, dict):
        return {"status": "unknown", "reason": "evidence_not_recorded"}

    value = _score_value(component.get("value"))
    if value is None:
        return {"status": "excluded", "reason": "invalid_component_value"}
    source_ref = component.get("evidence_ref")
    if not _http_url(source_ref):
        return {"status": "excluded", "reason": "invalid_source_reference"}
    source_type = component.get("source_type")
    if not isinstance(source_type, str) or source_type not in ALLOWED_SOURCE_TYPES:
        return {"status": "excluded", "reason": "source_type_not_verified"}
    confidence = component.get("confidence")
    if not _bounded_confidence(confidence):
        return {"status": "excluded", "reason": "confidence_not_recorded"}
    rationale = component.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale.strip()) > 500:
        return {"status": "excluded", "reason": "explanation_not_recorded"}
    verified = _parse_timestamp(component.get("verified_at"))
    if verified is None:
        return {"status": "excluded", "reason": "verification_time_invalid"}
    age = now - verified
    if age < timedelta(0):
        return {"status": "excluded", "reason": "verification_time_in_future"}
    if age > max_age:
        return {"status": "excluded", "reason": "evidence_stale"}

    return {
        "status": "counted",
        "reason": None,
        "value": float(value),
        "evidence_ref": source_ref.strip(),
        "source_type": source_type,
        "verified_at": verified.isoformat(),
        "age_days": round(age.total_seconds() / 86400, 3),
        "confidence": float(confidence),
        "rationale": rationale.strip(),
    }


def score_prospect(lead, now=None):
    """Return an explainable score interval without imputing missing values.

    A point score is available only when all six weighted components have
    valid fresh evidence.  For partial inputs, ``score_min`` and ``score_max``
    are mathematical bounds, not an observed score; ``score`` stays ``None``.
    Confidence is retained per component and is not mislabeled as a probability.
    """
    now = _clock(now)
    qualification = lead.get("qualification") if isinstance(lead, dict) else None
    raw_components = (qualification.get("commercial_components")
                      if isinstance(qualification, dict) else None)
    raw_components = raw_components if isinstance(raw_components, dict) else {}

    weighted_points = 0.0
    observed_weight = 0
    details = {}
    legacy_values = {}
    for name, weight in WEIGHTS.items():
        state = _evidence_state(raw_components.get(name), now)
        state["weight"] = weight
        if state["status"] == "counted":
            points = weight * state["value"] / 100
            weighted_points += points
            observed_weight += weight
            state["weighted_points"] = round(points, 3)
            legacy_values[name] = state["value"]
        else:
            state["weighted_points"] = None
            legacy_values[name] = None
        details[name] = state

    missing_weight = 100 - observed_weight
    complete = observed_weight == 100
    score = round(weighted_points) if complete else None
    lower = round(weighted_points)
    upper = round(weighted_points + missing_weight)
    if complete:
        band = "high" if score >= 80 else "review" if score >= 60 else "low"
    elif lower >= 80:
        # A high lower bound means the unknown components cannot drop the
        # minimum below 80.  Do not call this a complete point score.
        band = "high_unverified_range"
    elif upper < 60:
        band = "low_unverified_range"
    else:
        band = "review"

    return {
        "score": score,
        "score_min": lower,
        "score_max": upper,
        "coverage": observed_weight,
        "band": band,
        "components": legacy_values,
        "component_evidence": details,
        "confidence_summary": {
            "status": "complete" if complete else "partial_or_missing",
            "weighted_mean": (round(sum(
                WEIGHTS[name] * details[name]["confidence"]
                for name in WEIGHTS if details[name]["status"] == "counted"
            ) / observed_weight, 1) if observed_weight else None),
            "coverage_weight": observed_weight,
            "interpretation": "Mean of recorded component confidence ratings; not a probability.",
        },
        "summary": ("Tam kanıtlı ağırlıklı ticari puan."
                    if complete else
                    f"Puan bilinmiyor; {observed_weight}/100 ağırlık kanıtlı. "
                    f"{lower}–{upper} yalnızca olası aralıktır."),
    }


def _fresh_signal(qualification, signal, now):
    """Return validated source evidence for a categorical qualification signal."""
    if qualification.get(signal) is not True:
        return None
    evidence_ref = qualification.get(f"{signal}_evidence_url")
    if not _http_url(evidence_ref):
        return None
    source_type = qualification.get(f"{signal}_source_type")
    if not isinstance(source_type, str) or source_type not in ALLOWED_SOURCE_TYPES:
        return None
    confidence = qualification.get(f"{signal}_confidence")
    if not _bounded_confidence(confidence):
        return None
    rationale = qualification.get(f"{signal}_rationale")
    if not isinstance(rationale, str) or not rationale.strip() or len(rationale.strip()) > 500:
        return None
    verified = _parse_timestamp(qualification.get(f"{signal}_verified_at"))
    if verified is None:
        return None
    age = now - verified
    if age < timedelta(0) or age > MAX_SIGNAL_AGE:
        return None
    return {
        "signal": signal,
        "evidence_ref": evidence_ref.strip(),
        "source_type": source_type,
        "verified_at": verified.isoformat(),
        "age_days": round(age.total_seconds() / 86400, 3),
        "confidence": float(confidence),
        "rationale": rationale.strip(),
    }


def _unknown_match():
    return {"category": None, "service": None,
            "evidence_status": "unknown_requires_verification", "evidence": []}


def match_service(lead, now=None):
    """Assign the requested service category only from fresh, explained facts."""
    now = _clock(now)
    q = lead.get("qualification") if isinstance(lead, dict) else None
    q = q if isinstance(q, dict) else {}
    category2 = _fresh_signal(q, "whatsapp_automation_need_verified", now)
    if category2:
        return {"category": 2, "service": "WhatsApp müşteri desteği otomasyonu",
                "evidence_status": "verified", "evidence": [category2]}
    category1 = _fresh_signal(q, "website_absence_verified", now)
    if category1:
        return {"category": 1, "service": "Profesyonel web sitesi",
                "evidence_status": "verified", "evidence": [category1]}
    category3_signals = [
        _fresh_signal(q, signal, now)
        for signal in ("website_presence_verified", "whatsapp_presence_verified",
                       "automation_need_verified")
    ]
    if all(category3_signals):
        score = score_prospect(lead, now)
        if score["score"] is not None and score["score"] >= 75:
            return {"category": 3, "service": "AI, CRM ve iş süreçleri otomasyonu",
                    "evidence_status": "verified", "evidence": category3_signals,
                    "commercial_score": score["score"]}
    return _unknown_match()
