#!/usr/bin/env python3
"""Static page generator for live county pages (SOP section 6 page family).

Reads ONLY QA-passed, loaded data from engine/data/permits.db and emits:
  /[state]/[county]/                 county hub
  /[state]/[county]/[trade]/         trade pages (trades with real volume)
  /[state]/[county]/[yyyy-mm]/       monthly archives
and regenerates sitemap.xml with the new URLs appended.

Every figure carries its source + period (SOP section 8 citable stat blocks),
freshness stamps show source-last-updated and our-last-pull, and partial
months are labeled partial. No number appears here that is not in the DB.
"""
import html
import json
import os
import sqlite3
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(ENGINE)
sys.path.insert(0, HERE)

PULL_LABEL = "October 17, 2026"
SOURCE_UPDATED_LABEL = "October 17, 2026"
TODAY_ISO = "2026-10-17"
FIRST_MONTH = "2025-10"   # coverage begins Oct 17, 2025 -> partial month
CURRENT_MONTH = "2026-10"  # month-to-date through Oct 17, 2026
LAST_FULL_MONTH = "2026-09"

TRADE_LABELS = {
    "electrical": "Electrical", "plumbing": "Plumbing", "hvac": "HVAC",
    "solar": "Solar", "roofing": "Roofing", "masonry": "Masonry",
    "signage": "Signage", "new-construction": "New Construction",
    "fire-alarm": "Fire Alarm", "elevator": "Elevator",
    "fencing": "Fencing", "demolition": "Demolition", "general": "General & Other",
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


def month_note(ym):
    if ym == FIRST_MONTH:
        return " (from Oct 17)"
    if ym == CURRENT_MONTH:
        return " (to date)"
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


def dataset_ld(name, url, desc):
    return {"@context": "https://schema.org", "@type": "Dataset", "name": name,
            "description": desc, "url": url, "dateModified": TODAY_ISO,
            "creator": {"@type": "Organization", "name": "City of Chicago"},
            "publisher": {"@type": "Organization", "name": "PermitsByCounty",
                          "url": "https://permitsbycounty.com/"}}


def faq_ld(qas):
    return {"@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": q,
                            "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qas]}


def stamps():
    return (f'<p class="stamp">Source: City of Chicago open data — building permits. '
            f'Source last updated: {SOURCE_UPDATED_LABEL} &middot; Our last pull: {PULL_LABEL} &middot; '
            f'Figures are as reported by the City of Chicago.</p>')


def coverage_note():
    return ('<p class="note">Coverage: this report covers building permits issued by the '
            '<strong>City of Chicago</strong>, the largest jurisdiction in Cook County. '
            'Suburban Cook County permits are published by separate municipalities and are '
            'not in this feed yet, so county totals here are Chicago totals — labeled as such, '
            'never blended.</p>')


def projects_table(con, county_id, where, params, limit=8):
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


def main():
    con = sqlite3.connect(os.path.join(ENGINE, "data", "permits.db"))
    county_id = con.execute("SELECT id FROM counties WHERE slug='il/cook'").fetchone()[0]
    base = os.path.join(REPO, "il", "cook")
    os.makedirs(base, exist_ok=True)
    written = []

    # --- aggregates -------------------------------------------------------
    months = con.execute("SELECT year_month, permit_count, total_valuation FROM monthly_aggregates "
                         "WHERE county_id=? AND trade IS NULL ORDER BY year_month",
                         (county_id,)).fetchall()
    total_12 = sum(m[1] for m in months)
    total_val_12 = sum(m[2] for m in months)
    by_month = {m[0]: (m[1], m[2]) for m in months}
    cur_n, cur_v = by_month[CURRENT_MONTH]
    last_n, last_v = by_month[LAST_FULL_MONTH]
    trades_12 = con.execute("SELECT trade, COUNT(*), COALESCE(SUM(valuation),0) FROM permits "
                            "WHERE county_id=? GROUP BY trade ORDER BY 2 DESC",
                            (county_id,)).fetchall()
    top_trade = trades_12[0]
    cite = (f"PermitsByCounty data, Cook County (Chicago), {month_label(LAST_FULL_MONTH)} "
            f"· Source: City of Chicago")

    # --- hub --------------------------------------------------------------
    qas = [
        (f"How many building permits were issued in Chicago in {month_label(LAST_FULL_MONTH)}?",
         f"{last_n:,} building permits were issued in Chicago in {month_label(LAST_FULL_MONTH)}, "
         f"with a reported project value of {money_full(last_v)}, as reported by the City of Chicago."),
        ("How many building permits were issued in Chicago in the last 12 months?",
         f"{total_12:,} building permits were issued in Chicago in the 12 months ending "
         f"{month_label(CURRENT_MONTH)} (October 17, 2026), with a combined reported project value of "
         f"{money_full(total_val_12)}, as reported by the City of Chicago."),
        ("What is the most common type of building permit in Chicago?",
         f"Electrical permits are the most common classified type: {top_trade[1]:,} issued in the last "
         f"12 months ({top_trade[1] / total_12 * 100:.1f}% of all permits), as reported by the City of Chicago."),
    ]
    month_rows = "\n".join(
        f"<tr><td><a href='/il/cook/{ym}/'>{month_label(ym)}</a>{month_note(ym)}</td>"
        f"<td class='n'>{n:,}</td><td class='n'>{money_full(v)}</td></tr>"
        for ym, n, v in reversed(months))
    trade_rows = "\n".join(
        (f"<tr><td><a href='/il/cook/{t}/'>{esc(TRADE_LABELS.get(t, t))}</a></td>"
         f"<td class='n'>{n:,}</td><td class='n'>{n / total_12 * 100:.1f}%</td>"
         f"<td class='n'>{money_full(v)}</td></tr>") if t != "general" else
        (f"<tr><td>{esc(TRADE_LABELS.get(t, t))}</td>"
         f"<td class='n'>{n:,}</td><td class='n'>{n / total_12 * 100:.1f}%</td>"
         f"<td class='n'>{money_full(v)}</td></tr>")
        for t, n, v in trades_12)
    qa_html = "\n".join(f'<div class="qa"><h3>{esc(q)}</h3><p>{esc(a)}</p></div>' for q, a in qas)
    body = f"""
    <p class="eyebrow">County report &middot; Illinois</p>
    <h1>Building Permits in Cook County, Illinois</h1>
    <p class="lede">Every building permit issued by the City of Chicago — the county's largest
    jurisdiction — counted, valued, and sorted by trade. Free, and updated daily.</p>
    {stamps()}
    {coverage_note()}
    <div class="stats">
      <div class="stat"><div class="num">{cur_n:,}</div><div class="lab">Permits issued in October 2026 (to Oct 17)</div></div>
      <div class="stat"><div class="num">{money_short(cur_v)}</div><div class="lab">Reported project value, October 2026 to date</div></div>
      <div class="stat"><div class="num">{total_12:,}</div><div class="lab">Permits issued, last 12 months</div></div>
      <div class="stat"><div class="num">{esc(TRADE_LABELS[top_trade[0]])}</div><div class="lab">Top trade, last 12 months ({top_trade[1]:,} permits)</div></div>
    </div>
    <div class="cite"><strong>Citable figure:</strong> Chicago issued {last_n:,} building permits in
    {month_label(LAST_FULL_MONTH)} with a reported project value of {money_full(last_v)}.<br>{esc(cite)}</div>
    <h2>Questions, answered from the data</h2>
    {qa_html}
    <h2>Permits by month</h2>
    <table class="data"><tr><th>Month</th><th class="n">Permits issued</th><th class="n">Reported value</th></tr>
    {month_rows}
    </table>
    <p class="note">October 2025 coverage begins October 17, 2025 (our first full pull); October 2026 is month-to-date.</p>
    <h2>Permits by trade — last 12 months</h2>
    <table class="data"><tr><th>Trade</th><th class="n">Permits</th><th class="n">Share</th><th class="n">Reported value</th></tr>
    {trade_rows}
    </table>
    <h2>Biggest projects issued in October 2026</h2>
    {projects_table(con, county_id, "substr(issue_date,1,7)=?", (CURRENT_MONTH,))}
    <h2>Get the Cook County digest</h2>
    <p>One free email a week with the county's new permits, biggest projects, and trade movements.
    <a href="/#digest">Sign up on the home page</a> — no spam, unsubscribe anytime.</p>
"""
    hub_url = "https://permitsbycounty.com/il/cook/"
    hub = page_shell(
        "Building Permits in Cook County (Chicago), IL — Counts, Values & Trades | PermitsByCounty",
        f"Chicago building permits for Cook County: {last_n:,} issued in {month_label(LAST_FULL_MONTH)} "
        f"({money_short(last_v)} reported value), permits by trade and month, biggest projects. "
        "Free public-record reports, updated daily.",
        hub_url,
        [("Home", "https://permitsbycounty.com/"), ("Cook County, Illinois", hub_url)],
        [dataset_ld("Cook County (Chicago) building permits", hub_url,
                    "Building permits issued by the City of Chicago, as reported by the City of Chicago."),
         faq_ld(qas)],
        body)
    with open(os.path.join(base, "index.html"), "w") as fh:
        fh.write(hub)
    written.append("/il/cook/")

    # --- trade pages ------------------------------------------------------
    trade_months = {}
    for ym, trade, n, v in con.execute(
            "SELECT year_month, trade, permit_count, total_valuation FROM monthly_aggregates "
            "WHERE county_id=? AND trade IS NOT NULL", (county_id,)):
        trade_months.setdefault(trade, {})[ym] = (n, v)
    for trade, n12, v12 in trades_12:
        if trade == "general":
            continue
        label = TRADE_LABELS[trade]
        tm = trade_months.get(trade, {})
        sep_n, sep_v = tm.get(LAST_FULL_MONTH, (0, 0))
        cmo_n, cmo_v = tm.get(CURRENT_MONTH, (0, 0))
        if sep_n:
            q = (f"How many {label.lower()} permits were issued in Chicago in {month_label(LAST_FULL_MONTH)}?",
                 f"{sep_n:,} {label.lower()} permits were issued in Chicago in {month_label(LAST_FULL_MONTH)}, "
                 f"with a reported project value of {money_full(sep_v)}, as reported by the City of Chicago.")
        else:
            q = (f"How many {label.lower()} permits were issued in Chicago in the last 12 months?",
                 f"{n12:,} {label.lower()} permits were issued in Chicago in the 12 months ending "
                 f"October 17, 2026, as reported by the City of Chicago.")
        rows = "\n".join(
            f"<tr><td><a href='/il/cook/{ym}/'>{month_label(ym)}</a>{month_note(ym)}</td>"
            f"<td class='n'>{tm.get(ym, (0, 0))[0]:,}</td>"
            f"<td class='n'>{money_full(tm.get(ym, (0, 0))[1])}</td></tr>"
            for ym, _, _ in reversed(months))
        url = f"https://permitsbycounty.com/il/cook/{trade}/"
        body = f"""
    <p class="eyebrow">Trade report &middot; Cook County, Illinois</p>
    <h1>{esc(label)} Permits in Cook County (Chicago)</h1>
    <p class="lede">{esc(label)} building permits issued by the City of Chicago, counted from the
    official record — totals, reported value, and the biggest {label.lower()} projects.</p>
    {stamps()}
    {coverage_note()}
    <div class="stats">
      <div class="stat"><div class="num">{n12:,}</div><div class="lab">{esc(label)} permits issued, last 12 months</div></div>
      <div class="stat"><div class="num">{money_short(v12)}</div><div class="lab">Reported project value, last 12 months</div></div>
      <div class="stat"><div class="num">{cmo_n:,}</div><div class="lab">Issued in October 2026 (to Oct 17)</div></div>
      <div class="stat"><div class="num">{n12 / total_12 * 100:.1f}%</div><div class="lab">Share of all Chicago permits</div></div>
    </div>
    <div class="cite"><strong>Citable figure:</strong> Chicago issued {sep_n:,} {label.lower()} permits in
    {month_label(LAST_FULL_MONTH)}.<br>PermitsByCounty data, Cook County (Chicago), {month_label(LAST_FULL_MONTH)} · Source: City of Chicago</div>
    <h2>Questions, answered from the data</h2>
    <div class="qa"><h3>{esc(q[0])}</h3><p>{esc(q[1])}</p></div>
    <h2>{esc(label)} permits by month</h2>
    <table class="data"><tr><th>Month</th><th class="n">Permits issued</th><th class="n">Reported value</th></tr>
    {rows}
    </table>
    <h2>Biggest {label.lower()} projects — last 12 months</h2>
    {projects_table(con, county_id, "trade=?", (trade,))}
    <p class="note">All Cook County trades: <a href="/il/cook/">full county report</a>.</p>
"""
        page = page_shell(
            f"{label} Permits in Cook County (Chicago), IL | PermitsByCounty",
            f"{label} building permits issued in Chicago (Cook County): {n12:,} in the last 12 months, "
            f"monthly counts, reported values, and the biggest {label.lower()} projects. Free public-record data.",
            url,
            [("Home", "https://permitsbycounty.com/"), ("Cook County, Illinois", hub_url),
             (f"{label} permits", url)],
            [dataset_ld(f"Chicago {label.lower()} building permits", url,
                        f"{label} permits issued by the City of Chicago, as reported by the City of Chicago."),
             faq_ld([q])],
            body)
        d = os.path.join(base, trade)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as fh:
            fh.write(page)
        written.append(f"/il/cook/{trade}/")

    # --- monthly archives ---------------------------------------------------
    for ym, n, v in months:
        label_m = month_label(ym)
        tm_rows = con.execute(
            "SELECT trade, permit_count, total_valuation FROM monthly_aggregates "
            "WHERE county_id=? AND year_month=? AND trade IS NOT NULL ORDER BY permit_count DESC",
            (county_id, ym)).fetchall()
        top_t = tm_rows[0] if tm_rows else None
        trows = "\n".join(
            (f"<tr><td><a href='/il/cook/{t}/'>{esc(TRADE_LABELS.get(t, t))}</a></td>"
             f"<td class='n'>{c:,}</td><td class='n'>{money_full(tv)}</td></tr>") if t != "general" else
            (f"<tr><td>{esc(TRADE_LABELS.get(t, t))}</td>"
             f"<td class='n'>{c:,}</td><td class='n'>{money_full(tv)}</td></tr>")
            for t, c, tv in tm_rows)
        top_proj = con.execute(
            "SELECT permit_number, address, valuation, project_description FROM permits "
            "WHERE county_id=? AND substr(issue_date,1,7)=? AND valuation IS NOT NULL "
            "ORDER BY valuation DESC LIMIT 1", (county_id, ym)).fetchone()
        qa = None
        if top_proj:
            qa = (f"What was the largest building permit issued in Chicago in {label_m}?",
                  f"The largest was permit #{top_proj[0]} at {top_proj[1]}, with a reported project "
                  f"value of {money_full(top_proj[2])}, issued in {label_m}, as reported by the City of Chicago.")
        partial = ""
        if ym == FIRST_MONTH:
            partial = ('<p class="note">Partial month: our coverage of this feed begins October 17, 2025, '
                       'so this archive covers October 17–31, 2025.</p>')
        if ym == CURRENT_MONTH:
            partial = ('<p class="note">Month to date: figures run through October 17, 2026, '
                       'the date of our last pull.</p>')
        url = f"https://permitsbycounty.com/il/cook/{ym}/"
        body = f"""
    <p class="eyebrow">Monthly archive &middot; Cook County, Illinois</p>
    <h1>Chicago Building Permits — {label_m}</h1>
    <p class="lede">Every building permit issued by the City of Chicago in {label_m}: counts,
    reported value, permits by trade, and the month's biggest projects.</p>
    {stamps()}
    {coverage_note()}
    {partial}
    <div class="stats">
      <div class="stat"><div class="num">{n:,}</div><div class="lab">Permits issued, {label_m}</div></div>
      <div class="stat"><div class="num">{money_short(v)}</div><div class="lab">Reported project value</div></div>
      <div class="stat"><div class="num">{esc(TRADE_LABELS.get(top_t[0], top_t[0])) if top_t else '—'}</div><div class="lab">Top trade ({top_t[1]:,} permits)</div></div>
    </div>
    <div class="cite"><strong>Citable figure:</strong> Chicago issued {n:,} building permits in {label_m}
    with a reported project value of {money_full(v)}.<br>PermitsByCounty data, Cook County (Chicago), {label_m} · Source: City of Chicago</div>
    {f'<h2>Questions, answered from the data</h2><div class="qa"><h3>{esc(qa[0])}</h3><p>{esc(qa[1])}</p></div>' if qa else ''}
    <h2>Permits by trade — {label_m}</h2>
    <table class="data"><tr><th>Trade</th><th class="n">Permits issued</th><th class="n">Reported value</th></tr>
    {trows}
    </table>
    <h2>Biggest projects issued in {label_m}</h2>
    {projects_table(con, county_id, "substr(issue_date,1,7)=?", (ym,), limit=10)}
    <p class="note">Full report: <a href="/il/cook/">Cook County (Chicago) county hub</a>.</p>
"""
        lds = [dataset_ld(f"Chicago building permits {label_m}", url,
                          f"Building permits issued by the City of Chicago in {label_m}.")]
        if qa:
            lds.append(faq_ld([qa]))
        page = page_shell(
            f"Chicago Building Permits, {label_m} — Cook County | PermitsByCounty",
            f"{n:,} building permits were issued in Chicago in {label_m} ({money_short(v)} reported value): "
            "permits by trade and the month's biggest projects. Free public-record data.",
            url,
            [("Home", "https://permitsbycounty.com/"), ("Cook County, Illinois", hub_url),
             (label_m, url)],
            lds, body)
        d = os.path.join(base, ym)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "index.html"), "w") as fh:
            fh.write(page)
        written.append(f"/il/cook/{ym}/")

    # --- sitemap -------------------------------------------------------------
    sm_path = os.path.join(REPO, "sitemap.xml")
    with open(sm_path) as fh:
        sm = fh.read()
    entries = ""
    for path in written:
        loc = f"https://permitsbycounty.com{path}"
        if loc not in sm:
            pr = "0.9" if path == "/il/cook/" else ("0.7" if path.count("/") == 3 else "0.6")
            entries += (f"  <url>\n    <loc>{loc}</loc>\n    <lastmod>{TODAY_ISO}</lastmod>\n"
                        f"    <priority>{pr}</priority>\n  </url>\n")
    if entries:
        sm = sm.replace("</urlset>", entries + "</urlset>")
        with open(sm_path, "w") as fh:
            fh.write(sm)
    print(f"wrote {len(written)} pages")
    for p in written:
        print(" ", p)
    print(f"hub stats: total12={total_12} val12={total_val_12:,.0f} cur={cur_n} last={last_n}")


if __name__ == "__main__":
    main()
