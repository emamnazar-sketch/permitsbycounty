"""Normalizers: raw source rows -> the SOP section 4 standard schema.

Privacy rule (SOP section 3 rule 1) is enforced HERE, at the only door data
enters through: person-name fields are never copied. Chicago: only contacts
whose published role type contains 'CONTRACTOR' (a business role) are taken.
"""
import re

from trades import (classify_boston_trade, classify_br_trade,
                    classify_cincinnati_trade, classify_fort_worth_trade,
                    classify_philly_trade, classify_raleigh_trade,
                    classify_sa_trade, classify_trade, classify_nyc_trade,
                    classify_sf_trade, classify_seattle_trade)

# A real DOB job filing number: borough letter + 8 digits + filing iteration
# (measured: 125,096 of 125,097 distinct window values; the one exception is
# the feed's placeholder text — see normalize_nyc).
_JOB_NUMBER_RE = re.compile(r"^[A-Z]\d{8}-[A-Z]\d+$")


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


def normalize_sf(raw, reg):
    """One raw San Francisco row -> standard record dict (or None).

    Dedupe (registry dedupe_rule): the pull is restricted to the permit's
    primary-address record (primary_address_flag='Y'), so each permit_number
    arrives exactly once; source_record_id = record_id (the source's row id,
    unique per row). Privacy: this dataset publishes no contractor field and
    no applicant/owner person fields at all, and the pull is additionally
    column-restricted by the registry pull_select — contractor stays NULL,
    never inferred.
    Valuation (registry field_map): revised_cost when it is a real figure
    (> $1), else estimated_cost; $1 placeholders stay $1 as reported.
    """
    sid = _clean(raw.get("record_id"))
    if not sid:
        return None
    parts = [_clean(raw.get("street_number")), _clean(raw.get("street_number_suffix")),
             _clean(raw.get("street_name")), _clean(raw.get("street_suffix"))]
    address = " ".join(p for p in parts if p)
    if address and address.isupper():
        address = _title(address)
    address = address or None
    rev, est = _num(raw.get("revised_cost")), _num(raw.get("estimated_cost"))
    valuation = rev if (rev is not None and rev > 1) else est
    status_src = _clean(raw.get("status"))
    status = reg["status_map"].get(status_src.upper(), "not-stated") if status_src else "not-stated"
    definition = _clean(raw.get("permit_type_definition")) or _clean(raw.get("permit_type"))
    return {
        "source_record_id": sid,
        "permit_number": _clean(raw.get("permit_number")),
        "address": address,
        "city": "San Francisco",
        "county": reg["county"],
        "state": reg["state"],
        "zip": _clean(raw.get("zipcode")),
        "permit_type": definition,
        "trade": classify_sf_trade(definition, raw.get("description"),
                                   raw.get("reroof"), raw.get("fire_only_permit")),
        "category": None,  # source publishes no residential/commercial class; honest NULL
        "project_description": _clean(raw.get("description")),
        "valuation": valuation,
        "status": status,
        "status_source": status_src,
        "application_date": _date(raw.get("filed_date")),
        "issue_date": _date(raw.get("issued_date")),
        "source_updated_date": _date(raw.get("data_loaded_at")),
        "contractor_name": None,  # dataset publishes no contractor field (registry rule)
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


def normalize_seattle(raw, reg):
    """One raw Seattle row -> standard record dict (or None if unusable id).

    Identity (registry dedupe_rule): permitnum is unique — measured
    2026-10-18, window and all-time (6,348 = 6,348; 193,745 = 193,745) —
    so source_record_id = permitnum and no collapsing applies.
    Privacy: the dataset publishes no applicant/owner person-name fields
    at all (verified against the full 41-column schema), and the pull is
    additionally column-restricted by the registry pull_select. The only
    contractor field carried is contractorcompanyname (a business name).
    Valuation: estprojectcost is stored exactly as reported but is NOT
    published — SDCI stamps a development's full estimated cost onto each
    phase/sibling permit (registry field_map.valuation, measured 2026-10-18:
    duplicated values over $1M inject 38.5% excess into the raw sum), so
    King County runs counts-only, the Austin precedent.
    """
    sid = _clean(raw.get("permitnum"))
    if not sid:
        return None
    address = _clean(raw.get("originaladdress1"))
    if address and address.isupper():
        address = _title(address)
    city = _clean(raw.get("originalcity"))
    if city and city.isupper():
        city = _title(city)
    if not city:
        city = "Seattle"  # issuing jurisdiction's seat; mirrors Austin's default
    zipc = _clean(raw.get("originalzip"))
    if zipc and zipc.endswith(".0"):
        zipc = zipc[:-2]
    contractor = _clean(raw.get("contractorcompanyname"))
    if contractor and contractor.isupper():
        contractor = _title(contractor)
    status_src = _clean(raw.get("statuscurrent"))
    status = reg["status_map"].get(status_src.upper(), "not-stated") if status_src else "not-stated"
    cat_src = (_clean(raw.get("permitclassmapped")) or "").lower()
    category = cat_src if cat_src in ("residential", "non-residential") else None
    pt = _clean(raw.get("permittypedesc")) or _clean(raw.get("permittypemapped"))
    return {
        "source_record_id": sid,
        "permit_number": sid,
        "address": address,
        "city": city,
        "county": reg["county"],
        "state": reg["state"],
        "zip": zipc,
        "permit_type": pt,
        "trade": classify_seattle_trade(raw.get("permittypemapped"),
                                        raw.get("permittypedesc"),
                                        raw.get("description")),
        "category": category,
        "project_description": _clean(raw.get("description")),
        "valuation": _num(raw.get("estprojectcost")),
        "status": status,
        "status_source": status_src,
        "application_date": _date(raw.get("applieddate")),
        "issue_date": _date(raw.get("issueddate")),
        "source_updated_date": None,  # dataset publishes no per-row load stamp
        "contractor_name": contractor,
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


def normalize_nyc(raw, reg):
    """One collapsed NYC DOB NOW issuance event -> standard record dict.

    Input is NOT a raw feed row: the pipeline's collapse step (registry
    collapse_events) has already merged the event's per-work-type rows into
    one dict carrying `_work_types` (the issuance's work types) and
    `_valuation_event` (True only for the filing's latest issuance in the
    window). Identity (registry dedupe_rule): one permit = one
    (job_filing_number, tracking_number) issuance event; permit_number is
    the work_permit slot number, which recurs across the slot's issuances.
    Privacy: the pull is column-restricted by the registry pull_select —
    applicant person-name fields, filing-representative fields, and owner
    fields are never requested from the API at all. The only name carried
    is applicant_business_name, the permittee's published BUSINESS name
    (the dataset separates it from the applicant's person-name fields).
    Valuation (registry field_map.valuation): estimated_job_costs is a
    job-filing figure restated on every issuance of the filing, so it is
    stored only on the filing's latest issuance in the window and NULL on
    the earlier ones — each filing's cost is counted exactly once.
    """
    job = _clean(raw.get("job_filing_number"))
    tracking = _clean(raw.get("tracking_number"))
    if not job or not tracking or not _JOB_NUMBER_RE.match(job):
        # No real source identity: the feed's placeholder job number
        # ('Permit is no', work_permit 'Permit is not yet issued') names 4
        # window events. Held, reported, never published (registry rule).
        return None
    parts = [_clean(raw.get("house_no")), _clean(raw.get("street_name"))]
    address = " ".join(p for p in parts if p)
    address = " ".join(address.split())  # source pads some street names
    if address and address.isupper():
        address = _title(address)
    address = address or None
    contractor = _clean(raw.get("applicant_business_name"))
    if contractor and contractor.isupper():
        contractor = _title(contractor)
    status_src = _clean(raw.get("permit_status"))
    status = reg["status_map"].get(status_src, "not-stated") if status_src else "not-stated"
    work_types = [str(w).strip() for w in raw.get("_work_types", []) if w]
    valuation = _num(raw.get("estimated_job_costs")) if raw.get("_valuation_event") else None
    return {
        "source_record_id": f"{job}|{tracking}",
        "permit_number": _clean(raw.get("work_permit")),
        "address": address,
        "city": reg["borough_pull"]["borough_variants"][0],
        "county": reg["county"],
        "state": reg["state"],
        "zip": _clean(raw.get("zip_code")),
        "permit_type": "; ".join(work_types) or None,
        "trade": classify_nyc_trade(work_types, raw.get("job_description")),
        "category": None,  # source publishes no residential/commercial class; honest NULL
        "project_description": _clean(raw.get("job_description")),
        "valuation": valuation,
        "status": status,
        "status_source": status_src,
        "application_date": _date(raw.get("approved_date")),
        "issue_date": _date(raw.get("issued_date")),
        "source_updated_date": None,  # dataset publishes no per-row load stamp
        "contractor_name": contractor,
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


def normalize_philadelphia(raw, reg):
    """One raw Philadelphia row -> standard record dict (or None).

    Identity (registry dedupe_rule): the permit number is exactly unique
    in the trailing-12-month window (45,900 rows = 45,900 distinct
    permitnumber, measured 2026-10-18) — source_record_id = permitnumber,
    no collapsing. Privacy: the pull is column-restricted by the registry
    pull_select — opa_owner (the property owner, a person field) is never
    requested from the API at all, and neither are the contractor address
    fields or the geometry column. The only name carried is
    contractorname, L&I's published contractor of record on the permit.
    Valuation: the dataset publishes no cost field at all (47-column
    schema verified), so valuation stays NULL and Philadelphia runs
    counts-only by construction. Application date: the dataset publishes
    no application-date column, so it stays NULL by construction.
    """
    sid = _clean(raw.get("permitnumber"))
    if not sid:
        return None
    address = _clean(raw.get("address"))
    if address and address.isupper():
        address = _title(address)
    contractor = _clean(raw.get("contractorname"))
    if contractor and contractor.isupper():
        contractor = _title(contractor)
    status_src = _clean(raw.get("status"))
    status = reg["status_map"].get(status_src.upper(), "not-stated") if status_src else "not-stated"
    cat_src = (_clean(raw.get("commercialorresidential")) or "").lower()
    category = cat_src if cat_src in ("residential", "commercial") else None
    return {
        "source_record_id": sid,
        "permit_number": sid,
        "address": address,
        "city": "Philadelphia",
        "county": reg["county"],
        "state": reg["state"],
        "zip": _clean(raw.get("zip")),
        "permit_type": _clean(raw.get("permitdescription")) or _clean(raw.get("permittype")),
        "trade": classify_philly_trade(raw.get("permittype"), raw.get("typeofwork"),
                                       raw.get("approvedscopeofwork")),
        "category": category,
        "project_description": _clean(raw.get("approvedscopeofwork")),
        "valuation": None,  # source publishes no cost field (registry field_map)
        "status": status,
        "status_source": status_src,
        "application_date": None,  # source publishes no application-date column
        "issue_date": _date(raw.get("permitissuedate")),
        "source_updated_date": None,  # dataset publishes no per-row load stamp
        "contractor_name": contractor,
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


def _money(v):
    """Boston's declared_valuation is a formatted string ('$36,500.00')."""
    s = _clean(v)
    if not s:
        return None
    try:
        return float(s.replace("$", "").replace(",", "").strip())
    except ValueError:
        return None


def normalize_boston(raw, reg):
    """One raw Boston row -> standard record dict (or None if unusable id).

    Identity (registry dedupe_rule): the permit number is exactly unique
    in the trailing-12-month window (36,367 rows = 36,367 distinct
    permitnumber, measured 2026-10-18) — source_record_id = permitnumber,
    no collapsing. Privacy: the pull is column-restricted by the registry
    pull_select — `applicant`, the dataset's only name field, carries
    PERSON names and is never requested from the API at all; the schema
    publishes no contractor/business field, so contractor stays NULL,
    never inferred (the San Francisco treatment). Valuation:
    declared_valuation parsed from its formatted string and stored as
    reported (validated 2026-10-18 — see registry field_map.valuation;
    Certificates of Occupancy restating a project's value at the same
    address are the source's own shape, mirrored per SOP rule 2).
    Application date: the dataset publishes no application-date column,
    so it stays NULL by construction (the Philadelphia treatment).
    Category: occupancytype is a building occupancy class, not a permit
    category — NULL (the Chicago/SF/NYC honest-NULL treatment).
    """
    sid = _clean(raw.get("permitnumber"))
    if not sid:
        return None
    address = _clean(raw.get("address"))
    if address and address.isupper():
        address = _title(address)
    city = _clean(raw.get("city"))
    if city and city.isupper():
        city = _title(city)
    if not city:
        city = "Boston"  # issuing jurisdiction's seat; mirrors Austin's default
    status_src = _clean(raw.get("status"))
    status = reg["status_map"].get(status_src.upper(), "not-stated") if status_src else "not-stated"
    comments = _clean(raw.get("comments"))
    descr = _clean(raw.get("description"))
    scope = comments or descr
    return {
        "source_record_id": sid,
        "permit_number": sid,
        "address": address,
        "city": city,
        "county": reg["county"],
        "state": reg["state"],
        "zip": _clean(raw.get("zip")),
        "permit_type": _clean(raw.get("permittypedescr")) or _clean(raw.get("worktype")),
        "trade": classify_boston_trade(raw.get("permittypedescr"),
                                       raw.get("worktype"),
                                       f"{comments or ''} {descr or ''}"),
        "category": None,  # occupancy class is not a permit category; honest NULL
        "project_description": scope,
        "valuation": _money(raw.get("declared_valuation")),
        "status": status,
        "status_source": status_src,
        "application_date": None,  # source publishes no application-date column
        "issue_date": _date(raw.get("issued_date")),
        "source_updated_date": None,  # dataset publishes no per-row load stamp
        "contractor_name": None,  # only name field is `applicant` (persons) — never pulled
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


def _unquote(v):
    """Cincinnati's current extract wraps some text values in literal
    double quotes (a CSV-import artifact: '"QUEEN CITY CONSTRUCTION,
    INC."'). Strip one surrounding pair; leave inner quotes alone."""
    s = _clean(v)
    if s and len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        s = s[1:-1].strip() or None
    return s


def _cost(v):
    """Cincinnati's estprojectcostdec is a TEXT column ('20000')."""
    s = _unquote(v)
    if s is None:
        return None
    try:
        return float(s.replace(",", "").replace("$", ""))
    except ValueError:
        return None


def normalize_cincinnati(raw, reg):
    """One collapsed Cincinnati permit -> standard record dict (or None).

    Input is NOT a raw feed row: the pipeline's collapse step (registry
    collapse_events, key = permitnum) has already merged the permit's
    per-component rows into one dict carrying `_components` ({label,
    type, cost} per component row, in pull order). Identity (registry
    dedupe_rule): one published permit = one permitnum — the feed's grain
    is one row per work component the permit covers (10,417 window rows =
    9,788 permits; rows are unique per (permitnum, component), and a
    permit's rows agree on every identity field, re-asserted by the
    collapse on each run). Privacy: the dataset publishes no applicant or
    owner person-name fields at all (verified against the full 31-column
    schema); the only name carried is companyname, the permit's published
    company of record, with its CSV quote artifacts stripped — the city's
    'OWNER' code (owner-permitted work) names no company and stays NULL.
    Valuation (registry field_map.valuation): each component row states
    its own slice of the permit's estimated cost, so the permit's value
    is the SUM of its components' stated costs. Category: permitclass is
    the building code the permit issued under — RCO (Residential Code of
    Ohio) -> residential, OBC (Ohio Building Code) -> commercial; the
    class is published on 100% of window rows. The dataset publishes no
    free-text scope: `description` IS the component label, so the record's
    project description is the permit's component labels joined.
    """
    sid = _clean(raw.get("permitnum"))
    if not sid:
        return None
    comps = raw.get("_components") or []
    if not comps:  # defensive: an uncollapsed row is its own one component
        comps = [{"label": raw.get("description"),
                  "type": raw.get("permittypemapped"),
                  "cost": raw.get("estprojectcostdec")}]
    labels, types, costs = [], [], []
    for c in comps:
        lab = _clean(c.get("label"))
        if lab and lab not in labels:
            labels.append(lab)
        typ = _clean(c.get("type"))
        if typ and typ not in types:
            types.append(typ)
        v = _cost(c.get("cost"))
        if v is not None:
            costs.append(v)
    valuation = sum(costs) if costs else None
    address = _clean(raw.get("originaladdress1"))
    if address and address.isupper():
        address = _title(address)
    city = _clean(raw.get("originalcity"))
    if city and city.isupper():
        city = _title(city)
    if not city:
        city = "Cincinnati"  # issuing jurisdiction's seat; mirrors Austin's default
    zipc = _clean(raw.get("originalzip"))
    if zipc and zipc.endswith(".0"):
        zipc = zipc[:-2]
    contractor = _unquote(raw.get("companyname"))
    if contractor and contractor.upper() == "OWNER":
        contractor = None  # the city's owner-permitted code names no company
    if contractor and contractor.isupper():
        contractor = _title(contractor)
    status_src = _clean(raw.get("statuscurrentmapped")) or _clean(raw.get("statuscurrent"))
    status = reg["status_map"].get(status_src.upper(), "not-stated") if status_src else "not-stated"
    cat_src = (_clean(raw.get("permitclass")) or "").upper()
    category = {"RCO": "residential", "OBC": "commercial"}.get(cat_src)
    return {
        "source_record_id": sid,
        "permit_number": sid,
        "address": address,
        "city": city,
        "county": reg["county"],
        "state": reg["state"],
        "zip": zipc,
        "permit_type": "; ".join(types) or None,
        "trade": classify_cincinnati_trade(labels),
        "category": category,
        "project_description": "; ".join(labels) or None,
        "valuation": valuation,
        "status": status,
        "status_source": status_src,
        "application_date": _date(raw.get("applieddate")),
        "issue_date": _date(raw.get("issueddate")),
        "source_updated_date": None,  # dataset publishes no per-row load stamp
        "contractor_name": contractor,
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


def _br_city(v):
    """Baton Rouge's city1 is a free-text mailing-city field ('BATON
    ROUGE', 'Baton R0uge', 'Baton rouge la 70815', 'ZACHARY', 'test', ...).
    Anything recognizably Baton Rouge — and anything unusable — becomes
    'Baton Rouge', the issuing jurisdiction's seat (the Austin default);
    real neighboring localities (Zachary, Baker, Greenwell Springs,
    Pride, Slaughter, Jackson, Clinton) are carried, title-cased."""
    s = _clean(v)
    if not s:
        return "Baton Rouge"
    low = s.lower()
    if "baton" in low or low == "test":
        return "Baton Rouge"
    return _title(s) if s.isupper() else s


def normalize_baton_rouge(raw, reg):
    """One collapsed East Baton Rouge Parish permit -> standard record.

    Input is NOT a raw feed row: the pipeline's collapse step (registry
    collapse_events, key = permitid) has already merged the permit's
    per-address rows into one dict — the feed's grain is one row per
    address a permit covers (the San Francisco pattern, measured
    2026-10-18: 8,500 window rows = 8,482 permits; sibling rows agree on
    every permit-level field, re-asserted by the collapse on each run).
    The record is represented by the permit's first row in pull order
    (issue date, permit id, street address, contractor name); the source
    publishes no primary-address flag. Privacy: the pull is
    column-restricted by the registry pull_select — ownername and
    applicantname (person names) and contractoraddress are never
    requested from the API at all. The only name carried is
    contractorname, the permit's published contractor of record ('N/A'
    names no contractor and stays NULL). Valuation: projectvalue is
    restated verbatim on a permit's sibling rows, so the collapsed
    record's figure is the permit's value, counted once (validated
    2026-10-18 — see registry field_map.valuation). Status: the dataset
    publishes no status field; it is an issued-permits register, so
    status is 'issued' by the dataset's own definition. Category: the
    source's own designation, NULL where the source states none.
    """
    sid = _clean(raw.get("permitid"))
    if not sid:
        return None
    address = _clean(raw.get("streetaddress"))
    if address and address.isupper():
        address = _title(address)
    zipc = _clean(raw.get("zip"))
    if zipc and zipc.endswith(".0"):
        zipc = zipc[:-2]
    contractor = _clean(raw.get("contractorname"))
    if contractor and contractor.strip().upper() in ("N/A", "NA", "NONE"):
        contractor = None  # the source's no-contractor value names no one
    if contractor and contractor.isupper():
        contractor = _title(contractor)
    cat_src = (_clean(raw.get("designation")) or "").lower()
    category = cat_src if cat_src in ("residential", "commercial") else None
    return {
        "source_record_id": sid,
        "permit_number": _clean(raw.get("permitnumber")),
        "address": address,
        "city": _br_city(raw.get("city1")),
        "county": reg["county"],
        "state": reg["state"],
        "zip": zipc,
        "permit_type": _clean(raw.get("permittype")),
        "trade": classify_br_trade(raw.get("permittype")),
        "category": category,
        "project_description": _clean(raw.get("projectdescription")),
        "valuation": _num(raw.get("projectvalue")),
        "status": "issued",  # the dataset is an issued-permits register
        "status_source": None,  # the dataset publishes no status field
        "application_date": _date(raw.get("creationdate")),
        "issue_date": _date(raw.get("issueddate")),
        "source_updated_date": None,  # dataset publishes no per-row load stamp
        "contractor_name": contractor,
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


import re as _re

_SA_ZIP_RE = _re.compile(r"(\d{5})(?:-\d{4})?\s*$")


def _sa_address(raw_address):
    """San Antonio's ADDRESS is one free-text field: '3131 OLD ALMONTE
    DR, City of San Antonio, TX 78224', with ETJ and enclave variants
    ('City of San Antonio ETJ', 'Hollywood Park, TX 78232') and some
    street-only values. Returns (street, city, zip): street is the text
    before the first comma; city is the second segment with the 'City
    of' prefix and the ETJ marker dropped (display only — coverage is
    the city's feed, never the segment); zip is the trailing 5-digit
    group when present (78,252 of 80,965 window rows carry one)."""
    s = _clean(raw_address)
    if not s:
        return None, "San Antonio", None
    zipc = None
    m = _SA_ZIP_RE.search(s)
    if m:
        zipc = m.group(1)
    parts = [p.strip() for p in s.split(",")]
    street = parts[0] if parts else s
    if street and street.isupper():
        street = _title(street)
    city = None
    if len(parts) > 1:
        c = parts[1]
        if c.lower().startswith("city of "):
            c = c[8:]
        if c.upper().endswith(" ETJ"):
            c = c[:-4]
        c = c.strip()
        if c:
            city = _title(c) if c.isupper() else c
    return street or None, city or "San Antonio", zipc


def normalize_san_antonio(raw, reg):
    """One collapsed San Antonio permit -> standard record dict (or None).

    Input is NOT a raw feed row: the pipeline's collapse step (registry
    collapse_events, key = PERMIT #) has already merged the permit's rows
    into one dict carrying `_components` ({label, type, cost} per row —
    the row's PERMIT TYPE and DECLARED VALUATION). Identity (registry
    dedupe_rule): the PERMITS ISSUED register's grain is one row per
    permit-type component an issuance covers, plus repeat submission
    rows — one published permit = one PERMIT #, one issuance: across all
    3,099 multi-row window permits the rows never disagree on address,
    issue date, or work type (measured 2026-10-18), and the pull's order
    makes the representative row the permit's earliest submission, so
    application_date is the original DATE SUBMITTED. Scope (registry
    pull_where_extra): the register also issues non-construction permits
    (garage sales, tree affidavits, temporary signs and banners); those
    families are filtered at pull time — no scoped permit's type set
    touches them (measured: zero mixed permits). Privacy: the pull is
    column-restricted by the registry pull_select — PRIMARY CONTACT and
    PROJECT NAME, the register's two name-bearing fields (PRIMARY
    CONTACT carries person names — e.g. individual garage-sale and
    residential applicants; PROJECT NAME mixes applicant names with
    project labels), are never requested from the API at all. The
    dataset publishes no contractor/business field, so contractor stays
    NULL, never inferred (the Boston/SF treatment). Valuation:
    DECLARED VALUATION is stored as reported (the group's single stated
    figure; the one window permit stating two figures stores the larger,
    its amended figure) but is NOT published — the field is populated on
    only 2.55% of window permits (the commercial building core) and
    restates whole-project values across a project's permits, so no
    honest county total exists: Bexar County runs counts-only (the
    Austin/Seattle outcome, both diseases at once). Category: the
    register's type names mix Res/Comm prefixes inconsistently and the
    trade families are unmarked — NULL (honest-NULL precedent). Status:
    the register publishes no status field; it is a permits-issued
    register, so status is 'issued' (the Baton Rouge treatment). The
    register publishes no scope-of-work text, so project_description
    stays NULL, never invented.
    """
    sid = _clean(raw.get("PERMIT #"))
    if not sid:
        return None
    comps = raw.get("_components") or []
    if not comps:  # defensive: an uncollapsed row is its own one component
        comps = [{"label": raw.get("PERMIT TYPE"),
                  "type": raw.get("PERMIT TYPE"),
                  "cost": raw.get("DECLARED VALUATION")}]
    labels = []
    for comp in comps:
        lab = _clean(comp.get("label"))
        if lab and lab not in labels:
            labels.append(lab)
    stated = {_num(comp.get("cost")) for comp in comps}
    stated.discard(None)
    valuation = max(stated) if stated else None
    street, city, zipc = _sa_address(raw.get("ADDRESS"))
    return {
        "source_record_id": sid,
        "permit_number": sid,
        "address": street,
        "city": city,
        "county": reg["county"],
        "state": reg["state"],
        "zip": zipc,
        "permit_type": "; ".join(labels) or None,
        "trade": classify_sa_trade(labels),
        "category": None,  # no consistent res/comm class published; honest NULL
        "project_description": None,  # register publishes no scope text
        "valuation": valuation,
        "status": "issued",  # the dataset is a permits-issued register
        "status_source": None,  # the dataset publishes no status field
        "application_date": _date(raw.get("DATE SUBMITTED")),
        "issue_date": _date(raw.get("DATE ISSUED")),
        "source_updated_date": None,  # dataset publishes no per-row load stamp
        "contractor_name": None,  # only name fields are person fields — never pulled
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


def _epoch_ms_date(v):
    """ArcGIS date fields arrive as epoch milliseconds (numbers)."""
    if v is None or v == "":
        return None
    try:
        from datetime import datetime, timezone
        return datetime.fromtimestamp(float(v) / 1000, timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _fw_address(raw):
    """Fort Worth's table splits the street address into parts (Addr_No,
    Direction, Street_Name, Street_Suffix, Street_Suffix_Dir); its own
    Full_Street_Address column is unpopulated on sampled rows, so the
    parts are composed. All-caps compositions are title-cased."""
    parts = []
    no = raw.get("Addr_No")
    if no is not None and str(no).strip() not in ("", "0"):
        parts.append(str(no).strip().removesuffix(".0"))
    for f in ("Direction", "Street_Name", "Street_Suffix", "Street_Suffix_Dir"):
        s = _clean(raw.get(f))
        if s:
            parts.append(s)
    if not parts:
        return None
    addr = " ".join(parts)
    return _title(addr) if addr.isupper() else addr


def normalize_fort_worth(raw, reg):
    """One collapsed Fort Worth permit -> standard record dict (or None).

    Input is NOT a raw feed row: the pipeline's collapse step (registry
    collapse_events, key = Permit_No) has already merged the permit's
    restated mirror rows into one dict — the feed's grain is mostly one
    row per permit with a measured fan-out (70,199 issued-window rows =
    63,948 permits; surplus rows restate the permit per address it
    covers or as mirror duplicates, and never disagree on type, subtype,
    or job value). The representative row is the permit's earliest-filed
    row (pull order: File_Date, Permit_No, ObjectId). Population
    (registry pull_where_extra): only permits standing in an
    issued-proven status are pulled — the table is the city's
    all-applications Accela mirror, and statuses that cannot prove
    issuance (plan review, approved-not-yet-issued, withdrawn, denied,
    ...) are out of the published population by definition, as is the
    'Design Review' type (an approval that authorizes no construction).
    Dates: the feed publishes NO issuance date. issue_date therefore
    carries File_Date — the permit's application month — under the
    definition printed on the hub, Data Sources, and llms.txt (counts
    are issued permits by the month the application was filed);
    Status_Date is deliberately never used as a date of record (for
    Finaled permits it is the final-inspection date). Privacy: the pull
    is column-restricted by the registry pull_select — Owner_Full_Name
    (property-owner person names) and B1_SPECIAL_TEXT (who was involved)
    are never requested from the API at all, and the table publishes no
    contractor/business field, so contractor stays NULL, never inferred
    (the Boston treatment). Valuation: JobValue belongs to the permit
    (its rows never disagree); the city collects it on the building
    families (~100% of their permits) and not on trade permits (0%), so
    the permit's stated figure is stored as reported and published under
    the count-once rule (registry field_map.valuation).
    """
    sid = _clean(raw.get("Permit_No"))
    if not sid:
        return None
    ptype = _clean(raw.get("Permit_Type"))
    subtype = _clean(raw.get("Permit_SubType"))
    status_src = _clean(raw.get("Current_Status"))
    status = reg["status_map"].get(status_src.upper(), "not-stated") if status_src else "not-stated"
    category = {"Residential Building Permit": "residential",
                "Residential Accessory Struct": "residential",
                "Commercial Building Permit": "commercial",
                "Commercial Accessory Structure": "commercial",
                "Commercial Grading Permit": "commercial"}.get(ptype)
    zipc = raw.get("Zip_Code")
    zipc = str(int(zipc)) if isinstance(zipc, (int, float)) and zipc else _clean(zipc)
    file_date = _epoch_ms_date(raw.get("File_Date"))
    return {
        "source_record_id": sid,
        "permit_number": sid,
        "address": _fw_address(raw),
        "city": "Fort Worth",  # issuing jurisdiction's seat; mirrors Austin's default
        "county": reg["county"],
        "state": reg["state"],
        "zip": zipc,
        "permit_type": ptype,
        "trade": classify_fort_worth_trade(ptype, subtype),
        "category": category,
        "project_description": _clean(raw.get("B1_WORK_DESC")),
        "valuation": _cost(raw.get("JobValue")),
        "status": status,
        "status_source": status_src,
        "application_date": file_date,
        "issue_date": file_date,  # the feed's only record date — see docstring
        "source_updated_date": None,  # dataset publishes no per-row load stamp
        "contractor_name": None,  # no business field exists; owner names never pulled
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


def normalize_raleigh(raw, reg):
    """One raw Raleigh row -> standard record dict (or None).

    Identity (registry dedupe_rule): the permit number is exactly
    unique in the trailing-12-month window (5,486 rows = 5,486 distinct
    permitnum, measured 2026-10-23 on a full audit pull) —
    source_record_id = permitnum, no collapsing. Privacy: the pull is
    column-restricted by the registry pull_select — the parcel-owner
    fields (parcelownername and the owner address fields, property-owner
    person data) and the contractor's email/phone/license/address fields
    are never requested from the API at all. The only name carried is
    contractorcompanyname, the permit's published contractor company of
    record (present on 4,857 of 5,486 window permits; the source's empty
    string carries as NULL). Dates arrive as ArcGIS epoch milliseconds.
    Valuation: estprojectcost is stored and published as reported (it
    passed validation on the full window — see registry
    field_map.valuation). Category: the city's own mapped class
    (Residential / Non-Residential, the Seattle treatment). Population:
    the pull window is issueddate, so every record was issued by the
    city; post-issuance statuses (Complete, Expired-Closed, On Hold,
    Stop Work Order) stay in the population with their source status
    preserved.
    """
    sid = _clean(raw.get("permitnum"))
    if not sid:
        return None
    address = _clean(raw.get("originaladdress1"))
    if address and address.isupper():
        address = _title(address)
    city = _clean(raw.get("originalcity"))
    if city and city.isupper():
        city = _title(city)
    if not city:
        city = "Raleigh"  # issuing jurisdiction's seat; mirrors Austin's default
    zipc = _clean(raw.get("originalzip"))
    if zipc and zipc.endswith(".0"):
        zipc = zipc[:-2]
    contractor = _clean(raw.get("contractorcompanyname"))
    if contractor and contractor.isupper():
        contractor = _title(contractor)
    status_src = _clean(raw.get("statuscurrent"))
    status = reg["status_map"].get(status_src.upper(), "not-stated") if status_src else "not-stated"
    cat_src = (_clean(raw.get("permitclassmapped")) or "").lower()
    category = cat_src if cat_src in ("residential", "non-residential") else None
    return {
        "source_record_id": sid,
        "permit_number": sid,
        "address": address,
        "city": city,
        "county": reg["county"],
        "state": reg["state"],
        "zip": zipc,
        "permit_type": _clean(raw.get("permittype")),
        "trade": classify_raleigh_trade(raw.get("permittype"),
                                        raw.get("workclassmapped"),
                                        raw.get("proposeduse"),
                                        raw.get("proposedworkdescription")),
        "category": category,
        "project_description": _clean(raw.get("proposedworkdescription")),
        "valuation": _num(raw.get("estprojectcost")),
        "status": status,
        "status_source": status_src,
        "application_date": _epoch_ms_date(raw.get("applieddate")),
        "issue_date": _epoch_ms_date(raw.get("issueddate")),
        "source_updated_date": None,  # dataset publishes no per-row load stamp
        "contractor_name": contractor,
        "source_name": reg["source_name"],
        "source_url": reg["source_url"],
    }


NORMALIZERS = {"chicago-cook-il": normalize_chicago,
               "austin-travis-tx": normalize_austin,
               "san-francisco-ca": normalize_sf,
               "seattle-king-wa": normalize_seattle,
               "nyc-new-york-ny": normalize_nyc,
               "nyc-kings-ny": normalize_nyc,
               "nyc-queens-ny": normalize_nyc,
               "nyc-bronx-ny": normalize_nyc,
               "nyc-richmond-ny": normalize_nyc,
               "philadelphia-pa": normalize_philadelphia,
               "boston-suffolk-ma": normalize_boston,
               "cincinnati-hamilton-oh": normalize_cincinnati,
               "baton-rouge-east-baton-rouge-la": normalize_baton_rouge,
               "san-antonio-bexar-tx": normalize_san_antonio,
               "fort-worth-tarrant-tx": normalize_fort_worth,
               "raleigh-wake-nc": normalize_raleigh}
