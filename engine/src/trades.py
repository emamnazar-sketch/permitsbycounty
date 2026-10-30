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


def classify_raleigh_trade(permit_type="", work_class="", proposed_use="",
                           description=""):
    """Raleigh (City of Raleigh ArcGIS, Building Permits) trade
    classification.

    Raleigh's layer is a BUILDING-permits feed: the city publishes its
    plumbing, electrical, and mechanical permits in separate datasets
    (the item description says so), and every window record's mapped
    type is 'Building' — so, as with Seattle, the trade signal lives in
    the record's own fields, in this precedence:

    * the source's own demolition naming wins first: permittype
      'Demolition' or a DEMOLITION proposed use. The bare word
      'demolition' in a scope description is NOT a signal — remodel
      descriptions use it for interior work ('demolition of the
      existing tub') — the Philadelphia / Boston trap, handled the
      same way. (Measured: the layer's Demolition-type records carry
      no issue date after 2021, so this rule fires once in the window.)
    * workclassmapped 'New' is new construction (the Cincinnati rule:
      a new building with trade work inside it is a new-construction
      project — 1,253 window permits).
    * a proposed use of 'MISCELLANEOUS SUCH AS FENCES' is the city's
      own fence family — fencing (224 window permits after the New
      rule; the Boston gas / San Antonio foundation treatment: the
      source's own distinct family gets its own trade).
    * then the scope description's trade keywords (solar, roofing,
      HVAC/mechanical, plumbing, electrical), most specific first.
    * everything else is 'general' — measured 64.7% of the window, and
      sampled general descriptions are genuinely trade-less (kitchen
      and bath remodels, foundation repairs, fit-ups, porches, decks).

    Deterministic; first match wins; permits no rule claims land in
    'general' and are counted in the run report. Kept separate so
    other counties cannot be disturbed. Simulated on the full window
    pull before build (2026-10-23): general 3,550 · new-construction
    1,253 · fencing 224 · plumbing 153 · electrical 128 · hvac 87 ·
    roofing 81 · solar 9 · demolition 1.
    """
    pt = (permit_type or "").strip()
    wc = (work_class or "").strip()
    pu = (proposed_use or "").upper()
    d = (description or "").lower()
    if pt == "Demolition" or "DEMOLITION" in pu:
        return "demolition"
    if wc == "New":
        return "new-construction"
    if "FENCES" in pu:
        return "fencing"
    if "solar" in d:
        return "solar"
    if _contains(d, ROOF):
        return "roofing"
    if _contains(d, ("hvac", "furnace", "air conditioning", "air conditioner",
                     "ductwork", "mechanical")):
        return "hvac"
    if _contains(d, ("plumbing", "water heater", "repipe", "sewer")):
        return "plumbing"
    if _contains(d, ("electrical", "electric service", "panel upgrade",
                     "ev charger")):
        return "electrical"
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


def classify_miami_trade(permit_type="", app_type="", comments="",
                         category1="", proposed_use=""):
    """Miami-Dade County (ArcGIS 'Building Permits Issued') trade
    classification.

    The county's PermitType is a family code: ELEC/MELE electrical,
    PLUM/MPLU plumbing, MECH/MMEC mechanical (HVAC), FIRE fire
    protection, LPGX/MLPG gas (LPG), ZIPS a miscellaneous family, and
    BLDG/MBLD the building family (BLDG = a standalone building permit,
    MBLD = a master building permit). The family code wins first,
    except for the county's solar families: roof-mounted and
    ground-mounted installation applications are filed as electrical
    permits and their comments are overwhelmingly solar/PV work
    (measured 2026-10-25), so those application types are solar
    wherever they appear.

    Inside the building family the trade signal is the county's own
    application type, then its category and scope text:
    * RE-ROOF/REPAIR and ROOF MAINTENANCE applications, and change-out
      scopes whose comment names a re-roof, are roofing. (The bare
      application types ALTER/REPAIR stay general unless the scope
      text names a trade — the interior-demo trap rule.)
    * DEMOLISH applications on building permits are demolition; the
      same application type on a trade-family permit is that trade's
      disconnect work and stays with its family (handled above).
    * FENCE NOMASONRY applications, a fence category, or a fence
      scope are fencing.
    * NEW and SHELL ONLY applications are new construction, except
      paving/open-lot work; FOUNDATION ONLY is foundation work.
    * a scope naming a sign is signage.
    ZIPS is the county's miscellaneous permit family — fences are its
    largest named category (fencing when its category or scope names
    a fence); awnings, canopies, paving, farm buildings and the rest
    stay general.

    Deterministic; first match wins; everything else is 'general'.
    Kept separate so other counties cannot be disturbed.
    """
    pt = (permit_type or "").strip().upper()
    at = (app_type or "").strip().upper()
    d = (comments or "").strip().upper()
    cat = (category1 or "").strip().upper()
    pu = (proposed_use or "").strip().upper()
    if at in ("ROOF MOUNTED INSTAL", "GROUND MOUNTED INSTA"):
        return "solar"
    if pt in ("ELEC", "MELE"):
        return "electrical"
    if pt in ("PLUM", "MPLU"):
        return "plumbing"
    if pt in ("MECH", "MMEC"):
        return "hvac"
    if pt == "FIRE":
        return "fire-protection"
    if pt in ("LPGX", "MLPG"):
        return "gas"
    if pt == "ZIPS":
        if "FENCE" in cat or "FENCE" in d:
            return "fencing"
        return "general"
    if pt in ("BLDG", "MBLD"):
        if at in ("RE-ROOF/REPAIR", "ROOF MAINTENANCE") or \
                any(k in d for k in ("REROOF", "RE-ROOF", "RE ROOF",
                                     "ROOFING", "NEW ROOF")):
            return "roofing"
        if at == "DEMOLISH":
            return "demolition"
        if at == "FENCE NOMASONRY" or cat == "FENCE" or "FENCE" in d:
            return "fencing"
        if at == "FOUNDATION ONLY":
            return "foundation"
        if at in ("NEW", "SHELL ONLY") and "PAVING" not in pu:
            return "new-construction"
        if "SIGN" in d:
            return "signage"
        return "general"
    return "general"


def classify_orlando_trade(application_type="", worktype=""):
    """Orlando (City of Orlando Socrata ryhf-m453) trade classification.

    The city's application_type names the licensed trade families
    directly (Electrical, Plumbing, Mechanical Permit, GAS, Fire
    Permit, Demolition Permit) — those win, except solar: a Solar
    worktype is filed under the Electrical, Building, and Plumbing
    families alike (218 window permits) and is the city's own solar
    family wherever it appears (the Miami solar rule). Inside the
    Building family the worktype separates roofing (Roof), fencing
    (Fence), signage (Sign), and new construction (New); inside
    Engineering, SFR (single-family residence site permits) is new
    construction. Everything else — Building repair/alteration/pool/
    accessory work, Engineering site work, and FloodPlain elevation
    certificates — is 'general'.

    Cross-tab measured on the full window 2026-10-27 (see registry
    audit). Deterministic; first match wins. Kept separate so other
    counties cannot be disturbed. Simulated totals: electrical 6,119 ·
    hvac 3,970 · plumbing 3,439 · roofing 3,131 · new-construction
    1,943 · fire-protection 1,733 · general 6,227 · fencing 540 ·
    gas 455 · signage 407 · demolition 242 · solar 218.
    """
    at = (application_type or "").strip()
    wt = (worktype or "").strip()
    if at == "Demolition Permit":
        return "demolition"
    if wt == "Solar":
        return "solar"
    if at == "Electrical":
        return "electrical"
    if at == "Plumbing":
        return "plumbing"
    if at == "Mechanical Permit":
        return "hvac"
    if at == "GAS":
        return "gas"
    if at == "Fire Permit":
        return "fire-protection"
    if at == "Building Permit":
        if wt == "Roof":
            return "roofing"
        if wt == "Fence":
            return "fencing"
        if wt == "Sign":
            return "signage"
        if wt == "New":
            return "new-construction"
        return "general"
    if at == "Engineering" and wt == "SFR":
        return "new-construction"
    return "general"


def classify_hillsborough_trade(permit_type="", description=""):
    """Hillsborough County (ArcGIS Accela dashboard extract) trade
    classification.

    The county's TYPE names eight families and none of them is a
    licensed trade: Residential/Commercial New Construction, Addition,
    Building Alterations (Renovations), and Miscellaneous. Following
    the Fort Worth / Cincinnati discipline, classification starts from
    the source's own naming — a New Construction type is new
    construction — and the scope description is mined ONLY for strong,
    specific signals, in this precedence:

    * solar anywhere in the scope;
    * a sign installation (install/new/replace + sign, or 'signage') —
      signs are a real Hillsborough miscellaneous family (measured
      325 window permits), and sign scopes that mention connecting to
      existing electrical are sign permits, not electrical permits,
      so this rule fires before the electrical rule;
    * strong roofing signals only (re-roof / reroof / roof
      replacement / roofing / new roof) — a screen enclosure's roof
      or a roof-mounted stand is not a roofing permit and does not
      qualify (the Philadelphia interior-demo trap, roofing shape);
    * demolition as the permit's primary work (scope opens with
      demo/demolition, or names demolishing a structure) — interior
      demo inside a remodel is alteration work, not demolition;
    * fire sprinkler / fire alarm scopes;
    * strong HVAC signals (the letters HVAC, furnace, an air
      conditioning system, a condensing unit, ductwork) — a room
      named for A/C is not HVAC work and carries none of these;
    * strong plumbing signals (water heater, repipe) and strong
      electrical signals (service upgrade, panel upgrade, EV
      charger, electrical service) — a remodel scope that merely
      mentions plumbing or electrical among many trades stays
      general, as in San Antonio, where pools, screen enclosures,
      sheds, additions, and renovations likewise land in general.

    Simulated on the full window pull before build (2026-10-29):
    general 6,364 · new-construction 2,640 · signage 325 · roofing
    116 · hvac 102 · demolition 54 · electrical 38 · solar 35 ·
    plumbing 30 · fire-protection 14. Deterministic; first match
    wins; kept separate so other counties cannot be disturbed.
    """
    import re as _re_h
    t = (permit_type or "").strip().lower()
    d = (description or "").lower()
    if "new construction" in t:
        return "new-construction"
    if "solar" in d:
        return "solar"
    if _re_h.search(r"(install\w*|new|replace\w*|refac\w*|rebrand\w*)"
                    r".{0,40}\bsign", d) or "signage" in d \
            or d.strip().startswith("sign"):
        return "signage"
    if any(k in d for k in ("re-roof", "reroof", "re roof",
                            "roof replacement", "roofing", "new roof",
                            "replace roof")):
        return "roofing"
    if _re_h.match(r"\s*(demo|demolition|demolish)", d) \
            or "demolish" in d \
            or _re_h.search(r"demolition of (an?|the) (existing )?"
                            r"(house|home|building|structure|residence|"
                            r"mobile|commercial)", d):
        return "demolition"
    if "fire sprinkler" in d or "fire alarm" in d:
        return "fire-protection"
    if any(k in d for k in ("hvac", "furnace", "air conditioning system",
                            "condensing unit", "ductwork")):
        return "hvac"
    if any(k in d for k in ("water heater", "repipe", "repiping")):
        return "plumbing"
    if any(k in d for k in ("service upgrade", "panel upgrade",
                            "ev charger", "electrical service")):
        return "electrical"
    return "general"
