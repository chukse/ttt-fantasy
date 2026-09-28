// Throw in the Towel — combined proxy (Cloudflare Worker): ESPN + Yahoo
// Paste into the ttt-espn-proxy worker (replace all), then Deploy. URL stays the same.
const YID = "dj0yJmk9dGE4NW8wYXd3RVdSJmQ9WVdrOWRIRkhPVmR3UjA0bWNHbzlNQT09JnM9Y29uc3VtZXJzZWNyZXQmc3Y9MCZ4PTQ2";
const YSECRET = "b9f6ce5c0c80ab07dd15d392269cea780af01ba1";
const REDIRECT = "https://chukse.github.io/ttt-fantasy/";

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type"
};

function J(o, s) {
  const body = typeof o === "string" ? o : JSON.stringify(o);
  return new Response(body, { status: s || 200, headers: { "content-type": "application/json", ...CORS } });
}

async function yahooToken(params) {
  const auth = "Basic " + btoa(YID + ":" + YSECRET);
  const r = await fetch("https://api.login.yahoo.com/oauth2/get_token", {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", "Authorization": auth },
    body: new URLSearchParams(params)
  });
  return J(await r.text(), r.status);
}

// ===== Ask the Towel — Claude chat assistant =====
// Running Haiku 4.5: fast + cheap (~$1/$5 per 1M tokens, ~5x cheaper than Opus) — the right
// pick for a high-volume consumer chat grounded in our own data. To upgrade reasoning later,
// set CHAT_MODEL="claude-opus-4-8" (or "claude-sonnet-4-6") AND CHAT_THINKING={type:"adaptive"}.
// NOTE: Haiku 4.5 does NOT accept the thinking/effort params — keep CHAT_THINKING null on Haiku.
const CHAT_MODEL = "claude-haiku-4-5";
const CHAT_THINKING = null;
const ALLOWED_ORIGIN = "https://chukse.github.io";  // basic abuse gate (not bulletproof)
const SB_URL = "https://gpcydpgsgburxozdgylf.supabase.co";  // Supabase project (billing writes go here)

const TOWEL_PERSONA = [
  "You are \"The Towel\" — the in-app fantasy-football assistant for Throw in the Towel.",
  "Voice: dry, plain-spoken, honest about limits. Short — this is a phone chat, not an essay.",
  "Scoring is Full PPR unless the data says otherwise.",
  "HARD RULES:",
  "- Answer ONLY from the DATA block below. Never invent players, numbers, teams, matchups, or ownership.",
  "- If the data doesn't contain what's asked (a player not listed, no league connected), say so plainly.",
  "- Trades: compare the PLAYER TRADE VALUES; give a fair / win / lose verdict and note if a side fills a need. To find 'what trade gets me X', propose a fair package from MY TEAM whose combined value ~ the target's.",
  "- Start/sit: use this-week proj; lean matchup when it's close.",
  "- Waivers: recommend from TOP AVAILABLE only.",
  "- Odds/playoffs: if league teams are listed, reason from roster strength; otherwise tell them to connect a Sleeper/ESPN league.",
  "- Never fake confidence. Small samples and model disagreement are worth flagging."
].join("\n");

async function towelChat(request, env) {
  if (!env || !env.Anthropic_API) {
    return J({ error: "Chat isn't configured yet — set the Anthropic_API secret on this worker." }, 200);
  }
  const origin = request.headers.get("Origin") || "";
  if (ALLOWED_ORIGIN && origin && origin.indexOf(ALLOWED_ORIGIN) !== 0) {
    return J({ error: "forbidden origin" }, 403);
  }
  let body;
  try { body = await request.json(); } catch (e) { return J({ error: "bad request body" }, 400); }
  const history = Array.isArray(body.messages) ? body.messages.slice(-20) : [];
  if (!history.length) return J({ error: "no message" }, 400);
  const ctx = typeof body.context === "string" ? body.context.slice(0, 24000) : "";
  const system = TOWEL_PERSONA + "\n\n===== LIVE DATA =====\n" + ctx;

  const payload = { model: CHAT_MODEL, max_tokens: 1024, system: system, messages: history };
  if (CHAT_THINKING) payload.thinking = CHAT_THINKING;

  let data;
  try {
    const r = await fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-api-key": env.Anthropic_API,
        "anthropic-version": "2023-06-01"
      },
      body: JSON.stringify(payload)
    });
    data = await r.json();
  } catch (e) {
    return J({ error: "upstream call failed" }, 200);
  }
  if (data && data.type === "error") {
    return J({ error: (data.error && data.error.message) || "api error" }, 200);
  }
  let text = "";
  if (data && Array.isArray(data.content)) {
    for (const b of data.content) if (b.type === "text") text += b.text;
  }
  return J({ text: text || "(no answer)", stop: (data && data.stop_reason) || "" }, 200);
}

// ===== Stripe billing (freemium: free core + Pro) =====
// Secrets/vars on the worker (Cloudflare → Settings → Variables):
//   STRIPE_SECRET          (secret)  sk_live_… / sk_test_…
//   STRIPE_WEBHOOK_SECRET  (secret)  whsec_…  (from the Stripe webhook endpoint)
//   STRIPE_PRICE_MONTHLY   (var)     price_…  ($4.99/mo recurring)
//   STRIPE_PRICE_SEASON    (var)     price_…  ($19.99 one-time)
//   SUPABASE_SERVICE_ROLE  (secret)  Supabase service_role key (bypasses RLS to set plan)

// Season pass runs Aug–Jan; a pass bought anytime is valid through Feb 15 of the season's end year.
function seasonEnd() {
  const d = new Date(), y = d.getUTCFullYear();
  const endYear = d.getUTCMonth() >= 6 ? y + 1 : y;  // Jul+ → next Feb, else this Feb
  return new Date(Date.UTC(endYear, 1, 15)).toISOString();
}

async function stripeCheckout(request, env) {
  if (!env.STRIPE_SECRET) return J({ error: "Billing isn't set up yet." }, 200);
  const origin = request.headers.get("Origin") || "";
  if (ALLOWED_ORIGIN && origin && origin.indexOf(ALLOWED_ORIGIN) !== 0) return J({ error: "forbidden origin" }, 403);
  let b; try { b = await request.json(); } catch (e) { return J({ error: "bad request body" }, 400); }
  const uid = b.user_id;
  if (!uid) return J({ error: "Sign in first." }, 400);
  const kind = b.kind === "season" ? "season" : "monthly";
  const price = kind === "season" ? env.STRIPE_PRICE_SEASON : env.STRIPE_PRICE_MONTHLY;
  if (!price) return J({ error: "Price not configured on the server." }, 200);
  const ret = (b.return_url || (ALLOWED_ORIGIN + "/ttt-fantasy/")).split("#")[0].split("?")[0];

  const form = new URLSearchParams();
  form.set("mode", kind === "season" ? "payment" : "subscription");
  form.set("line_items[0][price]", price);
  form.set("line_items[0][quantity]", "1");
  form.set("client_reference_id", uid);
  if (b.email) form.set("customer_email", b.email);
  form.set("success_url", ret + "?upgraded=1");
  form.set("cancel_url", ret);
  form.set("metadata[user_id]", uid);
  form.set("metadata[kind]", kind);
  if (kind !== "season") form.set("subscription_data[metadata][user_id]", uid);  // carry uid onto sub events
  if (kind === "season") form.set("payment_intent_data[metadata][user_id]", uid);

  let d;
  try {
    const r = await fetch("https://api.stripe.com/v1/checkout/sessions", {
      method: "POST",
      headers: { "Authorization": "Bearer " + env.STRIPE_SECRET, "content-type": "application/x-www-form-urlencoded" },
      body: form
    });
    d = await r.json();
  } catch (e) { return J({ error: "checkout call failed" }, 200); }
  if (d && d.url) return J({ url: d.url }, 200);
  return J({ error: (d && d.error && d.error.message) || "stripe error" }, 200);
}

// Verify Stripe's signature header (t=timestamp,v1=hex-hmac) with Web Crypto — no SDK needed.
async function verifyStripeSig(payload, header, secret) {
  const parts = {}; (header || "").split(",").forEach(kv => { const i = kv.indexOf("="); if (i > 0) parts[kv.slice(0, i)] = kv.slice(i + 1); });
  if (!parts.t || !parts.v1) return false;
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(parts.t + "." + payload));
  const hex = [...new Uint8Array(mac)].map(x => x.toString(16).padStart(2, "0")).join("");
  if (hex.length !== parts.v1.length) return false;
  let diff = 0; for (let i = 0; i < hex.length; i++) diff |= hex.charCodeAt(i) ^ parts.v1.charCodeAt(i);
  return diff === 0;
}
function sbHeaders(env) {
  return { apikey: env.SUPABASE_SERVICE_ROLE, Authorization: "Bearer " + env.SUPABASE_SERVICE_ROLE, "content-type": "application/json" };
}
async function sbUpsert(env, row) {  // creates or updates by user_id PK
  await fetch(SB_URL + "/rest/v1/user_state", {
    method: "POST",
    headers: { ...sbHeaders(env), Prefer: "resolution=merge-duplicates,return=minimal" },
    body: JSON.stringify(row)
  });
}
async function sbPatch(env, col, val, fields) {
  await fetch(SB_URL + "/rest/v1/user_state?" + col + "=eq." + encodeURIComponent(val), {
    method: "PATCH",
    headers: { ...sbHeaders(env), Prefer: "return=minimal" },
    body: JSON.stringify(fields)
  });
}

async function stripeWebhook(request, env) {
  if (!env.STRIPE_WEBHOOK_SECRET || !env.SUPABASE_SERVICE_ROLE) return J({ error: "webhook not configured" }, 200);
  const sig = request.headers.get("stripe-signature") || "";
  const payload = await request.text();
  if (!(await verifyStripeSig(payload, sig, env.STRIPE_WEBHOOK_SECRET))) return J({ error: "bad signature" }, 400);
  let ev; try { ev = JSON.parse(payload); } catch (e) { return J({ error: "bad json" }, 400); }
  const o = (ev.data && ev.data.object) || {};
  try {
    if (ev.type === "checkout.session.completed") {
      const uid = o.client_reference_id || (o.metadata && o.metadata.user_id);
      const kind = (o.metadata && o.metadata.kind) || (o.mode === "payment" ? "season" : "monthly");
      if (uid) await sbUpsert(env, { user_id: uid, plan: "pro", plan_expires: kind === "season" ? seasonEnd() : null, stripe_customer_id: o.customer || null });
    } else if (ev.type === "customer.subscription.updated") {
      const uid = o.metadata && o.metadata.user_id;
      const active = o.status === "active" || o.status === "trialing";
      if (uid) await sbPatch(env, "user_id", uid, { plan: active ? "pro" : "free", plan_expires: null });
      else if (o.customer) await sbPatch(env, "stripe_customer_id", o.customer, { plan: active ? "pro" : "free" });
    } else if (ev.type === "customer.subscription.deleted") {
      const uid = o.metadata && o.metadata.user_id;
      if (uid) await sbPatch(env, "user_id", uid, { plan: "free", plan_expires: null });
      else if (o.customer) await sbPatch(env, "stripe_customer_id", o.customer, { plan: "free", plan_expires: null });
    }
  } catch (e) { /* swallow — return 200 so Stripe doesn't hammer retries on our DB hiccup */ }
  return J({ received: true }, 200);
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    const p = new URL(request.url).searchParams;

    if (p.get("chat") && request.method === "POST") {
      return towelChat(request, env);
    }
    if (p.get("stripe_checkout") && request.method === "POST") {
      return stripeCheckout(request, env);
    }
    if (p.get("stripe_webhook") && request.method === "POST") {
      return stripeWebhook(request, env);
    }

    if (p.get("yahoo_code")) {
      return yahooToken({ redirect_uri: REDIRECT, code: p.get("yahoo_code"), grant_type: "authorization_code" });
    }
    if (p.get("yahoo_refresh")) {
      return yahooToken({ redirect_uri: REDIRECT, refresh_token: p.get("yahoo_refresh"), grant_type: "refresh_token" });
    }
    if (p.get("yahoo_api")) {
      const url = "https://fantasysports.yahooapis.com/fantasy/v2/" + p.get("yahoo_api");
      const headers = { Authorization: "Bearer " + p.get("token"), accept: "application/json" };
      const r = await fetch(url, { headers });
      return J(await r.text(), r.status);
    }

    const leagueId = p.get("leagueId");
    if (leagueId) {
      const season = p.get("season") || "2026";
      const s2 = p.get("s2");
      const swid = p.get("swid");
      const espn = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/" + season + "/segments/0/leagues/" + leagueId + "?view=mRoster&view=mTeam&view=mMatchup&view=mSettings";
      const headers = { accept: "application/json", "user-agent": "Mozilla/5.0" };
      if (s2 && swid) {
        const sw = swid.charAt(0) === "{" ? swid : "{" + swid + "}";
        headers["Cookie"] = "espn_s2=" + s2 + "; SWID=" + sw;
      }
      const r = await fetch(espn, { headers });
      return J(await r.text(), r.status);
    }

    return J({ error: "no action" }, 400);
  }
};
