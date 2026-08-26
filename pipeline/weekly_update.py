#!/usr/bin/env python3
"""Throw in the Towel — weekly data pipeline (runs in GitHub Actions, no local files).
Pulls live nflverse data, recomputes matchup/funnel from current season when games exist
(falls back to committed 2025 priors preseason), applies committed scheme, regenerates data/*.json."""
import json, math, io, os, sys, datetime
import pandas as pd, numpy as np, requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
SEASON = 2026
NFV = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
TF = {"LAR": "LA", "JAC": "JAX"}
fix = lambda t: TF.get(str(t), str(t))
clamp = lambda x, a, b: max(a, min(b, x))
def load(name): return json.load(open(os.path.join(HERE, name)))
def getcsv(url):
    r = requests.get(url, timeout=90); r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), low_memory=False)

def current_week(games):
    g = games[games.season == SEASON]
    if "result" in g.columns:
        unplayed = g[g.result.isna()]
        if len(unplayed): return int(unplayed.week.min())
        return int(g.week.max())
    return 1

def dvp_from_live(wk):
    """def-vs-position + RB rush/rec funnel from completed weeks this season; None if no data yet."""
    try:
        w = getcsv(f"{NFV}/stats_player/stats_player_week_{SEASON}.csv")
    except Exception:
        return None, None
    w = w[(w.position.isin(["QB","RB","WR","TE"])) & (w.week < wk)]
    if len(w) < 50: return None, None
    for c in ["fantasy_points_ppr","rushing_yards","rushing_tds","receiving_yards","receiving_tds","receptions"]:
        w[c] = pd.to_numeric(w.get(c), errors="coerce").fillna(0)
    dvp = w.groupby(["opponent_team","position","week"]).fantasy_points_ppr.sum().groupby(level=[0,1]).mean()
    dvp = {f"{d}|{p}": v for (d,p), v in dvp.items()}
    rb = w[w.position=="RB"].copy()
    rb["rush_fp"] = 0.1*rb.rushing_yards + 6*rb.rushing_tds
    rb["rec_fp"]  = 0.1*rb.receiving_yards + 6*rb.receiving_tds + rb.receptions
    fg = rb.groupby("opponent_team").agg(g=("week","nunique"), rush=("rush_fp","sum"), rec=("rec_fp","sum"))
    fg["rush_pg"]=fg.rush/fg.g; fg["rec_pg"]=fg.rec/fg.g
    funnel = {d: {"rush": r.rush_pg/fg.rush_pg.mean(), "rec": r.rec_pg/fg.rec_pg.mean()} for d,r in fg.iterrows()}
    return dvp, funnel

def injuries(wk):
    try:
        inj = getcsv(f"{NFV}/injuries/injuries_{SEASON}.csv")
        inj = inj[inj.week == wk]
        m = {"Out":"O","Doubtful":"D","Questionable":"Q"}
        return {str(r.full_name): m.get(r.report_status,"") for _,r in inj.iterrows() if r.report_status in m}
    except Exception:
        return {}

def main():
    games = getcsv(GAMES)
    wk = current_week(games)
    w1 = games[(games.season==SEASON) & (games.week==wk)]
    opp, disp = {}, {}
    for _,r in w1.iterrows():
        opp[r.away_team]=r.home_team; opp[r.home_team]=r.away_team
        disp[r.away_team]="@"+r.home_team; disp[r.home_team]="vs "+r.away_team

    base = load("base_projections.json"); scheme = load("scheme.json")
    dvp_live, funnel_live = dvp_from_live(wk)
    dvp = dvp_live if dvp_live else load("dvp_prior.json")
    funnel = funnel_live if funnel_live else load("funnel_prior.json")
    lg = {p: np.mean([v for k,v in dvp.items() if k.endswith("|"+p)]) for p in ["QB","RB","WR","TE"]}
    inj = injuries(wk)
    src = "live" if dvp_live else "2025 priors (preseason)"

    week=[]
    for r in base:
        tm=fix(r["team"]); o=opp.get(tm); od=disp.get(tm,"BYE"); pos=r["pos"]; b=r["base"]; proj=b; why=[]
        if o:
            fo=fix(o)
            if pos=="RB" and fo in funnel and tm in scheme:
                rec=funnel[fo]["rec"]; rush=funnel[fo]["rush"]; wrec=0.35+0.30*scheme[tm]["screen_rate_pct"]
                mf=clamp(wrec*rec+(1-wrec)*rush,0.80,1.25); proj*=mf
                if rec>=1.15 and scheme[tm]["screen_rate_pct"]>=0.6: why.append("screens vs pass-funnel D — smash spot")
                elif mf>=1.08: why.append("soft RB matchup")
                elif mf<=0.92: why.append("tough RB front")
            else:
                v=dvp.get(f"{fo}|{pos}")
                if v is not None:
                    mf=clamp(v/lg[pos],0.80,1.25); proj*=mf
                    if mf>=1.08: why.append("good matchup")
                    elif mf<=0.92: why.append("tough matchup")
        if tm in scheme:
            s=scheme[tm]; pace=0.05*(s["plays_pg_pct"]-0.5)*2
            if pos=="RB":
                posb=0.05*(s["screen_rate_pct"]-0.5)*2
                if s["screen_rate_pct"]>=0.7: why.append("screen-heavy O")
            elif pos in ("WR","TE"):
                posb=0.05*(s["pa_rate_pct"]-0.5)*2
                if s["pa_rate_pct"]>=0.7: why.append("play-action heavy")
            else: posb=0.05*(s["proe_pct"]-0.5)*2
            proj*=clamp(1+pace+posb,0.90,1.12)
            if s["plays_pg_pct"]>=0.78: why.append("fast pace")
        own=max(1,min(100,round(100/(1+math.exp((r["rk"]-95)/22)))))
        week.append({"name":r["name"],"pos":pos,"team":tm,"opp":od,"proj":round(proj,1),"base":b,
                     "matchup":("good" if proj>b*1.03 else "tough" if proj<b*0.97 else "even"),
                     "delta":round(proj-b,1),"own":own,"inj":inj.get(r["name"],""),"why":"; ".join(why),
                     "rk":r["rk"],"pr":r["pr"]})
    json.dump(week, open(os.path.join(DATA,"week.json"),"w"))
    json.dump({"season":SEASON,"week":wk,"updated":datetime.date.today().isoformat(),
               "status":"in-season" if dvp_live else "preseason","source":src,
               "note":f"Week {wk} — projections from {src}. Base ML + matchup + scheme + injuries."},
              open(os.path.join(DATA,"meta.json"),"w"))
    print(f"[weekly_update] wrote week {wk} · {len(week)} players · matchup source: {src} · {len(inj)} injuries")

if __name__ == "__main__":
    main()
