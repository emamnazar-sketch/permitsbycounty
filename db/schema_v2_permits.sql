-- PermitsByCounty — schema v2 (ADDITIVE migration, applied after schema.sql v1)
-- Why this exists: the SOP section 4 standard schema requires fields the v1
-- permit_records table does not carry (address, city/county/state, permit type,
-- project description, application date, contractor/business name, source
-- name/URL, pull date). v1 tables stay untouched; the engine writes normalized
-- records to `permits` and keeps using v1 counties / data_sources /
-- monthly_aggregates / ingest_runs. If Amam picks D1, both files apply to D1
-- in order (D1 is SQLite; this file is D1-compatible).

CREATE TABLE IF NOT EXISTS permits (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  county_id           INTEGER NOT NULL REFERENCES counties(id),
  source_id           INTEGER REFERENCES data_sources(id),
  source_record_id    TEXT NOT NULL,          -- id in the source system
  permit_number       TEXT,
  address             TEXT,                   -- street address as published (no person data)
  city                TEXT,
  county              TEXT,
  state               TEXT,
  zip                 TEXT,                   -- NULL when the source does not publish it
  permit_type         TEXT,                   -- as published by the source
  trade               TEXT,                   -- classified: roofing|electrical|plumbing|hvac|solar|general|...
  category            TEXT,                   -- NULL when the source publishes no res/comm flag
  project_description TEXT,
  valuation           REAL,                   -- as reported by the source, USD
  status              TEXT,                   -- normalized lowercase status
  status_source       TEXT,                   -- status exactly as published
  application_date    TEXT,                   -- ISO date
  issue_date          TEXT,                   -- ISO date
  source_updated_date TEXT,
  contractor_name     TEXT,                   -- business name, only when the source publishes a contractor role
  source_name         TEXT,
  source_url          TEXT,
  pulled_at           TEXT NOT NULL,
  raw_ref             TEXT,                   -- vault manifest/page file the row came from
  UNIQUE (county_id, source_record_id)
);
CREATE INDEX IF NOT EXISTS idx_permits_county_issue ON permits (county_id, issue_date);
CREATE INDEX IF NOT EXISTS idx_permits_county_app   ON permits (county_id, application_date);
CREATE INDEX IF NOT EXISTS idx_permits_county_trade ON permits (county_id, trade);
