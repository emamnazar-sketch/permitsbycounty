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


def classify_boston_trade(permit_type_descr="", worktype="", description=""):
    """Boston (data.boston.gov CKAN, Approved Building Permits) trade
    classification.

    Two source signals compete: permittypedescr names the LICENSE family
    (Electrical Permit, Plumbing Permit, Gas Permit...), while worktype
    names the WORK actually performed (SOL, FA, ROOF...). Where ISD's own
    taxonomy separates a work family from the generic electrical code —
    SOL (solar) and FA (fire alarm) are distinct worktypes, not ELECTRICAL
    — the work wins over the license: a solar array filed on an electrical
    permit is a solar job (753 of the window's 1,462 SOL rows sit on
    Electrical Permits; measured 2026-10-18). The unambiguous work codes
    therefore fire first: SOL solar, RAZE + EXTDEM demolition, ROOF
    roofing, SIGNES signs, FA fire alarm, SPRINK sprinklers (fire
    protection, the NYC treatment), ERECT new construction, FENCE fencing.
    The one trap, handled exactly as Philadelphia handled its 'EZ Interior
    Non-Load-Bearing Wall Demo': INTDEM (interior demolition) is interior
    alteration work, NOT demolition — it is deliberately excluded from the
    demolition rule (EXTDEM, exterior demolition, is genuine demolition).
    The license-family permit types fire next, then the remaining trade
    worktype codes, then the scope text (comments, else the short
    description) as keyword fallback. Gas fitting is its own Boston permit
    family (3,062 window permits) and classifies as its own trade, 'gas'.
    Deterministic, first match wins; records no rule claims land in
    'general' and are counted in the run report. Kept separate so other
    counties cannot be disturbed.
    """
    pt = (permit_type_descr or "").strip()
    wt = (worktype or "").strip().upper()
    d = (description or "").lower()
    if pt == "Electrical Fire Alarms":
        return "fire-alarm"
    if wt == "SOL":
        return "solar"
    if wt in ("RAZE", "EXTDEM"):
        return "demolition"
    if wt == "ROOF":
        return "roofing"
    if wt == "SIGNES":
        return "signage"
    if wt == "FA":
        return "fire-alarm"
    if wt == "SPRINK":
        return "fire-protection"
    if wt == "ERECT":
        return "new-construction"
    if wt in ("FENCE", "FENCE2"):
        return "fencing"
    if pt in ("Electrical Permit", "Electrical Low Voltage",
              "Electrical Temporary Service"):
        return "electrical"
    if pt == "Plumbing Permit":
        return "plumbing"
    if pt == "Gas Permit":
        return "gas"
    if pt == "Erect/New Construction":
        return "new-construction"
    if wt in ("ELECTRICAL", "LVOLT", "TMPSER"):
        return "electrical"
    if wt == "PLUMBING":
        return "plumbing"
    if wt == "GAS":
        return "gas"
    if _contains(d, HVAC):
        return "hvac"
    if _contains(d, PLUMB):
        return "plumbing"
    if _contains(d, ELEC):
        return "electrical"
    if _contains(d, ROOF):
        return "roofing"
    return "general"


def classify_cincinnati_trade(components=()):
    """Cincinnati (data.cincinnati-oh.gov uhjb-xac9) trade classification.

    Input is the permit's SET of component labels — the city's feed lists
    one row per work component a permit covers, and the pipeline collapses
    those rows into one permit before classification (registry
    dedupe_rule). The component labels are themselves trade-bearing
    (Plumbing Permits, HVAC, Fire Protection Systems...), so the primary
    trade is chosen by precedence: a New Building component names the
    project's primary purpose and wins first (a new building with an HVAC
    component is a new-construction project — 24 such permits measured,
    plus 16 with excavation as well); the licensed trades named by
    components win next; a Wrecking component with no new building is a
    demolition (Excavation/Fill + Wrecking is its usual shape, 69
    permits). Alteration, Repair, Addition, Misc. Structures,
    Excavation/Fill, and Parking Lots name no licensed trade and land in
    'general' unless a trade component accompanies them (Alteration +
    HVAC is the commonest multi-component permit, 181 — classified
    hvac). The feed carries NO electrical component at all (zero rows
    mention electrical work — Cincinnati's dataset simply has none), so
    no electrical rule exists here. Deterministic, first match wins;
    permits no rule claims land in 'general' and are counted in the run
    report. Kept separate so other counties cannot be disturbed.
    """
    c = {str(x).strip() for x in (components or ()) if x}
    if "New Building" in c:
        return "new-construction"
    if "Plumbing Permits" in c:
        return "plumbing"
    if "HVAC" in c:
        return "hvac"
    if "Fire Protection Systems" in c:
        return "fire-protection"
    if "Signs" in c:
        return "signage"
    if "Elevator Permit" in c:
        return "elevator"
    if "Wrecking" in c:
        return "demolition"
    return "general"


import re as _re

_BR_SUFFIX_RE = _re.compile(r"\s*\([RC]\)\s*$")


def classify_br_trade(permit_type=""):
    """Baton Rouge (data.brla.gov 7fq7-8j7r, EBR Building Permits) trade
    classification.

    The parish's permittype names the permit family directly, and its
    (R)/(C) suffix restates the permit's Residential/Commercial
    designation, so classification is an exact match on the suffix-free
    type name — no description mining (the Cincinnati trap: free text
    misleads; the named families do not). The licensed-trade families the
    City-Parish files separately win their own trades (re-roof, electrical,
    gas test, plumbing, mechanical = HVAC, solar, fence, sign, demolition);
    generator permits are the parish's own permit family (239 window
    permits) and classify as their own trade, the treatment Boston gave
    its gas family. New Building (incl. the Shell Only variant) is new
    construction — matched by exact name so 'Cell Tower (New Const)'
    cannot leak in. Occupancy permits, the Existing Building
    remodel/addition family, accessory structures, and the long tail of
    use/site permits name no licensed trade and land in 'general'.
    Deterministic, first match wins; records no rule claims land in
    'general' and are counted in the run report. Kept separate so other
    counties cannot be disturbed.
    """
    base = _BR_SUFFIX_RE.sub("", (permit_type or "").strip()).strip()
    if base == "Re-Roof":
        return "roofing"
    if base == "Electrical Permit":
        return "electrical"
    if base == "Gas Test Permit":
        return "gas"
    if base == "Generator Permit":
        return "generator"
    if base in ("New Building Permit", "New Building", "New Building (Shell Only)"):
        return "new-construction"
    if base == "Demolition Permit":
        return "demolition"
    if base.startswith("Sign Permit"):
        return "signage"
    if base == "Plumbing Permit":
        return "plumbing"
    if base.startswith("Mechanical Permit"):
        return "hvac"
    if base == "Solar Permit":
        return "solar"
    if base == "Fence Permit":
        return "fencing"
    return "general"


def classify_sa_trade(components=()):
    """San Antonio (data.sanantonio.gov CKAN, Building Permits — PERMITS
    ISSUED) trade classification.

    Input is the permit's SET of PERMIT TYPE labels — the register's grain
    is one row per permit-type component an issuance covers (plus repeat
    submission rows), and the pipeline collapses those rows into one
    permit before classification (registry dedupe_rule). The type names
    are the city's own permit families, so classification is exact-match
    on the named families — no description mining exists to do (the
    register publishes no scope text at all). Precedence, first match
    wins: a new-building component names the project's primary purpose;
    demolition next (a demo with a utility disconnect is a demolition);
    then the licensed trades the city files as separate families
    (electrical, plumbing, gas, mechanical = HVAC); then roofing, solar,
    foundation, signage, fencing. Judgment calls, each measured against
    the 2026-10-18 window audit (73,739 scoped rows, 64,535 permits):

    * 'Plumbing Gas Permit' classifies as GAS, not plumbing: the work is
      gas-line installation (Boston treatment — the city's gas family is
      its own trade). 'Plumbing Medical Gas Permit' stays PLUMBING (a
      plumbing specialty, 99 permits).
    * 'Foundation Repair Permit' (3,208 permits) and 'Comm Foundation
      Permit' classify as FOUNDATION, their own trade — the source's own
      distinct permit family (the Boston gas / Baton Rouge generator
      treatment). Foundation work names no other licensed trade.
    * The repair/remodel/accessory/site families name no single licensed
      trade and land in 'general': Residential Repair, Minor Commercial
      Repair, Maintenance, Comm Remodel, Comm Addition, Home Addition,
      accessory buildings/dwellings, patios, carports, decks, pools,
      shade structures, retaining walls, pad sites, monuments, ice-teller
      machines, drive-thru aisles, equipment, manufactured homes,
      sitework, street improvement, sidewalk-curb, tree permits, building
      moves, pedestrian protection. Sampled 'general' volume is genuinely
      trade-less or multi-trade (remodels and repairs dominate).
    * Non-construction register families (garage sales, tree affidavits,
      temporary signs and banners) never reach this classifier — they are
      excluded by the registry's scope filter at pull time, and the
      exclusion is named and counted on the county pages.

    Deterministic; first match wins; permits no rule claims land in
    'general' and are counted in the run report. Kept separate so other
    counties cannot be disturbed.
    """
    c = {str(x).strip() for x in (components or ()) if x}
    if c & {"Res New Building Permit", "Comm New Building Permit",
            "Comm Shell Permit"}:
        return "new-construction"
    if c & {"Demolition Permit", "Billboard Demolition"}:
        return "demolition"
    if c & {"Electrical General Permit", "Electrical TOPS Permit",
            "Electrical TML Permit", "Electrical Reconnect Permit",
            "Electrical Completion Permit", "LSR Electrical Permit"}:
        return "electrical"
    if c & {"Plumbing General Permit", "Plumbing Irrigation Permit",
            "Plumbing Sewer Permit", "Plumbing Backflow Permit",
            "Plumbing Medical Gas Permit", "Plumbing Completion Permit",
            "LSR Plumbing Permit"}:
        return "plumbing"
    if "Plumbing Gas Permit" in c:
        return "gas"
    if c & {"Mechanical Permit", "LSR Mechanical Permit",
            "Mechanical Completion Permit"}:
        return "hvac"
    if "Re-Roof Permit" in c:
        return "roofing"
    if "Solar - Photovoltaic Permit" in c:
        return "solar"
    if c & {"Foundation Repair Permit", "Comm Foundation Permit"}:
        return "foundation"
    if c & {"On Premise Sign", "Off Premise Billboard"}:
        return "signage"
    if c & {"Residential Fence Permit", "Comm Fence Permit"}:
        return "fencing"
    return "general"


def classify_fort_worth_trade(permit_type="", permit_subtype=""):
    """Fort Worth (ArcGIS Hub, CFW Development Permits Table) trade
    classification.

    Input is ONE collapsed permit's Permit_Type (+ Permit_SubType) — the
    pipeline has already merged the permit's restated mirror rows by
    Permit_No, and a permit's rows never disagree on type or subtype
    (measured 2026-10-18), so classification is exact-match on the
    city's own permit families — no description mining (the Cincinnati
    trap: free text misleads; the named families do not).

    * The licensed-trade families the city files separately win their
      own trades: Plumbing, Electrical, Mechanical (= HVAC).
    * 'Plumbing Backflow' is the city's own distinct permit family
      (7,624 permits in the audit window; backflow-prevention assembly
      work is separately licensed in Texas) and classifies as BACKFLOW,
      its own trade — the treatment Boston gave its gas family and Baton
      Rouge its generator family.
    * The building families (Residential / Commercial Building Permit)
      classify as NEW-CONSTRUCTION only when the record's own SubType
      says 'New'; Remodel / Addition / Standalone / Umbrella subtypes
      name no single licensed trade and land in 'general', as do the
      accessory-structure families and Commercial Grading.
    * 'Design Review' never reaches this classifier — it is excluded
      by the registry's scope filter at pull time (a design-review
      approval authorizes no construction), and the exclusion is named
      and counted on the county pages.

    Deterministic; first match wins; permits no rule claims land in
    'general'. Kept separate so other counties cannot be disturbed.
    """
    t = (permit_type or "").strip()
    s = (permit_subtype or "").strip()
    if t == "Plumbing":
        return "plumbing"
    if t == "Plumbing Backflow":
        return "backflow"
    if t == "Electrical":
        return "electrical"
    if t == "Mechanical":
        return "hvac"
    if t in ("Residential Building Permit", "Commercial Building Permit"):
        return "new-construction" if s == "New" else "general"
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
