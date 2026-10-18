#!/usr/bin/env python3
"""Static page generator for live county pages (SOP section 6 page family).

Parametrized per county (CFG below): jurisdiction labels, coverage notes,
freshness stamps, and month windows all come from the county config + the
DB, never from hardcoded Chicago constants. Counties whose source valuation
field has not passed validation run with show_valuation=False and publish
counts only — no dollar figure is emitted anywhere for them (Austin /
Travis: see the valuation decision in PROGRESS.md, 2026-10-17 session).

Reads ONLY QA-passed, loaded data from engine/data/permits.db and emits:
  /[state]/[county]/                 county hub
  /[state]/[county]/[trade]/         trade pages (trades with real volume)
  /[state]/[county]/[yyyy-mm]/       monthly archives
and regenerates sitemap.xml with the new URLs appended.

Every figure carries its source + period (SOP section 8 citable stat blocks),
freshness stamps show source-last-updated and our-last-pull, and partial
months are labeled partial. No number appears here that is not in the DB.

Usage:
  python3 generate_pages.py [--county il/cook|tx/travis]
"""
import argparse
import calendar
import glob
import html
import json
import os
import sqlite3
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(ENGINE)
sys.path.insert(0, HERE)

# Pull stamps use the Pacific civil date (the site's session date convention:
# Chicago session 1 stamped October 17, 2026 while the pull ran Oct 18 UTC).
PULL_DATE = datetime.now(ZoneInfo("America/Los_Angeles")).date()
PULL_LABEL = f"{PULL_DATE.strftime('%B')} {PULL_DATE.day}, {PULL_DATE.year}"
TODAY_ISO = PULL_DATE.isoformat()

# Trade pages are built for trades with at least this many permits in the
# window ("sized to the data" — SOP: no thin or padded page families).
TRADE_PAGE_MIN = 100

TRADE_LABELS = {
    "electrical": "Electrical", "plumbing": "Plumbing", "hvac": "HVAC",
    "solar": "Solar", "roofing": "Roofing", "masonry": "Masonry",
    "signage": "Signage", "new-construction": "New Construction",
    "fire-alarm": "Fire Alarm", "elevator": "Elevator",
    "fencing": "Fencing", "demolition": "Demolition", "general": "General & Other",
    # NYC DOB NOW trades (scaffolding incl. sidewalk sheds is a first-class
    # NYC filing type; sprinklers/standpipe file as fire protection).
    "scaffolding": "Scaffolding", "fire-protection": "Fire Protection",
}

CFG = {
    "ca/san-francisco": {
        "registry": "san-francisco-ca",
        "state_name": "California", "state_abbr": "CA",
        "county_name": "San Francisco County", "crumb_county": "San Francisco County, California",
        "h1": "Building Permits in San Francisco, California",
        "city": "San Francisco",
        "source_short": "City and County of San Francisco",
        "source_line": "San Francisco open data (DataSF) — building permits issued by the Department of Building Inspection",
        "creator": "City and County of San Francisco",
        "cite_place": "San Francisco",
        "noun": "building permits", "noun_singular": "building permit",
        # SF costs passed validation on the deduped set (registry
        # field_map.valuation — 86% real-cost coverage, TTM sum verified
        # against the source to the dollar): values publish.
        "show_valuation": True, "show_category": False,
        "window_start": "2025-10-17",
        "lede_hub": ("Every building permit issued by the City and County of San Francisco — "
                     "counted, valued, and sorted by trade. Free, and updated nightly."),
        "coverage": ('<p class="note">Coverage: this report covers building permits issued by the '
                     '<strong>City and County of San Francisco</strong> (a consolidated city-county, '
                     'so the feed covers the whole county). One counting rule matters here: San '
                     'Francisco\'s Department of Building Inspection publishes one row for every '
                     'address or lot a permit touches, so one permit can appear several times in '
                     'the raw feed. We count each permit <strong>once</strong>, at the address the '
                     'department flags as primary — counts on this page are permits, never raw '
                     'feed rows.</p>'),
    },
    "wa/king": {
        "registry": "seattle-king-wa",
        "state_name": "Washington", "state_abbr": "WA",
        "county_name": "King County", "crumb_county": "King County, Washington",
        "h1": "Building Permits in King County, Washington",
        "city": "Seattle",
        "source_short": "City of Seattle",
        "source_line": "City of Seattle open data — building permits",
        "creator": "City of Seattle",
        "cite_place": "King County (Seattle)",
        "noun": "building permits", "noun_singular": "building permit",
        # Seattle's estprojectcost failed validation the Austin way: SDCI
        # stamps a development's full estimated cost onto each phase/sibling
        # permit (registry field_map.valuation — duplicated values over $1M
        # inject 38.5% excess into the raw sum, and no project-linkage field
        # exists to dedupe by): counts only, no dollar figures.
        "show_valuation": False, "show_category": True,
        "category_note": ("Category is the City of Seattle's own mapped class for each permit "
                          "(Residential / Non-Residential)."),
        "window_start": "2025-10-17",
        "lede_hub": ("Every building permit issued by the City of Seattle — counted and "
                     "sorted by trade, category, and month. Free, and updated daily."),
        "coverage": ('<p class="note">Coverage: this report covers building permits issued by the '
                     '<strong>City of Seattle</strong>, the largest jurisdiction in King County. '
                     'Other King County cities publish their permits separately and are not in '
                     'this feed, so totals here are Seattle totals — labeled as such, never blended. '
                     'County-wide coverage is not implied.</p>'),
    },
    "il/cook": {
        "registry": "chicago-cook-il",
        "state_name": "Illinois", "state_abbr": "IL",
        "county_name": "Cook County", "crumb_county": "Cook County, Illinois",
        "h1": "Building Permits in Cook County, Illinois",
        "city": "Chicago",
        "source_short": "City of Chicago",
        "source_line": "City of Chicago open data — building permits",
        "creator": "City of Chicago",
        "cite_place": "Cook County (Chicago)",
        "noun": "building permits", "noun_singular": "building permit",
        "show_valuation": True, "show_category": False,
        "window_start": "2025-10-17",
        "lede_hub": ("Every building permit issued by the City of Chicago — the county's largest "
                     "jurisdiction — counted, valued, and sorted by trade. Free, and updated daily."),
        "coverage": ('<p class="note">Coverage: this report covers building permits issued by the '
                     '<strong>City of Chicago</strong>, the largest jurisdiction in Cook County. '
                     'Suburban Cook County permits are published by separate municipalities and are '
                     'not in this feed yet, so county totals here are Chicago totals — labeled as such, '
                     'never blended.</p>'),
    },
    "tx/travis": {
        "registry": "austin-travis-tx",
        "state_name": "Texas", "state_abbr": "TX",
        "county_name": "Travis County", "crumb_county": "Travis County, Texas",
        "h1": "Building Permits in Travis County (Austin), Texas",
        "city": "Austin",
        "source_short": "City of Austin",
        "source_line": "City of Austin open data — issued construction permits",
        "creator": "City of Austin",
        "cite_place": "Travis County (Austin)",
        "noun": "construction permits", "noun_singular": "construction permit",
        # Austin's total_job_valuation failed validation (placeholders and
        # project values repeated across sibling permits — PROGRESS.md
        # 2026-10-17): counts only, no dollar figures, until it passes.
        "show_valuation": False, "show_category": True,
        "window_start": "2025-10-17",
        "lede_hub": ("Every construction permit issued by the City of Austin — counted and "
                     "sorted by trade, category, and month. Free, and updated daily."),
        "coverage": ('<p class="note">Coverage: this report covers construction permits issued by the '
                     '<strong>City of Austin</strong>. The city\'s permitting jurisdiction reaches '
                     'beyond the city limits — including its extraterritorial jurisdiction and a few '
                     'neighboring communities that use Austin\'s permitting — so totals here are '
                     'City of Austin feed totals for the Travis County report, labeled as such, '
                     'never blended with other jurisdictions\' records. County-wide coverage is '
                     'not implied.</p>'),
    },
    # New York City: one citywide DOB NOW feed, five boroughs = five
    # counties = five county reports (decision + evidence in the NYC
    # registries' dedupe_rule / coverage_note, PROGRESS.md session 5).
    # Values publish under the per-filing attribution rule (each filing's
    # stated estimated cost counted once, on its latest issuance in the
    # window) — the rule and its verification are in the registries and on
    # the Data Sources page. DOB NOW publishes no res/comm class: no
    # category figures. DOB NOW excludes electrical/elevator/LAA permits.
    "ny/new-york": {
        "registry": "nyc-new-york-ny",
        "state_name": "New York", "state_abbr": "NY",
        "county_name": "New York County", "crumb_county": "New York County, New York",
        "h1": "Building Permits in New York County (Manhattan), New York",
        "city": "Manhattan",
        "source_short": "NYC Department of Buildings",
        "source_line": "New York City open data — DOB NOW: Build, approved permits (NYC Department of Buildings)",
        "creator": "New York City Department of Buildings",
        "cite_place": "New York County (Manhattan)",
        "noun": "building permits", "noun_singular": "building permit",
        "show_valuation": True, "show_category": False,
        "window_start": "2025-10-17",
        "lede_hub": ("Every building permit issued by the New York City Department of Buildings "
                     "in Manhattan — counted, valued, and sorted by trade. Free, and updated daily."),
        "coverage": ('<p class="note">Coverage: this report covers building permits issued by the '
                     '<strong>New York City Department of Buildings (DOB NOW)</strong> in '
                     '<strong>Manhattan (New York County)</strong>. The city\'s other boroughs publish '
                     'as their own county reports: <a href="/ny/kings/">Kings County (Brooklyn)</a>, '
                     '<a href="/ny/queens/">Queens County</a>, <a href="/ny/bronx/">Bronx County</a>, '
                     'and <a href="/ny/richmond/">Richmond County (Staten Island)</a>. Two counting '
                     'rules matter here. DOB\'s feed lists one row for every work type an issuance '
                     'covers, so we count each issuance <strong>once</strong>. And the estimated cost '
                     'DOB publishes belongs to the whole job filing and repeats on each of its '
                     'issuances, so we count each filing\'s cost <strong>once</strong>, on its most '
                     'recent issuance. DOB NOW excludes electrical, elevator, and limited-alteration '
                     'permits — DOB publishes those in separate datasets — so no electrical figures '
                     'appear in this report.</p>'),
    },
    "ny/kings": {
        "registry": "nyc-kings-ny",
        "state_name": "New York", "state_abbr": "NY",
        "county_name": "Kings County", "crumb_county": "Kings County, New York",
        "h1": "Building Permits in Kings County (Brooklyn), New York",
        "city": "Brooklyn",
        "source_short": "NYC Department of Buildings",
        "source_line": "New York City open data — DOB NOW: Build, approved permits (NYC Department of Buildings)",
        "creator": "New York City Department of Buildings",
        "cite_place": "Kings County (Brooklyn)",
        "noun": "building permits", "noun_singular": "building permit",
        "show_valuation": True, "show_category": False,
        "window_start": "2025-10-17",
        "lede_hub": ("Every building permit issued by the New York City Department of Buildings "
                     "in Brooklyn — counted, valued, and sorted by trade. Free, and updated daily."),
        "coverage": ('<p class="note">Coverage: this report covers building permits issued by the '
                     '<strong>New York City Department of Buildings (DOB NOW)</strong> in '
                     '<strong>Brooklyn (Kings County)</strong>. The city\'s other boroughs publish '
                     'as their own county reports: <a href="/ny/new-york/">New York County (Manhattan)</a>, '
                     '<a href="/ny/queens/">Queens County</a>, <a href="/ny/bronx/">Bronx County</a>, '
                     'and <a href="/ny/richmond/">Richmond County (Staten Island)</a>. Two counting '
                     'rules matter here. DOB\'s feed lists one row for every work type an issuance '
                     'covers, so we count each issuance <strong>once</strong>. And the estimated cost '
                     'DOB publishes belongs to the whole job filing and repeats on each of its '
                     'issuances, so we count each filing\'s cost <strong>once</strong>, on its most '
                     'recent issuance. DOB NOW excludes electrical, elevator, and limited-alteration '
                     'permits — DOB publishes those in separate datasets — so no electrical figures '
                     'appear in this report.</p>'),
    },
    "ny/queens": {
        "registry": "nyc-queens-ny",
        "state_name": "New York", "state_abbr": "NY",
        "county_name": "Queens County", "crumb_county": "Queens County, New York",
        "h1": "Building Permits in Queens County, New York",
        "city": "Queens",
        "source_short": "NYC Department of Buildings",
        "source_line": "New York City open data — DOB NOW: Build, approved permits (NYC Department of Buildings)",
        "creator": "New York City Department of Buildings",
        "cite_place": "Queens County",
        "noun": "building permits", "noun_singular": "building permit",
        "show_valuation": True, "show_category": False,
        "window_start": "2025-10-17",
        "lede_hub": ("Every building permit issued by the New York City Department of Buildings "
                     "in Queens — counted, valued, and sorted by trade. Free, and updated daily."),
        "coverage": ('<p class="note">Coverage: this report covers building permits issued by the '
                     '<strong>New York City Department of Buildings (DOB NOW)</strong> in '
                     '<strong>Queens (Queens County)</strong>. The city\'s other boroughs publish '
                     'as their own county reports: <a href="/ny/new-york/">New York County (Manhattan)</a>, '
                     '<a href="/ny/kings/">Kings County (Brooklyn)</a>, <a href="/ny/bronx/">Bronx County</a>, '
                     'and <a href="/ny/richmond/">Richmond County (Staten Island)</a>. Two counting '
                     'rules matter here. DOB\'s feed lists one row for every work type an issuance '
                     'covers, so we count each issuance <strong>once</strong>. And the estimated cost '
                     'DOB publishes belongs to the whole job filing and repeats on each of its '
                     'issuances, so we count each filing\'s cost <strong>once</strong>, on its most '
                     'recent issuance. DOB NOW excludes electrical, elevator, and limited-alteration '
                     'permits — DOB publishes those in separate datasets — so no electrical figures '
                     'appear in this report.</p>'),
    },
    "ny/bronx": {
        "registry": "nyc-bronx-ny",
        "state_name": "New York", "state_abbr": "NY",
        "county_name": "Bronx County", "crumb_county": "Bronx County, New York",
        "h1": "Building Permits in Bronx County (the Bronx), New York",
        "city": "the Bronx",
        "source_short": "NYC Department of Buildings",
        "source_line": "New York City open data — DOB NOW: Build, approved permits (NYC Department of Buildings)",
        "creator": "New York City Department of Buildings",
        "cite_place": "Bronx County",
        "noun": "building permits", "noun_singular": "building permit",
        "show_valuation": True, "show_category": False,
        "window_start": "2025-10-17",
        "lede_hub": ("Every building permit issued by the New York City Department of Buildings "
                     "in the Bronx — counted, valued, and sorted by trade. Free, and updated daily."),
        "coverage": ('<p class="note">Coverage: this report covers building permits issued by the '
                     '<strong>New York City Department of Buildings (DOB NOW)</strong> in '
                     '<strong>the Bronx (Bronx County)</strong>. The city\'s other boroughs publish '
                     'as their own county reports: <a href="/ny/new-york/">New York County (Manhattan)</a>, '
                     '<a href="/ny/kings/">Kings County (Brooklyn)</a>, <a href="/ny/queens/">Queens County</a>, '
                     'and <a href="/ny/richmond/">Richmond County (Staten Island)</a>. Two counting '
                     'rules matter here. DOB\'s feed lists one row for every work type an issuance '
                     'covers, so we count each issuance <strong>once</strong>. And the estimated cost '
                     'DOB publishes belongs to the whole job filing and repeats on each of its '
                     'issuances, so we count each filing\'s cost <strong>once</strong>, on its most '
                     'recent issuance. DOB NOW excludes electrical, elevator, and limited-alteration '
                     'permits — DOB publishes those in separate datasets — so no electrical figures '
                     'appear in this report.</p>'),
    },
    "ny/richmond": {
        "registry": "nyc-richmond-ny",
        "state_name": "New York", "state_abbr": "NY",
        "county_name": "Richmond County", "crumb_county": "Richmond County, New York",
        "h1": "Building Permits in Richmond County (Staten Island), New York",
        "city": "Staten Island",
        "source_short": "NYC Department of Buildings",
        "source_line": "New York City open data — DOB NOW: Build, approved permits (NYC Department of Buildings)",
        "creator": "New York City Department of Buildings",
        "cite_place": "Richmond County (Staten Island)",
        "noun": "building permits", "noun_singular": "building permit",
        "show_valuation": True, "show_category": False,
        "window_start": "2025-10-17",
        "lede_hub": ("Every building permit issued by the New York City Department of Buildings "
                     "on Staten Island — counted, valued, and sorted by trade. Free, and updated daily."),
        "coverage": ('<p class="note">Coverage: this report covers building permits issued by the '
                     '<strong>New York City Department of Buildings (DOB NOW)</strong> on '
                     '<strong>Staten Island (Richmond County)</strong>. The city\'s other boroughs publish '
                     'as their own county reports: <a href="/ny/new-york/">New York County (Manhattan)</a>, '
                     '<a href="/ny/kings/">Kings County (Brooklyn)</a>, <a href="/ny/queens/">Queens County</a>, '
                     'and <a href="/ny/bronx/">Bronx County</a>. Two counting '
                     'rules matter here. DOB\'s feed lists one row for every work type an issuance '
                     'covers, so we count each issuance <strong>once</strong>. And the estimated cost '
                     'DOB publishes belongs to the whole job filing and repeats on each of its '
                     'issuances, so we count each filing\'s cost <strong>once</strong>, on its most '
                     'recent issuance. DOB NOW excludes electrical, elevator, and limited-alteration '
                     'permits — DOB publishes those in separate datasets — so no electrical figures '
                     'appear in this report.</p>'),
    },
}

CSS = """
:root{--navy:#102c40;--teal:#087f76;--teal-dark:#06685f;--bg:#f6f8f7;--ink:#16242e;--body:#2b3d47;--muted:#64757e;--border:#dfe7e3;--serif:"Playfair Display",Georgia,"Times New Roman",serif;--sans:"Source Sans 3","Segoe UI",Helvetica,Arial,sans-serif}
*{box-sizing:border-box}
body{margin:0;font-family:var(--sans);color:var(--body);background:#fff;-webkit-font-smoothing:antialiased}
a{color:var(--teal);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1200px;margin:0 auto;padding:0 24px}
header.site{background:#fff;border-bottom:1px solid #eef2f0}
.header-in{display:flex;align-items:center;justify-content:space-between;height:78px;gap:16px}
.logo{display:flex;align-items:center}
.logo img.full-logo{height:47px;width:auto;mix-blend-mode:multiply}
nav.main{display:flex;gap:26px;align-items:center}
nav.main a{color:var(--body);font-weight:600;font-size:15.5px}
nav.main a:hover{color:var(--teal);text-decoration:none}
nav.main a.cta{background:var(--teal);color:#fff;border-radius:7px;padding:10px 18px}
nav.main a.cta:hover{background:var(--teal-dark);color:#fff}
main .wrap{max-width:1020px}
.doc{padding-top:44px;padding-bottom:20px}
.eyebrow{font-size:13px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--teal);margin:0 0 12px}
h1{font-family:var(--serif);font-weight:800;color:var(--navy);font-size:44px;line-height:1.1;letter-spacing:-.015em;margin:0 0 14px}
.lede{font-size:19px;line-height:1.55;color:var(--body);margin:0 0 8px}
.stamp{font-size:14px;color:var(--muted);margin:0 0 6px}
h2{font-family:var(--serif);font-weight:800;color:var(--navy);font-size:27px;line-height:1.2;margin:34px 0 10px}
p{font-size:16.5px;line-height:1.65;margin:0 0 14px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:24px 0 6px}
.stat{background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:18px 20px}
.stat .num{font-family:var(--serif);font-weight:800;color:var(--navy);font-size:32px;line-height:1.05}
.stat .lab{font-size:14px;color:var(--muted);margin-top:5px}
table.data{width:100%;border-collapse:collapse;margin:14px 0 8px;font-size:15.5px}
table.data th{text-align:left;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);padding:8px 10px}
table.data td{border-bottom:1px solid var(--border);padding:9px 10px;vertical-align:top}
table.data td.n,table.data th.n{text-align:right;font-variant-numeric:tabular-nums}
.cite{background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:16px 20px;margin:22px 0;font-size:15px}
.qa{border:1px solid var(--border);border-radius:10px;padding:16px 20px;margin:12px 0}
.qa h3{margin:0 0 6px;font-size:17.5px;color:var(--navy)}
.qa p{margin:0;font-size:16px}
.note{font-size:14.5px;color:var(--muted)}
footer.site{background:#fff;border-top:1px solid #eef2f0;padding:24px 0 14px;margin-top:44px}
.foot-in{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}
.word{font-family:var(--serif);font-weight:800;font-size:20px;color:var(--navy);letter-spacing:-.01em;white-space:nowrap}
.foot-links{display:flex;gap:10px;align-items:center;padding-top:8px;flex-wrap:wrap;justify-content:flex-end}
.foot-links a{font-size:14.5px;font-weight:600;color:#54666f}
.foot-links a:hover{color:var(--teal);text-decoration:none}
.foot-links .dot{color:#b7c3c8}
.foot-line{text-align:center;color:#93a3ab;font-size:13.5px;margin:20px 0 4px}
@media (max-width:760px){
  .header-in{height:auto;padding-top:14px;padding-bottom:14px;flex-wrap:wrap}
  nav.main{gap:16px;flex-wrap:wrap}
  nav.main a{font-size:14.5px}
  h1{font-size:32px}
  .doc{padding-top:30px}
  table.data{font-size:14px}
  table.data td,table.data th{padding:7px 6px}
  .foot-in{flex-direction:column}
  .foot-links{justify-content:flex-start}
}
"""

HEADER = """<header class="site">
  <div class="wrap header-in">
    <a class="logo" href="/" aria-label="PermitsByCounty home"><img class="full-logo" src="/assets/logo-full.jpg" alt="PermitsByCounty" /></a>
    <nav class="main" aria-label="Main navigation">
      <a href="/#report">Explore counties</a>
      <a href="/data-sources">Our data</a>
      <a href="/about">About</a>
      <a class="cta" href="/#digest">Get the free digest</a>
    </nav>
  </div>
</header>"""

FOOTER = """<footer class="site">
  <div class="wrap">
    <div class="foot-in">
      <a class="logo" href="/" aria-label="PermitsByCounty home"><span class="word">PermitsByCounty</span></a>
      <div class="foot-links">
        <a href="/about">About</a><span class="dot">&middot;</span>
        <a href="/data-sources">Data &amp; methodology</a><span class="dot">&middot;</span>
        <a href="/corrections">Corrections</a><span class="dot">&middot;</span>
        <a href="/privacy">Privacy</a><span class="dot">&middot;</span>
        <a href="/terms">Terms</a><span class="dot">&middot;</span>
        <a href="/contact">Contact</a>
      </div>
    </div>
    <p class="foot-line">Independent public-record reporting. Not a government agency.</p>
  </div>
</footer>"""


def esc(s):
    return html.escape(str(s if s is not None else ""), quote=True)


def money_full(v):
    return f"${v:,.0f}" if v is not None else "—"


def money_short(v):
    if v is None:
        return "—"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.1f}M"
    if abs(v) >= 1e3:
        return f"${v / 1e3:.0f}K"
    return f"${v:,.0f}"


def month_label(ym):
    return datetime.strptime(ym, "%Y-%m").strftime("%B %Y")


def date_label(iso):
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def source_updated_label(registry):
    """Source-last-updated stamp: from the newest ingest report for the
    registry (the source's own dataset stamp recorded at pull time)."""
    reports = sorted(glob.glob(os.path.join(ENGINE, "data", "reports", f"{registry}-*.json")))
    for path in reversed(reports):
        try:
            with open(path) as fh:
                rep = json.load(fh)
            stamp = rep.get("source_updated_at")
            if stamp:
                return date_label(stamp[:10])
        except (OSError, ValueError):
            continue
    return PULL_LABEL


class Ctx:
    """Per-county generation context: config + DB-derived window facts."""

    def __init__(self, con, slug):
        self.slug = slug
        self.cfg = CFG[slug]
        self.county_id = con.execute("SELECT id FROM counties WHERE slug=?",
                                     (slug,)).fetchone()[0]
        months = con.execute("SELECT year_month, permit_count, total_valuation FROM monthly_aggregates "
                             "WHERE county_id=? AND trade IS NULL ORDER BY year_month",
                             (self.county_id,)).fetchall()
        self.months = months
        self.by_month = {m[0]: (m[1], m[2]) for m in months}
        self.first_month = months[0][0]
        self.current_month = months[-1][0]
        self.last_full_month = months[-2][0]
        self.data_through = con.execute("SELECT MAX(issue_date) FROM permits WHERE county_id=?",
                                        (self.county_id,)).fetchone()[0]
        self.data_through_label = date_label(self.data_through)
        d = datetime.strptime(self.data_through, "%Y-%m-%d").date()
        self.data_through_short = f"{d.strftime('%b')} {d.day}"
        ws = datetime.strptime(self.cfg["window_start"], "%Y-%m-%d").date()
        self.window_start_label = f"{ws.strftime('%B')} {ws.day}, {ws.year}"
        self.window_start_short = f"{ws.strftime('%b')} {ws.day}"
        self.source_updated = source_updated_label(self.cfg["registry"])
        self.val = self.cfg["show_valuation"]

    def month_note(self, ym):
        if ym == self.first_month:
            return f" (from {self.window_start_short})"
        if ym == self.current_month:
            return " (to date)"
        return ""

    def stamps(self):
        return (f'<p class="stamp">Source: {esc(self.cfg["source_line"])}. '
                f'Source last updated: {self.source_updated} &middot; Our last pull: {PULL_LABEL} &middot; '
                f'Figures are as reported by the {esc(self.cfg["source_short"])}.</p>')

    def partial_note(self, ym):
        if ym == self.first_month:
            y, m = int(ym[:4]), int(ym[5:7])
            last_day = calendar.monthrange(y, m)[1]
            ws = datetime.strptime(self.cfg["window_start"], "%Y-%m-%d").date()
            rng = f"{ws.strftime('%B')} {ws.day}–{last_day}, {y}"
            return ('<p class="note">Partial month: our coverage of this feed begins '
                    f'{self.window_start_label}, so this archive covers {rng}.</p>')
        if ym == self.current_month:
            if self.data_through == TODAY_ISO:
                return ('<p class="note">Month to date: figures run through '
                        f'{PULL_LABEL}, the date of our last pull.</p>')
            return ('<p class="note">Month to date: figures run through '
                    f'{self.data_through_label}, the latest date in the source data '
                    f'as of our {PULL_LABEL} pull.</p>')
        return ""


def page_shell(title, description, canonical, crumbs, ld_extra, body):
    crumbs_ld = {"@context": "https://schema.org", "@type": "BreadcrumbList",
                 "itemListElement": [{"@type": "ListItem", "position": i + 1,
                                      "name": n, "item": u} for i, (n, u) in enumerate(crumbs)]}
    lds = "\n".join(f'<script type="application/ld+json">{json.dumps(x)}</script>'
                    for x in [crumbs_ld] + ld_extra)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
<meta name="color-scheme" content="light" />
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}" />
<link rel="canonical" href="{canonical}" />
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;700;800&family=Source+Sans+3:wght@400;600;700&display=swap" rel="stylesheet" />
<style>{CSS}</style>
{lds}
</head>
<body>
{HEADER}
<main>
  <div class="wrap doc">
{body}
  </div>
</main>
{FOOTER}
</body>
</html>
"""


def dataset_ld(ctx, name, url, desc):
    return {"@context": "https://schema.org", "@type": "Dataset", "name": name,
            "description": desc, "url": url, "dateModified": TODAY_ISO,
            "creator": {"@type": "Organization", "name": ctx.cfg["creator"]},
            "publisher": {"@type": "Organization", "name": "PermitsByCounty",
                          "url": "https://permitsbycounty.com/"}}


def faq_ld(qas):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qas]}


def projects_table(con, county_id, where, params, limit=8):
    """Valuation-mode table: biggest projects by reported value."""
    rows = con.execute(
        "SELECT permit_number, address, trade, valuation, issue_date, project_description "
        f"FROM permits WHERE county_id=? AND valuation IS NOT NULL AND {where} "
        "ORDER BY valuation DESC LIMIT ?", (county_id, *params, limit)).fetchall()
    if not rows:
        return "<p>No valued projects in this period.</p>"
    out = ['<table class="data"><tr><th>Project (permit #)</th><th>Trade</th>'
           '<th class="n">Reported value</th><th>Issued</th></tr>']
    for num, addr, trade, val, iss, desc in rows:
        d = esc(desc or "")
        if len(d) > 110:
            d = d[:107] + "…"
        out.append(f"<tr><td><strong>{esc(addr or 'Address not published')}</strong> "
                   f"<span class='note'>#{esc(num)}</span><br><span class='note'>{d}</span></td>"
                   f"<td>{esc(TRADE_LABELS.get(trade, trade))}</td>"
                   f"<td class='n'>{money_full(val)}</td><td>{esc(iss)}</td></tr>")
    out.append("</table>")
    return "\n".join(out)


def recent_table(con, county_id, where, params, limit=8):
    """Counts-mode table: most recently issued permits (no dollar figures)."""
    rows = con.execute(
        "SELECT permit_number, address, trade, issue_date, project_description "
        f"FROM permits WHERE county_id=? AND {where} "
        "ORDER BY issue_date DESC, permit_number DESC LIMIT ?",
        (county_id, *params, limit)).fetchall()
    if not rows:
        return "<p>No permits in this period.</p>"
    out = ['<table class="data"><tr><th>Permit</th><th>Trade</th><th>Issued</th></tr>']
    for num, addr, trade, iss, desc in rows:
        d = esc(desc or "")
        if len(d) > 110:
            d = d[:107] + "…"
        out.append(f"<tr><td><strong>{esc(addr or 'Address not published')}</strong> "
                   f"<span class='note'>#{esc(num)}</span><br><span class='note'>{d}</span></td>"
                   f"<td>{esc(TRADE_LABELS.get(trade, trade))}</td><td>{esc(iss)}</td></tr>")
    out.append("</table>")
    return "\n".join(out)


def generate(con, slug):
    ctx = Ctx(con, slug)
    cfg = ctx.cfg
    county_id = ctx.county_id
    base = os.path.join(REPO, *slug.split("/"))
    os.makedirs(base, exist_ok=True)
    written = []
    city, src = cfg["city"], cfg["source_short"]
    noun = cfg["noun"]

    months = ctx.months
    total_12 = sum(m[1] for m in months)
    total_val_12 = sum(m[2] for m in months)
    cur_n, cur_v = ctx.by_month[ctx.current_month]
    last_n, last_v = ctx.by_month[ctx.last_full_month]
    trades_12 = con.execute("SELECT trade, COUNT(*), COALESCE(SUM(valuation),0) FROM permits "
                            "WHERE county_id=? GROUP BY trade ORDER BY 2 DESC",
                            (county_id,)).fetchall()
    paged_trades = {t for t, n, _ in trades_12 if t != "general" and n >= TRADE_PAGE_MIN}
    # "Top trade" names a real trade: when 'general' (the unclassified
    # bucket) leads a county — San Francisco, where most permits are small
    # alterations whose descriptions name no trade — the headline trade is
    # the largest classified one. Identical output where a real trade
    # already leads (Cook, Travis: electrical is #1 in both).
    top_trade = next((r for r in trades_12 if r[0] != "general"), trades_12[0])
    cite = (f"PermitsByCounty data, {cfg['cite_place']}, {month_label(ctx.last_full_month)} "
            f"· Source: {src}")
    hub_url = f"https://permitsbycounty.com/{slug}/"

    def trade_link(t, n):
        label = esc(TRADE_LABELS.get(t, t))
        if t in paged_trades:
            return f"<a href='/{slug}/{t}/'>{label}</a>"
        return label

    # --- hub --------------------------------------------------------------
    if ctx.val:
        qas = [
            (f"How many {noun} were issued in {city} in {month_label(ctx.last_full_month)}?",
             f"{last_n:,} {noun} were issued in {city} in {month_label(ctx.last_full_month)}, "
             f"with a reported project value of {money_full(last_v)}, as reported by the {src}."),
            (f"How many {noun} were issued in {city} in the last 12 months?",
             f"{total_12:,} {noun} were issued in {city} in the 12 months ending "
             f"{month_label(ctx.current_month)} ({ctx.data_through_label}), with a combined reported project value of "
             f"{money_full(total_val_12)}, as reported by the {src}."),
            (f"What is the most common type of building permit in {city}?",
             f"{TRADE_LABELS[top_trade[0]]} permits are the most common classified type: {top_trade[1]:,} issued in the last "
             f"12 months ({top_trade[1] / total_12 * 100:.1f}% of all permits), as reported by the {src}."),
        ]
        stats_html = f"""
      <div class="stat"><div class="num">{cur_n:,}</div><div class="lab">Permits issued in {month_label(ctx.current_month)} (to {ctx.data_through_short})</div></div>
      <div class="stat"><div class="num">{money_short(cur_v)}</div><div class="lab">Reported project value, {month_label(ctx.current_month)} to date</div></div>
      <div class="stat"><div class="num">{total_12:,}</div><div class="lab">Permits issued, last 12 months</div></div>
      <div class="stat"><div class="num">{esc(TRADE_LABELS[top_trade[0]])}</div><div class="lab">Top trade, last 12 months ({top_trade[1]:,} permits)</div></div>"""
        cite_html = (f"<strong>Citable figure:</strong> {city} issued {last_n:,} {noun} in "
                     f"{month_label(ctx.last_full_month)} with a reported project value of {money_full(last_v)}.<br>{esc(cite)}")
        month_rows = "\n".join(
            f"<tr><td><a href='/{slug}/{ym}/'>{month_label(ym)}</a>{ctx.month_note(ym)}</td>"
            f"<td class='n'>{n:,}</td><td class='n'>{money_full(v)}</td></tr>"
            for ym, n, v in reversed(months))
        month_head = '<th>Month</th><th class="n">Permits issued</th><th class="n">Reported value</th>'
        trade_rows = "\n".join(
            f"<tr><td>{trade_link(t, n)}</td>"
            f"<td class='n'>{n:,}</td><td class='n'>{n / total_12 * 100:.1f}%</td>"
            f"<td class='n'>{money_full(v)}</td></tr>"
            for t, n, v in trades_12)
        trade_head = '<th>Trade</th><th class="n">Permits</th><th class="n">Share</th><th class="n">Reported value</th>'
        projects_head = f"Biggest projects issued in {month_label(ctx.current_month)}"
        projects_html = projects_table(con, county_id, "substr(issue_date,1,7)=?", (ctx.current_month,))
        digest_line = "One free email a week with the county's new permits, biggest projects, and trade movements."
        hub_desc = (f"{city} {noun} for {cfg['county_name']}: {last_n:,} issued in {month_label(ctx.last_full_month)} "
                    f"({money_short(last_v)} reported value), permits by trade and month, biggest projects. "
                    "Free public-record reports, updated daily.")
        hub_title = (f"Building Permits in {cfg['county_name']} ({city}), {cfg['state_abbr']} "
                     "— Counts, Values & Trades | PermitsByCounty")
    else:
        qas = [
            (f"How many {noun} were issued in {city} in {month_label(ctx.last_full_month)}?",
             f"{last_n:,} {noun} were issued in {city} in {month_label(ctx.last_full_month)}, "
             f"as reported by the {src}."),
            (f"How many {noun} were issued in {city} in the last 12 months?",
             f"{total_12:,} {noun} were issued in {city} in the 12 months ending "
             f"{month_label(ctx.current_month)} ({ctx.data_through_label}), as reported by the {src}."),
            (f"What is the most common type of construction permit in {city}?",
             f"{TRADE_LABELS[top_trade[0]]} permits are the most common classified type: {top_trade[1]:,} issued in the last "
             f"12 months ({top_trade[1] / total_12 * 100:.1f}% of all permits), as reported by the {src}."),
        ]
        stats_html = f"""
      <div class="stat"><div class="num">{cur_n:,}</div><div class="lab">Permits issued in {month_label(ctx.current_month)} (to {ctx.data_through_short})</div></div>
      <div class="stat"><div class="num">{last_n:,}</div><div class="lab">Permits issued in {month_label(ctx.last_full_month)}</div></div>
      <div class="stat"><div class="num">{total_12:,}</div><div class="lab">Permits issued, last 12 months</div></div>
      <div class="stat"><div class="num">{esc(TRADE_LABELS[top_trade[0]])}</div><div class="lab">Top trade, last 12 months ({top_trade[1]:,} permits)</div></div>"""
        cite_html = (f"<strong>Citable figure:</strong> {city} issued {last_n:,} {noun} in "
                     f"{month_label(ctx.last_full_month)}.<br>{esc(cite)}")
        month_rows = "\n".join(
            f"<tr><td><a href='/{slug}/{ym}/'>{month_label(ym)}</a>{ctx.month_note(ym)}</td>"
            f"<td class='n'>{n:,}</td></tr>"
            for ym, n, v in reversed(months))
        month_head = '<th>Month</th><th class="n">Permits issued</th>'
        trade_rows = "\n".join(
            f"<tr><td>{trade_link(t, n)}</td>"
            f"<td class='n'>{n:,}</td><td class='n'>{n / total_12 * 100:.1f}%</td></tr>"
            for t, n, v in trades_12)
        trade_head = '<th>Trade</th><th class="n">Permits</th><th class="n">Share</th>'
        projects_head = f"Most recent permits issued in {month_label(ctx.current_month)}"
        projects_html = recent_table(con, county_id, "substr(issue_date,1,7)=?", (ctx.current_month,))
        digest_line = "One free email a week with the county's new permits, monthly counts, and trade movements."
        hub_desc = (f"{city} {noun} for {cfg['county_name']}: {last_n:,} issued in {month_label(ctx.last_full_month)}, "
                    "permits by trade, category and month, monthly archives. "
                    "Free public-record reports, updated daily.")
        hub_title = (f"Building Permits in {cfg['county_name']} ({city}), {cfg['state_abbr']} "
                     "— Counts & Trades | PermitsByCounty")

    category_html = ""
    if cfg["show_category"]:
        cats = con.execute("SELECT category, COUNT(*) FROM permits WHERE county_id=? "
                           "AND category IS NOT NULL GROUP BY category ORDER BY 2 DESC",
                           (county_id,)).fetchall()
        cat_rows = "\n".join(
            f"<tr><td>{esc(c.title())}</td><td class='n'>{n:,}</td>"
            f"<td class='n'>{n / total_12 * 100:.1f}%</td></tr>" for c, n in cats)
        category_html = f"""
    <h2>Permits by category — last 12 months</h2>
    <table class="data"><tr><th>Category</th><th class="n">Permits</th><th class="n">Share</th></tr>
    {cat_rows}
    </table>
    <p class="note">{esc(cfg.get('category_note') or f"Category is the {src}'s own residential / commercial class for each permit.")}</p>"""

    qa_html = "\n".join(f'<div class="qa"><h3>{esc(q)}</h3><p>{esc(a)}</p></div>' for q, a in qas)
    body = f"""
    <p class="eyebrow">County report &middot; {esc(cfg['state_name'])}</p>
    <h1>{esc(cfg['h1'])}</h1>
    <p class="lede">{esc(cfg['lede_hub'])}</p>
    {ctx.stamps()}
    {cfg['coverage']}
    <div class="stats">{stats_html}
    </div>
    <div class="cite">{cite_html}</div>
    <h2>Questions, answered from the data</h2>
    {qa_html}
    <h2>Permits by month</h2>
    <table class="data"><tr>{month_head}</tr>
    {month_rows}
    </table>
    <p class="note">{month_label(ctx.first_month)} coverage begins {ctx.window_start_label} (our first full pull); {month_label(ctx.current_month)} is month-to-date.</p>
    <h2>Permits by trade — last 12 months</h2>
    <table class="data"><tr>{trade_head}</tr>
    {trade_rows}
    </table>{category_html}
    <h2>{projects_head}</h2>
    {projects_html}
    <h2>Get the {esc(cfg['county_name'])} digest</h2>
    <p>{digest_line}
    <a href="/#digest">Sign up on the home page</a> — no spam, unsubscribe anytime.</p>
"""
    hub = page_shell(
        hub_title, hub_desc, hub_url,
        [("Home", "https://permitsbycounty.com/"), (cfg["crumb_county"], hub_url)],
        [dataset_ld(ctx, f"{cfg['cite_place']} {noun}", hub_url,
                    f"{noun.capitalize()} issued by the {src}, as reported by the {src}."),
         faq_ld(qas)],
        body)
    with open(os.path.join(base, "index.html"), "w") as fh:
        fh.write(hub)
    written.append(f"/{slug}/")

    # --- trade pages ------------------------------------------------------
    trade_months = {}
    for ym, trade, n, v in con.execute(
            "SELECT year_month, trade, permit_count, total_valuation FROM monthly_aggregates "
            "WHERE county_id=? AND trade IS NOT NULL", (county_id,)):
        trade_months.setdefault(trade, {})[ym] = (n, v)
    for trade, n12, v12 in trades_12:
        if trade not in paged_trades:
            continue
        label = TRADE_LABELS[trade]
        tm = trade_months.get(trade, {})
        sep_n, sep_v = tm.get(ctx.last_full_month, (0, 0))
        cmo_n, cmo_v = tm.get(ctx.current_month, (0, 0))
        if ctx.val:
            if sep_n:
                q = (f"How many {label.lower()} permits were issued in {city} in {month_label(ctx.last_full_month)}?",
                     f"{sep_n:,} {label.lower()} permits were issued in {city} in {month_label(ctx.last_full_month)}, "
                     f"with a reported project value of {money_full(sep_v)}, as reported by the {src}.")
            else:
                q = (f"How many {label.lower()} permits were issued in {city} in the last 12 months?",
                     f"{n12:,} {label.lower()} permits were issued in {city} in the 12 months ending "
                     f"{ctx.data_through_label}, as reported by the {src}.")
            t_stats = f"""
      <div class="stat"><div class="num">{n12:,}</div><div class="lab">{esc(label)} permits issued, last 12 months</div></div>
      <div class="stat"><div class="num">{money_short(v12)}</div><div class="lab">Reported project value, last 12 months</div></div>
      <div class="stat"><div class="num">{cmo_n:,}</div><div class="lab">Issued in {month_label(ctx.current_month)} (to {ctx.data_through_short})</div></div>
      <div class="stat"><div class="num">{n12 / total_12 * 100:.1f}%</div><div class="lab">Share of all {city} permits</div></div>"""
            t_cite = (f"<strong>Citable figure:</strong> {city} issued {sep_n:,} {label.lower()} permits in "
                      f"{month_label(ctx.last_full_month)}.<br>PermitsByCounty data, {cfg['cite_place']}, {month_label(ctx.last_full_month)} · Source: {src}")
            rows = "\n".join(
                f"<tr><td><a href='/{slug}/{ym}/'>{month_label(ym)}</a>{ctx.month_note(ym)}</td>"
                f"<td class='n'>{tm.get(ym, (0, 0))[0]:,}</td>"
                f"<td class='n'>{money_full(tm.get(ym, (0, 0))[1])}</td></tr>"
                for ym, _, _ in reversed(months))
            t_head = '<th>Month</th><th class="n">Permits issued</th><th class="n">Reported value</th>'
            t_projects_head = f"Biggest {label.lower()} projects — last 12 months"
            t_projects = projects_table(con, county_id, "trade=?", (trade,))
            t_lede = (f"{label} {noun} issued by the {src}, counted from the "
                      f"official record — totals, reported value, and the biggest {label.lower()} projects.")
            t_desc = (f"{label} {noun} issued in {city} ({cfg['county_name']}): {n12:,} in the last 12 months, "
                      f"monthly counts, reported values, and the biggest {label.lower()} projects. Free public-record data.")
        else:
            if sep_n:
                q = (f"How many {label.lower()} permits were issued in {city} in {month_label(ctx.last_full_month)}?",
                     f"{sep_n:,} {label.lower()} permits were issued in {city} in {month_label(ctx.last_full_month)}, "
                     f"as reported by the {src}.")
            else:
                q = (f"How many {label.lower()} permits were issued in {city} in the last 12 months?",
                     f"{n12:,} {label.lower()} permits were issued in {city} in the 12 months ending "
                     f"{ctx.data_through_label}, as reported by the {src}.")
            t_stats = f"""
      <div class="stat"><div class="num">{n12:,}</div><div class="lab">{esc(label)} permits issued, last 12 months</div></div>
      <div class="stat"><div class="num">{sep_n:,}</div><div class="lab">Issued in {month_label(ctx.last_full_month)}</div></div>
      <div class="stat"><div class="num">{cmo_n:,}</div><div class="lab">Issued in {month_label(ctx.current_month)} (to {ctx.data_through_short})</div></div>
      <div class="stat"><div class="num">{n12 / total_12 * 100:.1f}%</div><div class="lab">Share of all {city} permits</div></div>"""
            t_cite = (f"<strong>Citable figure:</strong> {city} issued {sep_n:,} {label.lower()} permits in "
                      f"{month_label(ctx.last_full_month)}.<br>PermitsByCounty data, {cfg['cite_place']}, {month_label(ctx.last_full_month)} · Source: {src}")
            rows = "\n".join(
                f"<tr><td><a href='/{slug}/{ym}/'>{month_label(ym)}</a>{ctx.month_note(ym)}</td>"
                f"<td class='n'>{tm.get(ym, (0, 0))[0]:,}</td></tr>"
                for ym, _, _ in reversed(months))
            t_head = '<th>Month</th><th class="n">Permits issued</th>'
            t_projects_head = f"Most recent {label.lower()} permits"
            t_projects = recent_table(con, county_id, "trade=?", (trade,))
            t_lede = (f"{label} {noun} issued by the {src}, counted from the "
                      f"official record — monthly totals and the most recent {label.lower()} permits.")
            t_desc = (f"{label} {noun} issued in {city} ({cfg['county_name']}): {n12:,} in the last 12 months, "
                      f"monthly counts and recent permits. Free public-record data.")
        url = f"https://permitsbycounty.com/{slug}/{trade}/"
        body = f"""
    <p class="eyebrow">Trade report &middot; {esc(cfg['county_name'])}, {esc(cfg['state_name'])}</p>
    <h1>{esc(label)} Permits in {esc(cfg['county_name'])} ({city})</h1>
    <p class="lede">{esc(t_lede)}</p>
    {ctx.stamps()}
    {cfg['coverage']}
    <div class="stats">{t_stats}
    </div>
    <div class="cite">{t_cite}</div>
    <h2>Questions, answered from the data</h2>
    <div class="qa"><h3>{esc(q[0])}</h3><p>{esc(q[1])}</p></div>
    <h2>{esc(label)} permits by month</h2>
    <table class="data"><tr>{t_head}</tr>
    {rows}
    </table>
    <h2>{t_projects_head}</h2>
    {t_projects}
    <p class="note">All {esc(cfg['county_name'])} trades: <a href="/{slug}/">full county report</a>.</p>
"""
        page = page_shell(
            f"{label} Permits in {cfg['county_name']} ({city}), {cfg['state_abbr']} | PermitsByCounty",
            t_desc, url,
            [("Home", "https://permitsbycounty.com/"), (cfg["crumb_county"], hub_url),
             (f"{label} permits", url)],
            [dataset_ld(ctx, f"{city} {label.lower()} {noun}", url,
                        f"{label} permits issued by the {src}, as reported by the {src}."),
             faq_ld([q])],
            body)
        d = os.path.join(base, trade)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as fh:
            fh.write(page)
        written.append(f"/{slug}/{trade}/")

    # --- monthly archives ---------------------------------------------------
    for ym, n, v in months:
        label_m = month_label(ym)
        tm_rows = con.execute(
            "SELECT trade, permit_count, total_valuation FROM monthly_aggregates "
            "WHERE county_id=? AND year_month=? AND trade IS NOT NULL ORDER BY permit_count DESC",
            (county_id, ym)).fetchall()
        top_t = tm_rows[0] if tm_rows else None
        if ctx.val:
            trows = "\n".join(
                f"<tr><td>{trade_link(t, c)}</td>"
                f"<td class='n'>{c:,}</td><td class='n'>{money_full(tv)}</td></tr>"
                for t, c, tv in tm_rows)
            m_head = '<th>Trade</th><th class="n">Permits issued</th><th class="n">Reported value</th>'
            m_stats = f"""
      <div class="stat"><div class="num">{n:,}</div><div class="lab">Permits issued, {label_m}</div></div>
      <div class="stat"><div class="num">{money_short(v)}</div><div class="lab">Reported project value</div></div>
      <div class="stat"><div class="num">{esc(TRADE_LABELS.get(top_t[0], top_t[0])) if top_t else '—'}</div><div class="lab">Top trade ({top_t[1]:,} permits)</div></div>"""
            m_cite = (f"<strong>Citable figure:</strong> {city} issued {n:,} {noun} in {label_m} "
                      f"with a reported project value of {money_full(v)}.<br>PermitsByCounty data, {cfg['cite_place']}, {label_m} · Source: {src}")
            top_proj = con.execute(
                "SELECT permit_number, address, valuation, project_description FROM permits "
                "WHERE county_id=? AND substr(issue_date,1,7)=? AND valuation IS NOT NULL "
                "ORDER BY valuation DESC LIMIT 1", (county_id, ym)).fetchone()
            qa = None
            if top_proj:
                qa = (f"What was the largest building permit issued in {city} in {label_m}?",
                      f"The largest was permit #{top_proj[0]} at {top_proj[1]}, with a reported project "
                      f"value of {money_full(top_proj[2])}, issued in {label_m}, as reported by the {src}.")
            m_projects_head = f"Biggest projects issued in {label_m}"
            m_projects = projects_table(con, county_id, "substr(issue_date,1,7)=?", (ym,), limit=10)
            m_lede = (f"Every {cfg['noun_singular']} issued by the {src} in {label_m}: counts, "
                      "reported value, permits by trade, and the month's biggest projects.")
            m_desc = (f"{n:,} {noun} were issued in {city} in {label_m} ({money_short(v)} reported value): "
                      "permits by trade and the month's biggest projects. Free public-record data.")
        else:
            trows = "\n".join(
                f"<tr><td>{trade_link(t, c)}</td>"
                f"<td class='n'>{c:,}</td></tr>"
                for t, c, tv in tm_rows)
            m_head = '<th>Trade</th><th class="n">Permits issued</th>'
            m_stats = f"""
      <div class="stat"><div class="num">{n:,}</div><div class="lab">Permits issued, {label_m}</div></div>
      <div class="stat"><div class="num">{esc(TRADE_LABELS.get(top_t[0], top_t[0])) if top_t else '—'}</div><div class="lab">Top trade ({top_t[1]:,} permits)</div></div>"""
            m_cite = (f"<strong>Citable figure:</strong> {city} issued {n:,} {noun} in {label_m}."
                      f"<br>PermitsByCounty data, {cfg['cite_place']}, {label_m} · Source: {src}")
            qa = (f"How many {noun} were issued in {city} in {label_m}?",
                  f"{n:,} {noun} were issued in {city} in {label_m}. The busiest trade was "
                  f"{TRADE_LABELS.get(top_t[0], top_t[0])} with {top_t[1]:,} permits, "
                  f"as reported by the {src}.") if top_t else None
            m_projects_head = f"Most recent permits issued in {label_m}"
            m_projects = recent_table(con, county_id, "substr(issue_date,1,7)=?", (ym,), limit=10)
            m_lede = (f"Every {cfg['noun_singular']} issued by the {src} in {label_m}: counts, "
                      "permits by trade, and the month's most recent permits.")
            m_desc = (f"{n:,} {noun} were issued in {city} in {label_m}: "
                      "permits by trade and the month's most recent permits. Free public-record data.")
        partial = ctx.partial_note(ym)
        url = f"https://permitsbycounty.com/{slug}/{ym}/"
        body = f"""
    <p class="eyebrow">Monthly archive &middot; {esc(cfg['county_name'])}, {esc(cfg['state_name'])}</p>
    <h1>{city} Building Permits — {label_m}</h1>
    <p class="lede">{esc(m_lede)}</p>
    {ctx.stamps()}
    {cfg['coverage']}
    {partial}
    <div class="stats">{m_stats}
    </div>
    <div class="cite">{m_cite}</div>
    {f'<h2>Questions, answered from the data</h2><div class="qa"><h3>{esc(qa[0])}</h3><p>{esc(qa[1])}</p></div>' if qa else ''}
    <h2>Permits by trade — {label_m}</h2>
    <table class="data"><tr>{m_head}</tr>
    {trows}
    </table>
    <h2>{m_projects_head}</h2>
    {m_projects}
    <p class="note">Full report: <a href="/{slug}/">{esc(cfg['county_name'])} ({city}) county hub</a>.</p>
"""
        lds = [dataset_ld(ctx, f"{city} {noun} {label_m}", url,
                          f"{noun.capitalize()} issued by the {src} in {label_m}.")]
        if qa:
            lds.append(faq_ld([qa]))
        page = page_shell(
            f"{city} Building Permits, {label_m} — {cfg['county_name']} | PermitsByCounty",
            m_desc, url,
            [("Home", "https://permitsbycounty.com/"), (cfg["crumb_county"], hub_url),
             (label_m, url)],
            lds, body)
        d = os.path.join(base, ym)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as fh:
            fh.write(page)
        written.append(f"/{slug}/{ym}/")

    # --- sitemap -------------------------------------------------------------
    sm_path = os.path.join(REPO, "sitemap.xml")
    with open(sm_path) as fh:
        sm = fh.read()
    entries = ""
    for path in written:
        loc = f"https://permitsbycounty.com{path}"
        if loc not in sm:
            pr = "0.9" if path == f"/{slug}/" else ("0.7" if path.count("/") == 3 else "0.6")
            entries += (f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{TODAY_ISO}</lastmod>\n"
                        f"    <priority>{pr}</priority>\n  </url>\n")
    if entries:
        sm = sm.replace("</urlset>", entries + "</urlset>")
        with open(sm_path, "w") as fh:
            fh.write(sm)
    print(f"[{slug}] wrote {len(written)} pages")
    for p in written:
        print(" ", p)
    print(f"hub stats: total12={total_12} cur={cur_n} last={last_n} top_trade={top_trade[0]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--county", default="il/cook", choices=sorted(CFG),
                    help="county slug to generate (default il/cook, the original behavior)")
    args = ap.parse_args()
    con = sqlite3.connect(os.path.join(ENGINE, "data", "permits.db"))
    generate(con, args.county)
    con.close()


if __name__ == "__main__":
    main()
