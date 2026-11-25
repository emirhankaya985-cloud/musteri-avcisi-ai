"""Explainable duplicate-candidate strength, never an auto-merge decision."""

REASON_WEIGHTS = {
    "same_first_party_domain": 55,
    "same_phone": 55,
    "same_name_address": 65,
    "same_name_category_review": 20,
}
LOCATION_BANDS = frozenset(("co_located", "nearby", "separated", "unverified"))


def score_pair(evidence, location_band=None):
    """Return (0..95 heuristic strength, JSON-safe explanation).

    The score is intentionally not a probability, legal identity determination,
    or merge permission. It summarizes the strongest observed identity signal
    and adds small support from independent signals. Branch distance is shown
    as a separate risk cue; proximity alone never raises the score.
    """
    reasons = tuple(sorted(set(evidence or ())))
    unknown = set(reasons) - REASON_WEIGHTS.keys()
    if unknown:
        raise ValueError("Unknown duplicate evidence reason")
    if location_band is not None and location_band not in LOCATION_BANDS:
        raise ValueError("Unknown duplicate location band")

    weights = {reason: REASON_WEIGHTS[reason] for reason in reasons}
    robust = [reason for reason in reasons if reason != "same_name_category_review"]
    # Identical name/category is a subset of the address match, so it never
    # counts as a second independent signal alongside that stronger reason.
    independent = len(robust)
    base = max(weights.values(), default=0)
    score = min(95, base + max(0, independent - 1) * 15)

    if location_band == "co_located":
        branch_risk = "low_but_not_excluded"
    elif location_band in ("nearby", "separated"):
        branch_risk = "possible_different_branch"
    else:
        branch_risk = "unknown"

    detail = {
        "method": "heuristic-v1",
        "signal_weights": weights,
        "independent_signal_count": independent,
        "location_band": location_band or "unknown",
        "branch_risk": branch_risk,
        "interpretation": "candidate evidence strength only; manual identity review required",
        "automatic_merge_allowed": False,
    }
    return score, detail
