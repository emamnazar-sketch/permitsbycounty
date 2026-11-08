// POST /api/digest — weekly digest signup capture.
// Stores signups in the Cloudflare D1 database `permitsbycounty`
// (binding DB, declared in wrangler.toml at the repo root).
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status: status || 200,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}

export async function onRequestPost(context) {
  const { request, env } = context;
  if (!env.DB) {
    return json({ ok: false, error: "db_binding_missing" }, 500);
  }
  let email = "";
  let county = "";
  let trade = "";
  const ct = request.headers.get("content-type") || "";
  try {
    if (ct.includes("application/json")) {
      const body = await request.json();
      email = (body.email || "").toString();
      county = (body.county || "").toString();
      trade = (body.trade || "").toString();
    } else {
      const form = await request.formData();
      email = (form.get("email") || "").toString();
      county = (form.get("county") || "").toString();
      trade = (form.get("trade") || "").toString();
    }
  } catch (e) {
    return json({ ok: false, error: "bad_request" }, 400);
  }
  email = email.trim().toLowerCase();
  county = county.trim().slice(0, 80);
  trade = trade.trim().toLowerCase().slice(0, 40);
  if (email.length > 254 || !EMAIL_RE.test(email)) {
    return json({ ok: false, error: "invalid_email" }, 400);
  }
  try {
    await env.DB.prepare(
      "CREATE TABLE IF NOT EXISTS subscribers (email TEXT UNIQUE NOT NULL, county TEXT, created_at TEXT NOT NULL)"
    ).run();
    // Trade pages (added 2026-11-07) segment signups by trade as well as by
    // county: the trade column is added once, here, and stays NULL for the
    // county/homepage forms, which send no trade.
    try {
      await env.DB.prepare("ALTER TABLE subscribers ADD COLUMN trade TEXT").run();
    } catch (e) {
      /* column already exists */
    }
    const res = await env.DB.prepare(
      "INSERT OR IGNORE INTO subscribers (email, county, trade, created_at) VALUES (?, ?, ?, ?)"
    )
      .bind(email, county || null, trade || null, new Date().toISOString())
      .run();
    const added = !!(res.meta && res.meta.changes > 0);
    return json({ ok: true, already: !added });
  } catch (e) {
    return json(
      { ok: false, error: "db_error", detail: String((e && e.message) || e) },
      500
    );
  }
}
