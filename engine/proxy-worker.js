// Throw in the Towel — combined proxy (Cloudflare Worker): ESPN + Yahoo OAuth/API
// Paste this into the SAME worker (ttt-espn-proxy), replacing the old code. URL stays the same.
const YID = "dj0yJmk9dGE4NW8wYXd3RVdSJmQ9WVdrOWRIRkhPVmR3UjA0bWNHbzlNQT09JnM9Y29uc3VtZXJzZWNyZXQmc3Y9MCZ4PTQ2";
const YSECRET = "b9f6ce5c0c80ab07dd15d392269cea780af01ba1";
const REDIRECT = "https://chukse.github.io/ttt-fantasy/";
const CORS = { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type" };
const J = (obj, status = 200) => new Response(typeof obj === "string" ? obj : JSON.stringify(obj), { status, headers: { "content-type": "application/json", ...CORS } });

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    const url = new URL(request.url);
    const p = url.searchParams;

    // ---- YAHOO: exchange auth code for token ----
    if (p.get("yahoo_code")) {
      const body = new URLSearchParams({ client_id: YID, client_secret: YSECRET, redirect_uri: REDIRECT, code: p.get("yahoo_code"), grant_type: "authorization_code" });
      const r = await fetch("https://api.login.yahoo.com/oauth2/get_token", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded", "Authorization": "Basic " + btoa(YID + ":" + YSECRET) }, body });
      return J(await r.text(), r.status);
    }
    // ---- YAHOO: refresh token ----
    if (p.get("yahoo_refresh")) {
      const body = new URLSearchParams({ client_id: YID, client_secret: YSECRET, redirect_uri: REDIRECT, refresh_token: p.get("yahoo_refresh"), grant_type: "refresh_token" });
      const r = await fetch("https://api.login.yahoo.com/oauth2/get_token", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded", "Authorization": "Basic " + btoa(YID + ":" + YSECRET) }, body });
      return J(await r.text(), r.status);
    }
    // ---- YAHOO: proxy a Fantasy API call ----
    if (p.get("yahoo_api")) {
      const api = "https://fantasysports.yahooapis.com/fantasy/v2/" + p.get("yahoo_api");
      const r = await fetch(api, { headers: { Authorization: "Bearer " + p.get("token"), accept: "application/json" } });
      return J(await r.text(), r.status);
    }

    // ---- ESPN (unchanged) ----
    const leagueId = p.get("leagueId");
    if (leagueId) {
      const season = p.get("season") || "2026";
      const s2 = p.get("s2"), swid = p.get("swid");
      const espn = `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/${season}/segments/0/leagues/${leagueId}?view=mRoster&view=mTeam`;
      const headers = { accept: "application/json", "user-agent": "Mozilla/5.0" };
      if (s2 && swid) headers["Cookie"] = `espn_s2=${s2}; SWID=${swid.startsWith("{") ? swid : "{" + swid + "}"}`;
      const r = await fetch(espn, { headers });
      return J(await r.text(), r.status);
    }
    return J({ error: "no action" }, 400);
  }
};
