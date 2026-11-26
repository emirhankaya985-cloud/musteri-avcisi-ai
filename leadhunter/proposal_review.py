"""Evidence-backed proposal drafts for owner review; never sends email.

This is a presentation layer over the existing evidence scorer. Public contact
details or OSM fields alone cannot turn a research idea into a verified need.
"""
from __future__ import annotations

from .commercial_scoring import match_service
from .core import recommend


def build_proposal_review(lead, *, now=None):
    """Build a structured, unsent proposal and show its evidence boundary.

    ``ready_for_owner_review`` means the requested service need passed the
    scorer's fresh-evidence checks. It is not marketing consent or send
    authorization. Without that evidence the generated text remains a research
    question, and the service field stays unknown.
    """
    match = match_service(lead, now=now)
    suggestion = recommend(lead)
    verified = match.get("evidence_status") == "verified"
    evidence = [
        {
            "url": item["evidence_ref"],
            "source_type": item["source_type"],
            "verified_at": item["verified_at"],
            "age_days": item["age_days"],
            "confidence": item["confidence"],
            "rationale": item["rationale"],
        }
        for item in match.get("evidence", [])
    ]
    name = " ".join(str(lead.get("name") or "işletmeniz").split())[:100]
    if verified:
        draft = (f"Araştırmada {match['service']} konusu için güncel kaynak kanıtı gördüm. "
                 "İşletmenize uyup uymadığını birlikte netleştirebiliriz; ilginizi çekerse "
                 "kısa ve size özel bir örnek hazırlayabilirim.")
    else:
        draft = ("Web siteniz ve müşteri iletişim süreçleriniz hakkında kısa bir bilgi "
                 "rica edebilir miyim? Uygunsa, önce ihtiyacı doğrulayıp ardından size "
                 "uygun bir örnek hazırlayabilirim.")
    return {
        "status": "ready_for_owner_review" if verified else "research_required",
        "claim_level": "verified_need" if verified else "exploratory_question",
        "service": match.get("service") if verified else None,
        "evidence_status": match.get("evidence_status", "unknown_requires_verification"),
        "evidence": evidence,
        "recommendation": suggestion["idea"],
        "recommendation_is_hypothesis": not verified,
        "draft": draft,
        "human_review_required": True,
        "marketing_permission": "not_evaluated_here",
        "email_send_authorized": False,
    }
