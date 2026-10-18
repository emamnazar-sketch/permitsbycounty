"""Socrata pull -> raw vault.

The vault stores each API response body EXACTLY as received (SOP section 4:
raw vault rule), one file per page, plus a manifest with sha256 of every page
so any normalized record can be traced back to what the source actually said.
"""
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request

PAGE_SIZE = 5000


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "PermitsByCounty-ingest/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def count_where(api_base, where):
    url = api_base + "?" + urllib.parse.urlencode({"$select": "count(*)", "$where": where})
    return int(json.loads(_get(url))[0]["count"])


def dataset_updated_at(domain, dataset_id):
    body = _get(f"https://{domain}/api/views/{dataset_id}")
    meta = json.loads(body)
    return meta.get("rowsUpdatedAt"), meta.get("name")


def pull_window(api_base, where, order, vault_dir, run_stamp):
    """Pull all rows matching `where`, paged, into vault_dir. Returns manifest."""
    os.makedirs(vault_dir, exist_ok=True)
    pages = []
    offset = 0
    total = 0
    while True:
        params = {"$limit": PAGE_SIZE, "$offset": offset, "$order": order}
        if where:
            params["$where"] = where
        url = api_base + "?" + urllib.parse.urlencode(params)
        body = _get(url)
        rows = json.loads(body)
        fname = f"page-{offset // PAGE_SIZE + 1:04d}.json"
        with open(os.path.join(vault_dir, fname), "wb") as fh:
            fh.write(body)
        pages.append({
            "file": fname,
            "url": url,
            "rows": len(rows),
            "bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
        })
        total += len(rows)
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.4)  # polite pacing on the anonymous tier
    manifest = {"run_stamp": run_stamp, "api_base": api_base, "where": where,
                "order": order, "total_rows": total, "pages": pages}
    with open(os.path.join(vault_dir, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    return manifest
