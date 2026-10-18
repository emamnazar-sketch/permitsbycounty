"""Deterministic trade classification for permit records.

Scripts do the hauling (PHASE1-PLAN automation shape): this classifier is
rule-based and auditable, not an AI call. Records it cannot classify land in
'general' and are counted in the run report so a human can review the rate.
Rules are evaluated in order; first match wins.
"""

SOLAR = ("solar",)
ROOF = ("reroof", "re-roof", "roofing", "roof replacement", "shingle")
ELEC = ("electrical", "electric service", "service upgrade", "panel upgrade", "ev charger", "ev charging")
PLUMB = ("plumbing", "water heater", "repipe", "repiping", "sewer", "gas line", "boiler")
HVAC = ("hvac", "furnace", "air conditioning", "air conditioner", "ductwork", "mechanical work", "condensing unit")


def _contains(text, needles):
    return any(n in text for n in needles)


def classify_trade(permit_type="", work_type="", description=""):
    pt = (permit_type or "").lower()
    wt = (work_type or "").lower()
    d = (description or "").lower()
    blob = f"{wt} {pt} {d}"

    if "wrecking" in pt or "demolition" in pt or wt == "demolition":
        return "demolition"
    if _contains(blob, SOLAR):
        return "solar"
    if wt == "electrical work" or "electrical" in pt:
        return "electrical"
    if wt == "plumbing work":
        return "plumbing"
    if wt == "mechanical work":
        return "hvac"
    # Austin (data.austintexas.gov): the permit type itself names the trade
    # ("Mechanical Permit", "Plumbing Permit") and work_class carries no
    # trade signal. Chicago's permit_type values never contain these
    # strings (verified against the loaded Chicago data), so these rules
    # cannot reclassify Chicago records.
    if "mechanical" in pt:
        return "hvac"
    if "plumbing" in pt:
        return "plumbing"
    if wt in ("reroofing",) or _contains(d, ROOF):
        return "roofing"
    if "new construction" in pt:
        return "new-construction"
    if "elevator" in pt:
        return "elevator"
    if "signs" in pt or pt.strip().endswith("sign"):
        return "signage"
    if wt == "fire alarm system":
        return "fire-alarm"
    if wt == "masonry work":
        return "masonry"
    if wt == "fence or trash enclosure":
        return "fencing"
    # Description keyword fallback, most specific first.
    if _contains(d, HVAC):
        return "hvac"
    if _contains(d, PLUMB):
        return "plumbing"
    if _contains(d, ELEC):
        return "electrical"
    return "general"


def classify_seattle_trade(type_mapped="", type_desc="", description=""):
    """Seattle (data.seattle.gov 76t5-zqzr) trade classification.

    Seattle's mapped permit type separates demolition and roof permits
    cleanly, and permittypedesc names new construction; everything else is
    a building permit whose trade signal, when one exists, lives in the
    work description. Deterministic, first match wins; records no rule
    claims land in 'general' and are counted in the run report. Kept
    separate from classify_trade so other counties cannot be disturbed.
    """
    tm = (type_mapped or "").strip().lower()
    td = (type_desc or "").strip().lower()
    d = (description or "").lower()
    if tm == "demolition":
        return "demolition"
    if tm == "roof":
        return "roofing"
    if td == "new":
        return "new-construction"
    if _contains(d, SOLAR):
        return "solar"
    if _contains(d, HVAC):
        return "hvac"
    if _contains(d, PLUMB):
        return "plumbing"
    if _contains(d, ELEC):
        return "electrical"
    if _contains(d, ROOF):
        return "roofing"
    return "general"


def classify_philly_trade(permit_type="", work_type="", description=""):
    """Philadelphia (phl.carto.com `permits`, L&I) trade classification.

    Philadelphia's permittype names the trade directly for the four big
    licensed trades (Plumbing, Electrical, Mechanical, Fire Suppression) —
    those win first. typeofwork then separates new construction, EZ roof
    replacements, solar, signs, and demolition from the building/zoning/
    general stream; the approved scope is the keyword fallback. The one
    trap: 'EZ Interior Non-Load-Bearing Wall Demo.' is interior alteration
    work, not demolition — it is excluded from the demolition rule by its
    'wall demo' wording. Deterministic, first match wins; records no rule
    claims land in 'general' and are counted in the run report. Kept
    separate so other counties cannot be disturbed.
    """
    pt = (permit_type or "").strip()
    tw = (work_type or "").strip().lower()
    d = (description or "").lower()
    if pt == "Plumbing":
        return "plumbing"
    if pt == "Electrical":
        return "electrical"
    if pt == "Mechanical":
        return "hvac"
    if pt == "Fire Suppression":
        return "fire-protection"
    if pt == "Demolition" or ("demolition" in tw and "wall demo" not in tw):
        return "demolition"
    if tw.startswith("new construction"):
        return "new-construction"
    if "roof" in tw:
        return "roofing"
    if "solar" in tw:
        return "solar"
    if "sign" in tw:
        return "signage"
    if _contains(d, HVAC):
        return "hvac"
    if _contains(d, PLUMB):
        return "plumbing"
    if _contains(d, ELEC):
        return "electrical"
    if _contains(d, ROOF):
        return "roofing"
    return "general"


import re

_NUMWORD = (r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
            r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
            r"eighteen|nineteen|twenty)")
# NB signal = "new building", "new NB", or "new <number> story" (number as
# digits or a word, optional parenthetical: "NEW SIX (6) STORY BUILDING").
# The bare phrase "new construction" is deliberately NOT a signal: DOB
# descriptions use it for construction fences, demolition prep, and
# interior fit-outs (verified against loaded data, 2026-10-18).
_NEW_BUILDING_RE = re.compile(
    r"new\s+(?:building|nb\b|" + _NUMWORD +
    r"(?:\s*\([^)]*\))?\s*-?\s*(?:story|storey|stories))|proposed\s+nb\b")


def classify_nyc_trade(work_types=(), description=""):
    """New York City (data.cityofnewyork.us rbx6-tga4, DOB NOW) trade
    classification. Input is the issuance event's SET of DOB work types —
    DOB NOW records one row per work type an issuance covers, and the
    pipeline collapses those rows into one permit before classification
    (registry dedupe_rule). DOB work types are themselves trade-bearing
    (Plumbing, Mechanical Systems, Solar, Sign...), so the primary trade is
    chosen by precedence: the most specific trade named wins over the
    general-construction cluster. DOB NOW excludes electrical, elevator,
    and limited-alteration permits entirely (separate datasets), so no
    electrical rule exists here. Deterministic; first match wins; events
    no rule claims land in 'general' and are counted in the run report.
    Kept separate so other counties cannot be disturbed.
    """
    t = {str(w).strip() for w in (work_types or ()) if w}
    d = (description or "").lower()
    if "Full Demolition" in t:
        return "demolition"
    if _NEW_BUILDING_RE.search(d):
        return "new-construction"
    if "Plumbing" in t:
        return "plumbing"
    if "Mechanical Systems" in t or "Boiler Equipment" in t:
        return "hvac"
    if "Solar" in t:
        return "solar"
    if "Sprinklers" in t or "Standpipe" in t:
        return "fire-protection"
    if "Sign" in t:
        return "signage"
    if t & {"Sidewalk Shed", "Supported Scaffold", "Suspended Scaffold"}:
        return "scaffolding"
    return "general"


def classify_sf_trade(definition="", description="", reroof="", fire_only=""):
    """San Francisco (DataSF i98e-djp9) trade classification.

    SF's permit_type_definition is a *process* category, not a trade: 91%
    of the trailing-12-month window is 'otc alterations permit'. The trade
    signal lives in the source's own flags first (reroof, fire_only_permit),
    then the work description. Deterministic, first match wins; records no
    rule claims land in 'general' and are counted in the run report.
    Kept separate from classify_trade so Chicago/Austin classification
    cannot be disturbed.
    """
    dt = (definition or "").lower()
    d = (description or "").lower()
    if "demolition" in dt:
        return "demolition"
    if "new construction" in dt:
        return "new-construction"
    if "sign" in dt:
        return "signage"
    if (reroof or "").strip().upper() == "Y":
        return "roofing"
    if _contains(d, SOLAR):
        return "solar"
    if (fire_only or "").strip().upper() == "Y":
        return "fire-alarm"
    if _contains(d, HVAC):
        return "hvac"
    if _contains(d, PLUMB):
        return "plumbing"
    if _contains(d, ELEC):
        return "electrical"
    if _contains(d, ROOF):
        return "roofing"
    return "general"
