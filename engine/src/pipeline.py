#!/usr/bin/env python3
"""PermitsByCounty ingest pipeline.

Flow (PHASE1-PLAN automation shape + SOP sections 4-5):
  pull (Socrata, paged) -> raw vault (exact responses + sha256 manifest)
  -> normalize (SOP standard schema, privacy rules enforced)
  -> QA gates 1-3 per record, gate 4 volume + gate 5 freshness per run
  -> load (SQLite twin of the D1 schema, upsert = re-pulls update, never dup)
  -> monthly aggregates rebuild -> run report (JSON + MD)

Usage:
  python3 pipeline.py --registry chicago-cook-il --since 2025-10-17
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone, date

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.dirname(HERE)
REPO = os.path.dirname(ENGINE)
sys.path.insert(0, HERE)

import socrata
import normalize as nz
import qa


def utcnow():
    return datetime.now(timezone.utc)


def load_registry(name):
    with open(os.path.join(ENGINE, "registry", f"{name}.json")) as fh:
        return json.load(fh)


def open_db():
    db_path = os.path.join(ENGINE, "data", "permits.db")
    con = sqlite3.connect(db_path)
    with open(os.path.join(REPO, "db", "schema.sql")) as fh:
        con.executescript(fh.read())
    with open(os.path.join(REPO, "db", "schema_v2_permits.sql")) as fh:
        con.executescript(fh.read())
    return con


def ensure_county_source(con, reg):
    con.execute(
        "INSERT INTO counties (state, county_name, slug, wave, status) VALUES (?,?,?,?,?) "
        "ON CONFLICT(slug) DO UPDATE SET status="
        "CASE WHEN counties.status='live' THEN 'live' ELSE 'onboarding' END",
        (reg["state"], reg["county"], reg["county_slug"], reg["wave"], "onboarding"))
    county_id = con.execute("SELECT id FROM counties WHERE slug=?",
                            (reg["county_slug"],)).fetchone()[0]
    con.execute(
        "INSERT INTO data_sources (county_id, source_name, source_url, source_type, license_note) "
        "SELECT ?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM data_sources WHERE county_id=? AND source_name=?)",
        (county_id, reg["source_name"], reg["source_url"], reg["source_type"],
         reg["terms_status"], county_id, reg["source_name"]))
    source_id = con.execute("SELECT id FROM data_sources WHERE county_id=? AND source_name=?",
                            (county_id, reg["source_name"])).fetchone()[0]
    return county_id, source_id


def rebuild_aggregates(con, county_id):
    con.execute("DELETE FROM monthly_aggregates WHERE county_id=?", (county_id,))
    rows = con.execute(
        "SELECT substr(issue_date,1,7) ym, trade, COUNT(*), COALESCE(SUM(valuation),0) "
        "FROM permits WHERE county_id=? AND issue_date IS NOT NULL GROUP BY ym, trade",
        (county_id,)).fetchall()
    totals = {}
    for ym, trade, n, val in rows:
        con.execute("INSERT INTO monthly_aggregates (county_id, year_month, trade, permit_count, total_valuation) "
                    "VALUES (?,?,?,?,?)", (county_id, ym, trade, n, val))
        t = totals.setdefault(ym, [0, 0.0])
        t[0] += n
        t[1] += val
    for ym, (n, val) in totals.items():
        con.execute("INSERT INTO monthly_aggregates (county_id, year_month, trade, permit_count, total_valuation) "
                    "VALUES (?,?,NULL,?,?)", (county_id, ym, n, val))
    return len(totals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True)
    ap.add_argument("--since", required=True, help="window field >= this ISO date")
    ap.add_argument("--field", default="application_start_date",
                    choices=["application_start_date", "applieddate", "issue_date"],
                    help="date field the backfill window is keyed on "
                         "(field name is per-source, from the registry field_map)")
    args = ap.parse_args()

    reg = load_registry(args.registry)
    normalizer = nz.NORMALIZERS[args.registry]
    run_stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    pull_date = utcnow().date()
    report = {"registry": args.registry, "run_stamp": run_stamp, "since": args.since}

    # Gate 5 (freshness) input: dataset-level update stamp from the source itself.
    import urllib.parse
    domain = urllib.parse.urlparse(reg["api_base"]).hostname
    updated_epoch, ds_name = socrata.dataset_updated_at(domain, reg["dataset_id"])
    updated_dt = datetime.fromtimestamp(updated_epoch, timezone.utc)
    age_h = (utcnow() - updated_dt).total_seconds() / 3600
    report["source_dataset"] = ds_name
    report["source_updated_at"] = updated_dt.isoformat()
    report["source_age_hours"] = round(age_h, 1)
    report["gate5_freshness"] = "PASS" if age_h <= reg["qa_thresholds"]["freshness_max_age_hours"] else "STALE"

    # Pull -> vault. Pre-pull count is the integrity baseline for gate 4:
    # what we haul must match what the source says exists for this window.
    vault_dir = os.path.join(ENGINE, "data", "vault", args.registry,
                             f"backfill-{args.field}-{args.since}")
    where = f"{args.field} >= '{args.since}T00:00:00'"
    report["window_field"] = args.field
    report["expected_pull_count"] = socrata.count_where(reg["api_base"], where)
    # Paging order keys on the source's uniqueness field (registry
    # order_tiebreak): Chicago has a numeric id; Austin has no id column —
    # its unique key is permit_number. pull_select (when the registry
    # defines one) restricts requested columns (see socrata.pull_window).
    order = f"{args.field}, {reg.get('order_tiebreak', 'id')}"
    manifest = socrata.pull_window(reg["api_base"], where,
                                   order, vault_dir, run_stamp,
                                   select=reg.get("pull_select"))
    report["pulled_rows"] = manifest["total_rows"]
    report["vault_pages"] = len(manifest["pages"])

    # Normalize from the vault files (never straight from the wire).
    accepted, held, seen = [], [], set()
    dupes = 0
    raw_total = 0
    for page in manifest["pages"]:
        with open(os.path.join(vault_dir, page["file"])) as fh:
            rows = json.load(fh)
        for raw in rows:
            raw_total += 1
            rec = normalizer(raw, reg)
            if rec is None:
                held.append({"id": None, "reasons": ["normalize: missing source id"]})
                continue
            if rec["source_record_id"] in seen:  # Gate 2, in-batch
                dupes += 1
                continue
            seen.add(rec["source_record_id"])
            rec["raw_ref"] = f"{os.path.basename(vault_dir)}/{page['file']}"
            reasons = qa.check_record(rec, pull_date,
                                      reg["qa_thresholds"].get("valuation_max_plausible_usd",
                                                               qa.MAX_VALUATION_DEFAULT))
            if reasons:
                held.append({"id": rec["source_record_id"], "reasons": reasons})
            else:
                accepted.append(rec)
    report["raw_rows_read"] = raw_total
    report["duplicate_rows_in_batch"] = dupes
    report["accepted"] = len(accepted)
    report["held"] = len(held)
    report["hold_reasons"] = dict(Counter(r for h in held for r in h["reasons"]))
    report["held_sample"] = held[:25]

    # Gate 4 (volume anomaly): (a) count-match — pulled rows must equal the
    # source's own count for the identical window (small drift allowed for
    # records arriving mid-pull); (b) registry baseline when one is configured
    # for this window field. Either failure = HELD, aggregates not rebuilt.
    exp = report["expected_pull_count"]
    drift = abs(manifest["total_rows"] - exp)
    count_ok = drift <= max(10, 0.01 * exp)
    report["gate4_volume"] = {"count_match": {"expected": exp, "pulled": manifest["total_rows"],
                                              "drift": drift, "verdict": "PASS" if count_ok else "HELD"}}
    base_ok = True
    if args.field in ("application_start_date", "applieddate", "issue_date"):
        expected = reg["qa_thresholds"].get("backfill_expected_volume_12mo")
        if expected:
            tol = reg["qa_thresholds"].get("backfill_volume_tolerance", 0.25)
            base_ok = expected * (1 - tol) <= manifest["total_rows"] <= expected * (1 + tol)
            report["gate4_volume"]["baseline"] = {"expected": expected, "tolerance": tol,
                                                  "verdict": "PASS" if base_ok else "HELD"}
    report["gate4_volume"]["verdict"] = "PASS" if (count_ok and base_ok) else "HELD"

    # Load (upsert: re-pulls update, never duplicate — Gate 2 at the DB).
    con = open_db()
    county_id, source_id = ensure_county_source(con, reg)
    pulled_at = utcnow().isoformat()
    cols = ["county_id", "source_id", "source_record_id", "permit_number", "address",
            "city", "county", "state", "zip", "permit_type", "trade", "category",
            "project_description", "valuation", "status", "status_source",
            "application_date", "issue_date", "source_updated_date", "contractor_name",
            "source_name", "source_url", "pulled_at", "raw_ref"]
    sql = (f"INSERT INTO permits ({','.join(cols)}) VALUES ({','.join('?' * len(cols))}) "
           "ON CONFLICT(county_id, source_record_id) DO UPDATE SET "
           "status=excluded.status, status_source=excluded.status_source, "
           "issue_date=excluded.issue_date, valuation=excluded.valuation, "
           "project_description=excluded.project_description, pulled_at=excluded.pulled_at")
    for rec in accepted:
        vals = [county_id, source_id] + [rec.get(c) for c in cols[2:-2]] + [pulled_at, rec["raw_ref"]]
        con.execute(sql, vals)
    months = 0
    if report["gate4_volume"]["verdict"] == "PASS":
        months = rebuild_aggregates(con, county_id)
    run_status = "ok" if report["gate4_volume"]["verdict"] != "HELD" else "held-volume"
    con.execute(
        "INSERT INTO ingest_runs (source_id, county_id, finished_at, status, record_count, note) "
        "VALUES (?,?,?, ?,?,?)",
        (source_id, county_id, pulled_at, run_status, len(accepted),
         f"backfill since {args.since}; held={len(held)}; gate5={report['gate5_freshness']}"))
    con.commit()
    report["db_counts"] = {
        "permits_total": con.execute("SELECT COUNT(*) FROM permits WHERE county_id=?",
                                     (county_id,)).fetchone()[0],
        "with_issue_date": con.execute("SELECT COUNT(*) FROM permits WHERE county_id=? AND issue_date IS NOT NULL",
                                       (county_id,)).fetchone()[0],
        "with_contractor": con.execute("SELECT COUNT(*) FROM permits WHERE county_id=? AND contractor_name IS NOT NULL",
                                       (county_id,)).fetchone()[0],
        "aggregate_months": months,
        "trade_breakdown": con.execute("SELECT trade, COUNT(*) FROM permits WHERE county_id=? "
                                       "GROUP BY trade ORDER BY 2 DESC", (county_id,)).fetchall(),
        "top_valuations": con.execute("SELECT permit_number, valuation, trade, substr(project_description,1,80) "
                                       "FROM permits WHERE county_id=? AND valuation IS NOT NULL "
                                       "ORDER BY valuation DESC LIMIT 5", (county_id,)).fetchall(),
    }
    con.close()

    out_dir = os.path.join(ENGINE, "data", "reports")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{args.registry}-backfill-{args.since}-{run_stamp}.json")
    with open(out_path, "w") as fh:
        json.dump(report, fh, indent=1, default=str)
    print(json.dumps({k: report[k] for k in ("pulled_rows", "accepted", "held", "hold_reasons",
                                             "gate5_freshness")}, indent=1, default=str))
    print("gate4:", report["gate4_volume"])
    print("db:", json.dumps(report["db_counts"], default=str)[:800])
    print("report:", out_path)


if __name__ == "__main__":
    main()
