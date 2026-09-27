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
// Model: claude-opus-4-8 is the default. For a high-volume consumer chat you can
// cut cost ~5x by switching to "claude-haiku-4-5" (or "claude-sonnet-4-6" as a middle),
// and turn thinking off for snappier replies. Just change the two constants below.
const CHAT_MODEL = "claude-opus-4-8";
const CHAT_THINKING = { type: "adaptive" };   // set to null for fastest/cheapest
const ALLOWED_ORIGIN = "https://chukse.github.io";  // basic abuse gate (not bulletproof)

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
  if (!env || !env.ANTHROPIC_API_KEY) {
    return J({ error: "Chat isn't configured yet — set the ANTHROPIC_API_KEY secret on this worker." }, 200);
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
        "x-api-key": env.ANTHROPIC_API_KEY,
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

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    const p = new URL(request.url).searchParams;

    if (p.get("chat") && request.method === "POST") {
      return towelChat(request, env);
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
