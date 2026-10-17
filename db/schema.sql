-- PermitsByCounty — Cloudflare D1 schema v1
-- Rules baked in from the Master Plan SOP:
--  * Public permit records only; NO homeowner names or other consumer personal data.
--  * Every record carries its source + fetch time (freshness labels).
--  * Aggregate tables feed the public pages and the AI-citable stats (record-level data is never bulk-exported free).

CREATE TABLE IF NOT EXISTS counties (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  state         TEXT NOT NULL,               -- e.g. 'TX'
  county_name   TEXT NOT NULL,               -- e.g. 'Travis County'
  slug          TEXT NOT NULL UNIQUE,        -- e.g. 'tx/travis'
  wave          TEXT,                        -- 'wave-1' etc.
  status        TEXT NOT NULL DEFAULT 'planned',  -- planned | onboarding | live | paused
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS data_sources (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  county_id     INTEGER NOT NULL REFERENCES counties(id),
  source_name   TEXT NOT NULL,               -- e.g. 'City of Austin Open Data (Socrata)'
  source_url    TEXT,
  source_type   TEXT,                        -- socrata | csv | api | portal
  license_note  TEXT,
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS permit_records (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  county_id     INTEGER NOT NULL REFERENCES counties(id),
  source_id     INTEGER REFERENCES data_sources(id),
  source_record_id TEXT,                     -- the id in the source system
  permit_number TEXT,
  category      TEXT,                        -- residential | commercial | etc.
  trade         TEXT,                        -- roofing | electrical | plumbing | hvac | solar | general ...
  status        TEXT,                        -- issued | finaled | expired | in-review (as published by source)
  issued_date   TEXT,                        -- ISO date as published by source
  valuation     REAL,                        -- declared project value in USD, if published
  locality      TEXT,                        -- city / ZIP only — never a homeowner name
  fetched_at    TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (county_id, source_record_id)
);
CREATE INDEX IF NOT EXISTS idx_permits_county_date ON permit_records (county_id, issued_date);
CREATE INDEX IF NOT EXISTS idx_permits_county_trade ON permit_records (county_id, trade);

CREATE TABLE IF NOT EXISTS monthly_aggregates (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  county_id     INTEGER NOT NULL REFERENCES counties(id),
  year_month    TEXT NOT NULL,               -- '2026-10'
  trade         TEXT,                        -- NULL = all trades
  permit_count  INTEGER NOT NULL DEFAULT 0,
  total_valuation REAL NOT NULL DEFAULT 0,
  computed_at   TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (county_id, year_month, trade)
);

CREATE TABLE IF NOT EXISTS ingest_runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id     INTEGER REFERENCES data_sources(id),
  county_id     INTEGER REFERENCES counties(id),
  started_at    TEXT NOT NULL DEFAULT (datetime('now')),
  finished_at   TEXT,
  status        TEXT NOT NULL DEFAULT 'running',  -- running | ok | partial | failed
  record_count  INTEGER NOT NULL DEFAULT 0,
  note          TEXT
);

CREATE TABLE IF NOT EXISTS digest_subscribers (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT NOT NULL UNIQUE,
  county_slug   TEXT,                        -- county they follow, if any
  status        TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | unsubscribed
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
