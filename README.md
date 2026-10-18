# PermitsByCounty

See what's being built. County by county.

Production site for permitsbycounty.com — free public building-permit reports and a weekly county digest, built from official public records.

- Static site deployed via Cloudflare Pages: `index.html` (home, assets inlined) plus the required launch pages — `about.html`, `data-sources.html`, `corrections.html`, `privacy.html`, `terms.html`, `contact.html` — `sitemap.xml`, `robots.txt`, `llms.txt`
- Production branch: `master`
- Wave 1 coverage: TX metros → FL metros → Maricopa County AZ → NC metros → Cook County IL. **Cook County (Chicago) went LIVE 2026-10-17** — see `il/cook/` (hub + trade pages + monthly archives, generated from real QA-passed data)
- Data engine lives in `engine/` (Socrata connectors, raw vault, QA gates, static page generator). Database: SOP names Supabase, which is account-blocked; the engine currently runs on a local SQLite twin of the D1 schema (`db/schema.sql` + `db/schema_v2_permits.sql`) pending Amam's D1-vs-Supabase decision — see PROGRESS notes in the project workspace

Master plan: see `MASTER-PLAN-SOP.md` in the project records (kept outside this repo).
