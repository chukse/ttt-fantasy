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

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    const p = new URL(request.url).searchParams;

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
      const espn = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/" + season + "/segments/0/leagues/" + leagueId + "?view=mRoster&view=mTeam";
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
