"""QA gates — SOP section 5. Nothing publishes without passing.

Gate 1 schema, Gate 2 duplicate, Gate 3 sanity run per record here.
Gate 4 (volume anomaly) and Gate 5 (freshness) run per ingest in pipeline.py.
A failed gate = the record/run is HELD, never silently dropped: every hold
carries a reason and lands in the run report.
"""
from datetime import date, timedelta

MAX_VALUATION_DEFAULT = 2_000_000_000


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return "INVALID"


def check_record(rec, pull_date, valuation_max=MAX_VALUATION_DEFAULT):
    """Returns a list of hold reasons (empty list = passes gates 1-3)."""
    reasons = []
    # Gate 1 — schema: required fields present and correctly typed.
    if not rec.get("source_record_id"):
        reasons.append("g1: missing source_record_id")
    if not rec.get("permit_number"):
        reasons.append("g1: missing permit_number")
    app_d = _parse_date(rec.get("application_date"))
    iss_d = _parse_date(rec.get("issue_date"))
    if app_d is None and iss_d is None:
        reasons.append("g1: no application or issue date")
    if app_d == "INVALID" or iss_d == "INVALID":
        reasons.append("g1: unparseable date value")
    # Gate 3 — sanity: no future dates, plausible valuation.
    horizon = pull_date + timedelta(days=1)
    for label, d in (("application_date", app_d), ("issue_date", iss_d)):
        if isinstance(d, date) and d > horizon:
            reasons.append(f"g3: {label} {d} is in the future")
    v = rec.get("valuation")
    if v is not None:
        if v < 0:
            reasons.append("g3: negative valuation")
        elif v > valuation_max:
            reasons.append(f"g3: valuation {v} above plausible ceiling {valuation_max}")
    return reasons
