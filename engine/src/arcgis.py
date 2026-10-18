#!/usr/bin/env python3
"""ArcGIS FeatureServer client — the adapter for source_type == "arcgis"
registries (City of Fort Worth, services5.arcgis.com hosted FeatureServer).
Same vault discipline as socrata.py / carto.py: every raw response body is
written byte-for-byte to the vault with a sha256 manifest; nothing is
transformed in flight.

The FeatureServer REST query endpoint is the City of Fort Worth's official
published interface for its open-data tables: the city's ArcGIS Hub site
(data.fortworthtexas.gov) lists the "CFW Development Permits Table" feature
service (publisher: City of Fort Worth Development Services Department,
license CC BY 4.0, public access) and serves downloads from this service.

Differences from Socrata, handled here so pipeline.py stays generic:
  * responses are JSON objects {"features": [{"attributes": {...}}, ...],
    "exceededTransferLimit": bool} — the pipeline's vault reader unwraps
    the feature attributes for arcgis registries;
  * paging is resultOffset/resultRecordCount over an explicit ORDER BY,
    and the page size is capped by the layer's maxRecordCount (1,000 for
    the Fort Worth view), read from the layer metadata at pull time;
  * dates in WHERE clauses use ArcGIS SQL TIMESTAMP literals — the
    registry supplies its window predicate as `window_where_sql` with a
    {since} placeholder, and freshness (gate 5) is measured from the
    layer's own editingInfo.dataLastEditDate stamp;
  * the pull's column list (registry pull_select) is sent as outFields,
    so fields the registry excludes (Fort Worth's Owner_Full_Name, a
    person-name field) are never requested at all.
"""
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = {"User-Agent": "PermitsByCounty/1.0 (public-records mirror; permitsbycounty.com)"}
FALLBACK_PAGE = 1000


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


def _layer_meta(api_base, layer):
    body = _request(f"{api_base}/{layer}?" + urllib.parse.urlencode({"f": "json"}))
    return json.loads(body)


def _query_url(api_base, layer, params):
    return f"{api_base}/{layer}/query?" + urllib.parse.urlencode(params)


def count_where(api_base, layer, where):
    body = _request(_query_url(api_base, layer,
                               {"where": where, "returnCountOnly": "true", "f": "json"}))
    return int(json.loads(body)["count"])


def dataset_updated_at(api_base, layer):
    """Freshness measure for ArcGIS registries: the layer's own
    editingInfo.dataLastEditDate (epoch ms) — the source's stamp of when
    its data last changed. Returns (datetime UTC, service-layer name)."""
    meta = _layer_meta(api_base, layer)
    ms = meta.get("editingInfo", {}).get("dataLastEditDate")
    dt = datetime.fromtimestamp(ms / 1000, timezone.utc)
    return dt, meta.get("name")


def pull_window(api_base, layer, select_cols, where, order, vault, stamp):
    vault = Path(vault)
    vault.mkdir(parents=True, exist_ok=True)
    meta = _layer_meta(api_base, layer)
    page_size = int(meta.get("maxRecordCount") or FALLBACK_PAGE)
    out_fields = ",".join(select_cols)
    offset, page_no, total = 0, 0, 0
    pages = []
    while True:
        url = _query_url(api_base, layer, {
            "where": where, "outFields": out_fields, "orderByFields": order,
            "resultOffset": offset, "resultRecordCount": page_size, "f": "json"})
        body = _request(url)
        fn = f"page-{stamp}-{page_no:03d}.json"
        (vault / fn).write_bytes(body)
        payload = json.loads(body)
        rows = payload.get("features", [])
        pages.append({"file": fn, "url": url, "rows": len(rows),
                      "bytes": len(body),
                      "sha256": hashlib.sha256(body).hexdigest()})
        total += len(rows)
        page_no += 1
        if len(rows) < page_size:
            break
        offset += page_size
        time.sleep(0.4)
    manifest = {"api_base": api_base, "layer": layer, "select": list(select_cols),
                "where": where, "order": order, "pulled_at": stamp,
                "page_size": page_size,
                "pages": pages, "total_rows": total}
    (vault / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
