#!/usr/bin/env python3
"""Throw in the Towel — weekly ROLLING pipeline (GitHub Actions, no local files).
Projections roll: preseason base is a PRIOR that gets shrunk toward in-season production
as weeks accumulate. Covers ALL skill players (breakouts included), not just the top 200.
Then matchup (live def-vs-position) x scheme x injury. Refreshes ADP + FantasyPros."""
import json, math, io, os, datetime
import pandas as pd, numpy as np, requests

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); DATA = os.path.join(ROOT, "data")
SEASON = 2026
NFV = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
TF = {"LAR": "LA", "JAC": "JAX"}; fix = lambda t: TF.get(str(t), str(t)); clamp = lambda x,a,b: max(a,min(b,x))
def load(n): return json.load(open(os.path.join(HERE, n)))
def getcsv(u): r=requests.get(u,timeout=90); r.raise_for_status(); return pd.read_csv(io.StringIO(r.text), low_memory=False)
def norm(s): import re; return re.sub(r'[^a-z]','',re.sub(r'\b(jr|sr|ii|iii|iv|v)\b','',str(s).lower()))
REPL = {"QB":10.0,"RB":5.0,"WR":5.0,"TE":3.5}   # replacement-level prior for unknown/breakout players

def refresh_adp():
    out={}
    for fmt,key in [("ppr","ppr"),("half-ppr","half"),("standard","std")]:
        try:
            d=requests.get(f"https://fantasyfootballcalculator.com/api/v1/adp/{fmt}?teams=12&year={SEASON}",timeout=25).json()
            out[key]=[{"name":p["name"],"pos":p["position"],"team":p.get("team",""),"adp":round(p["adp"],1)} for p in d.get("players",[]) if p["position"] in("QB","RB","WR","TE")]
        except Exception: pass
    if out: json.dump(out,open(os.path.join(DATA,"adp.json"),"w")); print("[roll] adp refreshed")

def refresh_fpros():
    out={}
    for sc,key in [("PPR","ppr"),("HALF","half"),("STD","std")]:
        try:
            d=requests.get(f"https://partners.fantasypros.com/api/v1/consensus-rankings.php?sport=NFL&year={SEASON}&week=0&experts=available&position=ALL&scoring={sc}&type=draft",headers={"User-Agent":"Mozilla/5.0"},timeout=25).json()
            out[key]=[{"name":p["player_name"],"pos":p["player_position_id"],"rank":p["rank_ecr"],"posrank":p.get("pos_rank","")} for p in d.get("players",[]) if p["player_position_id"] in("QB","RB","WR","TE")]
        except Exception: pass
    if out: json.dump(out,open(os.path.join(DATA,"fpros.json"),"w")); print("[roll] fpros refreshed")

def current_week(games):
    g=games[games.season==SEASON]
    if "result" in g.columns:
        un=g[g.result.isna()]
        return int(un.week.min()) if len(un) else int(g.week.max())
    return 1

def injuries(wk):
    try:
        inj=getcsv(f"{NFV}/injuries/injuries_{SEASON}.csv"); inj=inj[inj.week==wk]
        m={"Out":"O","Doubtful":"D","Questionable":"Q"}
        return {norm(r.full_name):m.get(r.report_status,"") for _,r in inj.iterrows() if r.report_status in m}
    except Exception: return {}

def main():
    refresh_adp(); refresh_fpros()
    games=getcsv(GAMES); wk=current_week(games)
    w1=games[(games.season==SEASON)&(games.week==wk)]
    opp,disp={},{}
    for _,r in w1.iterrows():
        opp[r.away_team]=r.home_team; opp[r.home_team]=r.away_team
        disp[r.away_team]="@"+r.home_team; disp[r.home_team]="vs "+r.away_team

    base={norm(r["name"]):r for r in load("base_projections.json")}
    scheme=load("scheme.json"); inj=injuries(wk)

    # ---- pull season-to-date weekly production (rolling) ----
    live=None
    try: live=getcsv(f"{NFV}/stats_player/stats_player_week_{SEASON}.csv")
    except Exception: pass

    dvp,funnel,lg=load("dvp_prior.json"),load("funnel_prior.json"),None
    rows=[]
    if live is not None and len(live):
        tcol="team" if "team" in live.columns else ("recent_team" if "recent_team" in live.columns else None)
        live=live[live.position.isin(["QB","RB","WR","TE"])&(live.week<=wk)].copy()
        for c in ["fantasy_points_ppr","rushing_yards","rushing_tds","receiving_yards","receiving_tds","receptions","target_share","wopr"]:
            live[c]=pd.to_numeric(live.get(c),errors="coerce").fillna(0)
        live=live.rename(columns={tcol:"team"}) if tcol else live
        # live def-vs-position + RB funnel from games actually played
        played=live[live.week<wk]
        if len(played)>=40:
            d=played.groupby(["opponent_team","position","week"]).fantasy_points_ppr.sum().groupby(level=[0,1]).mean()
            dvp={f"{a}|{b}":v for (a,b),v in d.items()}
            rb=played[played.position=="RB"].copy()
            rb["rush_fp"]=0.1*rb.rushing_yards+6*rb.rushing_tds; rb["rec_fp"]=0.1*rb.receiving_yards+6*rb.receiving_tds+rb.receptions
            fg=rb.groupby("opponent_team").agg(g=("week","nunique"),rush=("rush_fp","sum"),rec=("rec_fp","sum"))
            fg["rush_pg"]=fg.rush/fg.g; fg["rec_pg"]=fg.rec/fg.g
            funnel={dd:{"rush":r.rush_pg/fg.rush_pg.mean(),"rec":r.rec_pg/fg.rec_pg.mean()} for dd,r in fg.iterrows()}
        # per-player rolling talent
        g=live.sort_values(["player_id","week"]).groupby("player_id")
        agg=g.agg(name=("player_display_name","last"),pos=("position","last"),team=("team","last"),
                  gp=("week","nunique"),tot=("fantasy_points_ppr","sum"),tgt=("target_share","mean"),wopr=("wopr","mean")).reset_index()
        l3=live[live.week>wk-4].groupby("player_id").fantasy_points_ppr.mean().rename("l3")
        agg=agg.merge(l3,on="player_id",how="left")
        for _,r in agg.iterrows():
            k=norm(r["name"]); gp=int(r.gp); std=r.tot/max(gp,1); l3v=r.l3 if pd.notna(r.l3) else std
            observed=0.55*std+0.45*l3v
            b=base.get(k); prior=float(b["base"]) if b else REPL.get(r.pos,5.0); K=5.0 if b else 3.0
            rolling=(K*prior+gp*observed)/(K+gp)              # <-- shrink prior toward observed as gp grows
            rows.append(dict(name=r["name"],pos=r.pos,team=fix(str(r.team)),roll=rolling,std=std,l3=l3v,gp=gp,
                             tgt=float(r.tgt or 0),base=prior,rk=(int(b["rk"]) if b else 999),pr=(b["pr"] if b else "")))
    # add base-only players who haven't logged live stats yet (early/bye)
    haveN={norm(x["name"]) for x in rows}
    for k,b in base.items():
        if k not in haveN:
            rows.append(dict(name=b["name"],pos=b["pos"],team=fix(str(b["team"])),roll=float(b["base"]),std=float(b["base"]),l3=float(b["base"]),gp=0,tgt=0,base=float(b["base"]),rk=int(b["rk"]),pr=b["pr"]))
    lg={p:np.mean([v for kk,v in dvp.items() if kk.endswith("|"+p)] or [10]) for p in ["QB","RB","WR","TE"]}

    week=[]
    for r in rows:
        tm=r["team"]; o=opp.get(tm); od=disp.get(tm,"BYE"); pos=r["pos"]; b=r["roll"]; proj=b; why=[]
        if o:
            fo=fix(o)
            if pos=="RB" and fo in funnel and tm in scheme:
                rec=funnel[fo]["rec"]; rush=funnel[fo]["rush"]; wrec=0.35+0.30*scheme[tm]["screen_rate_pct"]
                mf=clamp(wrec*rec+(1-wrec)*rush,0.80,1.25); proj*=mf
                if rec>=1.15 and scheme[tm]["screen_rate_pct"]>=0.6: why.append("screens vs pass-funnel D — smash spot")
            else:
                v=dvp.get(f"{fo}|{pos}")
                if v is not None:
                    mf=clamp(v/lg[pos],0.80,1.25); proj*=mf
                    if mf>=1.08: why.append("good matchup")
                    elif mf<=0.92: why.append("tough matchup")
        if tm in scheme:
            s=scheme[tm]; pace=0.05*(s["plays_pg_pct"]-0.5)*2
            posb=0.05*(s["screen_rate_pct"]-0.5)*2 if pos=="RB" else 0.05*(s["pa_rate_pct"]-0.5)*2 if pos in("WR","TE") else 0.05*(s["proe_pct"]-0.5)*2
            proj*=clamp(1+pace+posb,0.90,1.12)
            if pos=="RB" and s["screen_rate_pct"]>=0.7: why.append("screen-heavy O")
        trend=round(r["l3"]-r["std"],1)                       # + = heating up
        hot = r["gp"]>=1 and r["l3"]>=12 and r["l3"]>r["base"]*1.3
        if hot: why.insert(0,"🔥 trending up")
        own=max(1,min(100,round(100/(1+math.exp((r["rk"]-95)/22))))) if r["rk"]<900 else max(1,min(60,round(r["l3"]*3)))
        week.append({"name":r["name"],"pos":pos,"team":tm,"opp":od,"proj":round(proj,1),"base":round(r["base"],1),
                     "roll":round(b,1),"form":round(r["l3"],1),"trend":trend,"gp":r["gp"],
                     "matchup":("good" if proj>b*1.03 else "tough" if proj<b*0.97 else "even"),
                     "delta":round(proj-r["base"],1),"own":own,"inj":inj.get(norm(r["name"]),""),
                     "why":"; ".join(why),"rk":r["rk"],"pr":r["pr"]})
    week=sorted(week,key=lambda x:-x["proj"])[:450]
    json.dump(week,open(os.path.join(DATA,"week.json"),"w"))
    src="rolling (live "+str(wk-1)+"wk)" if (live is not None and wk>1) else "preseason base"
    json.dump({"season":SEASON,"week":wk,"updated":datetime.date.today().isoformat(),
               "status":"in-season" if wk>1 else "preseason","source":src,
               "note":f"Week {wk} — ROLLING projections ({src}): preseason prior shrunk toward live production + matchup + scheme + injuries."},
              open(os.path.join(DATA,"meta.json"),"w"))
    print(f"[roll] week {wk} · {len(week)} players · source {src} · {len(inj)} injuries")

if __name__=="__main__": main()
