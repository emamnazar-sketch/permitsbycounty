#!/usr/bin/env python3
"""CKAN datastore client — the adapter for source_type == "ckan" registries
(City of Boston, data.boston.gov — "Approved Building Permits"). Same vault
discipline as socrata.py / carto.py: every raw response body is written
byte-for-byte to the vault with a sha256 manifest; nothing is transformed
in flight.

The datastore is the City of Boston's official published interface for this
dataset: the catalog record (approved-building-permits, PDDL) carries one
datastore-active CSV resource, and reads go through the CKAN action API's
datastore_search_sql endpoint — the catalog's own documented query route.

Differences from Socrata/Carto, handled here so pipeline.py stays generic:
  * queries are SQL over the datastore resource id (a UUID, double-quoted
    as the table name): SELECT ... FROM "<resource_id>" WHERE ... ;
  * responses are JSON objects {"result": {"records": [...]}, ...} — the
    pipeline's vault reader unwraps result.records;
  * paging is LIMIT/OFFSET over an explicit ORDER BY on the registry's
    uniqueness field (the permit number — exactly unique in the window);
  * freshness (gate 5) is the datastore resource's own last_modified stamp
    from package_show (the city re-uploads the resource on its daily
    cadence) — the registry documents that measure;
  * the endpoint throttles bursts (observed 2026-10-18: HTTP 403 after
    rapid-fire audit queries, recovering within a minute or two), so
    pacing is slower than Carto's and retries back off harder. The pull
    itself is a handful of plain paged SELECTs, which the endpoint serves
    steadily when paced.
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
    for attempt in range(5):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 — retried, then raised
            last = e
            time.sleep(5 * (attempt + 1))
    raise last


def _sql_url(api_base, sql_text):
    return (api_base + "/datastore_search_sql?"
            + urllib.parse.urlencode({"sql": sql_text}))


def _records(body):
    payload = json.loads(body)
    if not payload.get("success"):
        raise RuntimeError(f"CKAN error: {str(payload.get('error'))[:300]}")
    return payload["result"]["records"]


def count_where(api_base, resource_id, where):
    body = _request(_sql_url(
        api_base, f'SELECT count(*) AS n FROM "{resource_id}" WHERE {where}'))
    return int(_records(body)[0]["n"])


def dataset_updated_at(api_base, dataset_id, resource_id):
    """Freshness measure for CKAN registries: the datastore resource's
    last_modified stamp (ISO string) from package_show. See docstring.
    CKAN stamps are naive UTC — an explicit +00:00 offset is appended so
    the pipeline can subtract them from its aware clock."""
    url = (api_base + "/package_show?"
           + urllib.parse.urlencode({"id": dataset_id}))
    payload = json.loads(_request(url))
    result = payload["result"]
    stamp = None
    for res in result.get("resources", []):
        if res.get("id") == resource_id and res.get("last_modified"):
            stamp = res["last_modified"]
            break
    if stamp is None:
        stamp = result["metadata_modified"]
    if stamp.endswith("Z"):
        stamp = stamp[:-1] + "+00:00"
    elif "+" not in stamp and stamp.count("-") == 2:
        stamp = stamp + "+00:00"
    return stamp


def pull_window(api_base, resource_id, select_cols, where, order, vault, stamp):
    vault = Path(vault)
    vault.mkdir(parents=True, exist_ok=True)
    cols = ", ".join(select_cols)
    offset, page_no, total = 0, 0, 0
    pages = []
    while True:
        q = (f'SELECT {cols} FROM "{resource_id}" WHERE {where} '
             f"ORDER BY {order} LIMIT {PAGE} OFFSET {offset}")
        url = _sql_url(api_base, q)
        body = _request(url)
        fn = f"page-{stamp}-{page_no:03d}.json"
        (vault / fn).write_bytes(body)
        rows = _records(body)
        pages.append({"file": fn, "url": url, "rows": len(rows),
                      "bytes": len(body),
                      "sha256": hashlib.sha256(body).hexdigest()})
        total += len(rows)
        page_no += 1
        if len(rows) < PAGE:
            break
        offset += PAGE
        time.sleep(1.0)
    manifest = {"api_base": api_base, "resource": resource_id,
                "select": list(select_cols), "where": where, "order": order,
                "pulled_at": stamp, "pages": pages, "total_rows": total}
    (vault / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
