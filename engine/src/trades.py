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
