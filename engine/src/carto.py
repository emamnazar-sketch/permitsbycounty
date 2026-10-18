#!/usr/bin/env python3
"""Carto SQL API client — the adapter for source_type == "carto" registries
(City of Philadelphia, phl.carto.com). Same vault discipline as socrata.py:
every raw response body is written byte-for-byte to the vault with a sha256
manifest; nothing is transformed in flight.

The SQL API is the City of Philadelphia's official published interface for
its open-data tables: the OpenDataPhilly catalog's own CSV/API links for
the L&I permits dataset point at this endpoint, and the catalog record
(licenses-and-inspections-building-and-zoning-permits) lists the dataset as
public, updated daily (modified R/P1D), under the City's Terms of Use.

Differences from Socrata, handled here so pipeline.py stays generic:
  * responses are JSON objects {"rows": [...], "fields": {...}} — the
    pipeline's vault reader unwraps the "rows" key;
  * paging is LIMIT/OFFSET over an explicit ORDER BY on the registry's
    uniqueness field (the permit number — exactly unique in the window);
  * the table exposes no dataset-level updated stamp through the SQL API,
    so freshness (gate 5) is measured as the freshest watermark value in
    the table itself — for permits, max(permitissuedate) — and the
    registry documents that measure (freshness_stamp_field).
"""
import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "PermitsByCounty/1.0 (public-records mirror; permitsbycounty.com)"}
PAGE = 5000


def _request(url):
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 — retried, then raised
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def _sql_url(api_base, sql_text):
    return api_base + "?" + urllib.parse.urlencode({"q": sql_text, "format": "json"})


def count_where(api_base, table, where):
    body = _request(_sql_url(api_base, f"SELECT count(*) AS n FROM {table} WHERE {where}"))
    return int(json.loads(body)["rows"][0]["n"])


def dataset_updated_at(api_base, table, stamp_field):
    """Freshness measure for Carto registries: the freshest watermark value
    in the table (ISO string). See module docstring."""
    body = _request(_sql_url(api_base, f"SELECT max({stamp_field}) AS m FROM {table}"))
    return json.loads(body)["rows"][0]["m"]


def pull_window(api_base, table, select_cols, where, order, vault, stamp):
    vault = Path(vault)
    vault.mkdir(parents=True, exist_ok=True)
    cols = ", ".join(select_cols)
    offset, page_no, total = 0, 0, 0
    pages = []
    while True:
        q = (f"SELECT {cols} FROM {table} WHERE {where} "
             f"ORDER BY {order} LIMIT {PAGE} OFFSET {offset}")
        url = _sql_url(api_base, q)
        body = _request(url)
        fn = f"page-{stamp}-{page_no:03d}.json"
        (vault / fn).write_bytes(body)
        rows = json.loads(body)["rows"]
        pages.append({"file": fn, "url": url, "rows": len(rows),
                      "bytes": len(body),
                      "sha256": hashlib.sha256(body).hexdigest()})
        total += len(rows)
        page_no += 1
        if len(rows) < PAGE:
            break
        offset += PAGE
        time.sleep(0.4)
    manifest = {"api_base": api_base, "table": table, "select": list(select_cols),
                "where": where, "order": order, "pulled_at": stamp,
                "pages": pages, "total_rows": total}
    (vault / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
