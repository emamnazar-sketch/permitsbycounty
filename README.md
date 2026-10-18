# PermitsByCounty

See what's being built. County by county.

Production site for permitsbycounty.com — free public building-permit reports and a weekly county digest, built from official public records.

- Static site deployed via Cloudflare Pages: `index.html` (home, assets inlined) plus the required launch pages — `about.html`, `data-sources.html`, `corrections.html`, `privacy.html`, `terms.html`, `contact.html` — `sitemap.xml`, `robots.txt`, `llms.txt`
- Production branch: `master`
- Wave 1 coverage: TX metros → FL metros → Maricopa County AZ → NC metros → Cook County IL (all planned at launch)
- Data engine (Supabase) connects separately; the site labels sample data honestly until it does

Master plan: see `MASTER-PLAN-SOP.md` in the project records (kept outside this repo).
