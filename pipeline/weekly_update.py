#!/usr/bin/env python3
"""Throw in the Towel — weekly HYBRID pipeline (GitHub Actions, no local files).
Projections are a HYBRID: (1) a shrinkage 'rolling' talent estimate (preseason prior shrunk
toward in-season production) and (2) the trained weekly ML model (weekly_model_v2) re-run each
week on live features. The two are blended, with ML weight growing as games accumulate.
Ownership is REAL ESPN % rostered (+ weekly change), not an estimate. Then matchup x scheme x
injury. Refreshes ADP + FantasyPros. Covers ALL skill players (breakouts included)."""
import json, math, io, os, datetime
import pandas as pd, numpy as np, requests
try:
    import joblib
except Exception:
    joblib = None

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); DATA = os.path.join(ROOT, "data")
SEASON = 2026
NFV = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
MODEL_PATH = os.path.join(ROOT, "engine", "weekly_model_v2.joblib")
FEAT_ORDER = ['l4','l1','s2d','gp','dvp','is_QB','is_RB','is_WR','is_TE','wopr_l4','tgtsh_l4','car_l4','wopr_tr','injc']
TF = {"LAR": "LA", "JAC": "JAX"}; fix = lambda t: TF.get(str(t), str(t)); clamp = lambda x,a,b: max(a,min(b,x))
def load(n): return json.load(open(os.path.join(HERE, n)))
def getcsv(u): r=requests.get(u,timeout=90); r.raise_for_status(); return pd.read_csv(io.StringIO(r.text), low_memory=False)
def norm(s): import re; return re.sub(r'[^a-z]','',re.sub(r'\b(jr|sr|ii|iii|iv|v)\b','',str(s).lower()))
REPL = {"QB":10.0,"RB":5.0,"WR":5.0,"TE":3.5}   # replacement-level prior for unknown/breakout players
INJC = {"O":3,"D":2,"Q":1}

def load_model():
    if joblib is None: print("[roll] joblib unavailable — shrinkage only"); return None
    try: m=joblib.load(MODEL_PATH); print("[roll] ML model loaded (hybrid on)"); return m
    except Exception as e: print("[roll] model load failed — shrinkage only:",e); return None

def espn_ownership():
    """Real ESPN % rostered (+ weekly change). Returns {norm(name): {own, chg}}."""
    try:
        url=f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{SEASON}/players?view=kona_player_info"
        flt={"players":{"limit":2000,"sortPercOwned":{"sortPriority":1,"sortAsc":False}}}
        h={"x-fantasy-filter":json.dumps(flt,separators=(",",":")),"user-agent":"Mozilla/5.0","accept":"application/json"}
        r=requests.get(url,headers=h,timeout=75); r.raise_for_status()
        d=r.json(); pl=d if isinstance(d,list) else d.get("players",[]); out={}
        for p in pl:
            x=p.get("player",p); o=x.get("ownership") or {}; po=o.get("percentOwned")
            if po is None: continue
            k=norm(x.get("fullName","")); po=round(float(po),1)
            if k not in out or po>out[k]["own"]:          # keep the real player, not a same-name scrub
                out[k]={"own":po,"chg":round(float(o.get("percentChange") or 0),1)}
        print(f"[roll] ESPN ownership: {len(out)} players")
        return out
    except Exception as e:
        print("[roll] ESPN ownership failed — synthetic fallback:",e); return {}

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
        inj=getcsv(f"{NFV}/injuries/injuries_{SEASON}.csv")
        cur=inj[inj.week==wk]
        rep=cur[cur.report_status.isin(["Out","Doubtful","Questionable"])]
        if not len(rep):                                    # current-week report not published yet
            av=inj[inj.week<wk].week
            if len(av): cur=inj[inj.week==int(av.max())]     # carry forward the latest available report
        m={"Out":"O","Doubtful":"D","Questionable":"Q"}
        return {norm(r.full_name):m.get(r.report_status,"") for _,r in cur.iterrows() if r.report_status in m}
    except Exception: return {}

def main():
    refresh_adp(); refresh_fpros()
    model=load_model(); OWN=espn_ownership()
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
    rows=[]; FEAT={}   # FEAT[player_id] = live ML features (usage), dvp/injc added at projection time
    if live is not None and len(live):
        tcol="team" if "team" in live.columns else ("recent_team" if "recent_team" in live.columns else None)
        live=live[live.position.isin(["QB","RB","WR","TE"])&(live.week<=wk)].copy()
        for c in ["fantasy_points_ppr","rushing_yards","rushing_tds","receiving_yards","receiving_tds","receptions","target_share","wopr","carries","targets"]:
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
        # per-player rolling talent (shrinkage) + ML feature build
        for pid,grp in live.sort_values(["player_id","week"]).groupby("player_id"):
            fp=grp.fantasy_points_ppr; gp=int(grp.week.nunique())
            nm=grp.player_display_name.iloc[-1]; pos=grp.position.iloc[-1]; team=fix(str(grp.team.iloc[-1]))
            std=fp.sum()/max(gp,1)
            recent=grp[grp.week>wk-4].fantasy_points_ppr
            l3v=recent.mean() if len(recent) else std
            observed=0.55*std+0.45*l3v
            b=base.get(norm(nm)); prior=float(b["base"]) if b is not None else REPL.get(pos,5.0); K=5.0 if b is not None else 3.0
            rolling=(K*prior+gp*observed)/(K+gp)              # <-- shrink prior toward observed as gp grows
            spark=[round(float(x),1) for x in grp.sort_values("week").fantasy_points_ppr]
            rows.append(dict(pid=pid,name=nm,pos=pos,team=team,roll=rolling,std=std,l3=l3v,gp=gp,
                             tgt=float(grp.target_share.mean() or 0),base=prior,spark=spark,
                             rk=(int(b["rk"]) if b is not None else 999),pr=(b["pr"] if b is not None else "")))
            if gp>=2 and model is not None:                  # ML needs >=2 games (as trained)
                FEAT[pid]=dict(l4=float(fp.tail(4).mean()),l1=float(fp.iloc[-1]),s2d=float(fp.mean()),gp=gp,
                               wopr_l4=float(grp.wopr.tail(4).mean()),tgtsh_l4=float(grp.target_share.tail(4).mean()),
                               car_l4=float(grp.carries.tail(4).mean()),wopr_tr=float(grp.wopr.tail(4).mean()-grp.wopr.mean()),pos=pos)
    # add base-only players who haven't logged live stats yet (early/bye)
    haveN={norm(x["name"]) for x in rows}
    for k,b in base.items():
        if k not in haveN:
            rows.append(dict(pid=None,name=b["name"],pos=b["pos"],team=fix(str(b["team"])),roll=float(b["base"]),std=float(b["base"]),l3=float(b["base"]),gp=0,tgt=0,base=float(b["base"]),spark=[],rk=int(b["rk"]),pr=b["pr"]))
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
        # ---- HYBRID: re-run the ML model on live features, blend with shrinkage ----
        shrink=proj; mlp=None
        f=FEAT.get(r["pid"])
        if f is not None:
            fo=fix(o) if o else None
            dvpv=dvp.get(f"{fo}|{pos}", lg[pos]) if fo else lg[pos]
            injc=INJC.get(inj.get(norm(r["name"]),""),0)
            X=[[f["l4"],f["l1"],f["s2d"],f["gp"],dvpv,int(pos=="QB"),int(pos=="RB"),int(pos=="WR"),int(pos=="TE"),
                f["wopr_l4"],f["tgtsh_l4"],f["car_l4"],f["wopr_tr"],injc]]
            try:
                mlp=float(model.predict(pd.DataFrame(X,columns=FEAT_ORDER))[0])
                wt=min(0.7, r["gp"]/(r["gp"]+3.0))           # ML weight grows with games played
                proj=wt*mlp+(1-wt)*shrink
            except Exception: mlp=None
        trend=round(r["l3"]-r["std"],1)                       # + = heating up
        hot = r["gp"]>=1 and r["l3"]>=12 and r["l3"]>r["base"]*1.3
        if hot: why.insert(0,"🔥 trending up")
        # ---- REAL ESPN ownership (+ weekly change); synthetic only if ESPN has no row ----
        eo=OWN.get(norm(r["name"])); chg=0.0
        if eo is not None: own=int(round(eo["own"])); chg=eo["chg"]
        else: own=max(1,min(100,round(100/(1+math.exp((r["rk"]-95)/22))))) if r["rk"]<900 else max(1,min(60,round(r["l3"]*3)))
        week.append({"name":r["name"],"pos":pos,"team":tm,"opp":od,"proj":round(proj,1),"base":round(r["base"],1),
                     "roll":round(b,1),"ml":(round(mlp,1) if mlp is not None else None),"form":round(r["l3"],1),"trend":trend,"gp":r["gp"],
                     "matchup":("good" if proj>b*1.03 else "tough" if proj<b*0.97 else "even"),
                     "delta":round(proj-r["base"],1),"own":own,"chg":chg,"inj":inj.get(norm(r["name"]),""),
                     "spark":r.get("spark",[]),"why":"; ".join(why),"rk":r["rk"],"pr":r["pr"]})
    # ---- VACATED OPPORTUNITY: injured starter -> next man up gets the touches ----
    try:
        dc=getcsv(f"{NFV}/depth_charts/depth_charts_{SEASON}.csv")
        dc=dc[(dc.dt==dc.dt.max())&(dc.pos_abb.isin(["QB","RB","WR","TE"]))].copy()
        dc["k"]=dc.player_name.apply(norm)
        depth={}
        for (tm,pos),gg in dc.sort_values("pos_rank").groupby(["team","pos_abb"]):
            depth[(fix(str(tm)),pos)]=list(gg.k)
    except Exception as e:
        depth={}; print("[roll] depth charts unavailable:",e)
    ALPHA={"RB":0.75,"WR":0.30,"TE":0.55,"QB":0.85}   # share of the vacated role the next man inherits
    byk={norm(w["name"]):w for w in week}; bumped=0
    for w in week:
        st=w.get("inj")
        if st not in ("O","D"): continue
        vac=w.get("roll") or w.get("base") or 0
        if vac<6: continue                                   # only a real starter's role is worth redistributing
        order=depth.get((w["team"],w["pos"]),[]); me=norm(w["name"])
        if me not in order: continue
        for nxt in order[order.index(me)+1:]:
            b=byk.get(nxt)
            if not b or b.get("inj")=="O": continue          # skip a backup who is also out
            a=ALPHA.get(w["pos"],0.5)*(1.0 if st=="O" else 0.5)   # Doubtful = half the bump
            newp=min(round(b["proj"]+a*vac,1), max(b["proj"], round(vac*0.95,1)))
            up=round(newp-b["proj"],1)
            if up>0.3:
                b["oppUp"]=up; b["oppFrom"]=w["name"]; b["proj"]=newp
                b["delta"]=round(newp-b["base"],1); b["matchup"]="good"
                b["why"]=("▲ "+w["name"].split()[-1]+" out — inherits touches")+("; "+b["why"] if b["why"] else "")
                bumped+=1
            break
    print(f"[roll] vacated-opportunity bumps: {bumped}")
    week=sorted(week,key=lambda x:-x["proj"])[:450]
    json.dump(week,open(os.path.join(DATA,"week.json"),"w"))
    hyb="hybrid ML+shrinkage" if model is not None else "shrinkage"
    src=f"rolling {hyb} (live {wk-1}wk)" if (live is not None and wk>1) else "preseason base"
    json.dump({"season":SEASON,"week":wk,"updated":datetime.date.today().isoformat(),
               "status":"in-season" if wk>1 else "preseason","source":src,
               "note":f"Week {wk} — HYBRID rolling projections ({src}): shrinkage prior blended with weekly ML model re-run on live features + matchup + scheme + injuries. Ownership = live ESPN % rostered."},
              open(os.path.join(DATA,"meta.json"),"w"))
    print(f"[roll] week {wk} · {len(week)} players · {hyb} · {len(FEAT)} ML-scored · {len(inj)} injuries")

if __name__=="__main__": main()
