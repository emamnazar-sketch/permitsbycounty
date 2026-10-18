"""Normalizers: raw source rows -> the SOP section 4 standard schema.

Privacy rule (SOP section 3 rule 1) is enforced HERE, at the only door data
enters through: person-name fields are never copied. Chicago: only contacts
whose published role type contains 'CONTRACTOR' (a business role) are taken.
"""
from trades import classify_trade


def _clean(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _date(v):
    """Socrata calendar_date arrives as '2026-10-01T00:00:00.000' (or a date)."""
    s = _clean(v)
    if not s:
        return None
    return s[:10]


def _num(v):
    try:
        return float(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _title(s):
    return s.title() if s else s


def normalize_chicago(raw, reg):
    """One raw Chicago row -> standard record dict (or None if unusable id)."""
    sid = _clean(raw.get("id"))
    if not sid:
        return None
    # Address: Chicago publishes number/direction/name; name already carries suffix.
    parts = [_clean(raw.get("street_number")), _clean(raw.get("street_direction")),
             _clean(raw.get("street_name"))]
    address = " ".join(_title(p) for p in parts if p) or None
    # Contractor: first published contact whose role is a contractor role.
    contractor = None
    for i in range(1, 16):
        ctype = (_clean(raw.get(f"contact_{i}_type")) or "").upper()
        if "CONTRACTOR" in ctype:
            contractor = _clean(raw.get(f"contact_{i}_name"))
            if contractor:
                contractor = _title(contractor) if contractor.isupper() else contractor
                break
    status_src = _clean(raw.get("permit_status"))
    status = reg["status_map"].get(status_src.upper(), "not-stated") if status_src else "not-stated"
    return {
        "source_record_id": sid,
        "permit_number": _clean(raw.get("permit_")),
        "address": address,
        "city": "Chicago",
        "county": reg["county"],
        "state": reg["state"],
        "zip": None,  # Chicago dataset does not publish the property ZIP
        "permit_type": _clean(raw.get("permit_type")),
        "trade": classify_trade(raw.get("permit_type"), raw.get("work_type"),
                                raw.get("work_description")),
        "category": None,  # source publishes no residential/commercial flag; honest NULL
        "project_description": _clean(raw.get("work_description")),
        "valuation": _num(raw.get("reported_cost")),
        "status": status,
        "status_source": status_src,
        "application_date": _date(raw.get("application_start_date")),
        "issue_date": _date(raw.get("issue_date")),
        "source_updated_date": None,
        "contractor_name": contractor,
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


def normalize_austin(raw, reg):
    """One raw Austin row -> standard record dict (or None if unusable id).

    Uniqueness: source_record_id = permit_number — verified unique in the
    trailing-12-month window by the 2026-10-17 audit brief (55,575 distinct
    permit_number = 55,575 rows) and re-checked at build time by the
    pipeline's in-batch duplicate gate; never assumed silently.
    Privacy: the pull is column-restricted by the registry pull_select —
    contractor_full_name and applicant_full_name are never requested from
    the API at all, so they cannot reach this function. The only contractor
    field carried is contractor_company_name (a business name).
    """
    sid = _clean(raw.get("permit_number"))
    if not sid:
        return None
    address = _clean(raw.get("original_address1"))
    if address and address.isupper():
        address = _title(address)
    city = _clean(raw.get("original_city"))
    if city and city.isupper():
        city = _title(city)
    if not city:
        city = "Austin"  # issuing jurisdiction's seat; mirrors Chicago's fixed city
    zipc = _clean(raw.get("original_zip"))
    if zipc and zipc.endswith(".0"):
        zipc = zipc[:-2]
    contractor = _clean(raw.get("contractor_company_name"))
    if contractor and contractor.isupper():
        contractor = _title(contractor)
    status_src = _clean(raw.get("status_current"))
    status = reg["status_map"].get(status_src.upper(), "not-stated") if status_src else "not-stated"
    cat_src = (_clean(raw.get("permit_class_mapped")) or "").lower()
    category = cat_src if cat_src in ("residential", "commercial") else None
    pt = _clean(raw.get("permit_type_desc"))
    wc = _clean(raw.get("work_class"))
    trade = classify_trade(pt, wc, raw.get("description"))
    # Austin Building Permits: work_class "New" on a building permit is new
    # construction (Austin publishes no separate permit type for it). Only
    # applied when the generic classifier found nothing more specific.
    if pt == "Building Permit" and (wc or "").lower() == "new" and trade == "general":
        trade = "new-construction"
    return {
        "source_record_id": sid,
        "permit_number": sid,
        "address": address,
        "city": city,
        "county": reg["county"],
        "state": reg["state"],
        "zip": zipc,
        "permit_type": pt,
        "trade": trade,
        "category": category,
        "project_description": _clean(raw.get("description")),
        "valuation": _num(raw.get("total_job_valuation")),
        "status": status,
        "status_source": status_src,
        "application_date": _date(raw.get("applieddate")),
        "issue_date": _date(raw.get("issue_date")),
        "source_updated_date": _date(raw.get("statusdate")),
        "contractor_name": contractor,
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


NORMALIZERS = {"chicago-cook-il": normalize_chicago,
               "austin-travis-tx": normalize_austin}
