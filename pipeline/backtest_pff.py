#!/usr/bin/env python3
"""
Walk-forward backtest of the PFF layer, 2025 season.

For each test week W: build a baseline rolling projection from nflverse through W-1,
apply the SHIPPED PFF factors (talent + graded matchup, same formulas/caps as
weekly_update.py) using POINT-IN-TIME PFF grades (weeks 1..W-1 only, no lookahead),
and score both against the actual week-W PPR. Reports MAE delta by position.

PFF weekly pulls live in ../pff_hist/2025/wkNN_<ep>.json (single-week each).
"""
import json, os, re, glob, math, collections
import pandas as pd, numpy as np, requests, io

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))            # NFL DATA (real)
HIST = os.path.join(ROOT, "pff_hist", "2025")
NFV  = "https://github.com/nflverse/nflverse-data/releases/download"
TEAMFIX = {"ARZ":"ARI","BLT":"BAL","CLV":"CLE","HST":"HOU"}
def tfix(t): return TEAMFIX.get(str(t), str(t))
def norm(s): return re.sub(r'[^a-z]','',re.sub(r'\b(jr|sr|ii|iii|iv|v)\b','',str(s).lower()))
def clamp(x,a,b): return max(a,min(b,x))

def load_ep(week, ep):
    f = os.path.join(HIST, f"wk{week:02d}_{ep}.json")
    if not os.path.exists(f): return []
    d = json.load(open(f))
    if isinstance(d, dict):
        for k in d:
            if isinstance(d[k], list): return d[k]
    return d if isinstance(d, list) else []

# ---------- point-in-time PFF snapshot through (week-1) ----------
def pff_through(upto):   # inclusive of weeks 1..upto
    # player talent
    ry=collections.defaultdict(float); rr=collections.defaultdict(float)   # recv yards / routes
    elu_n=collections.defaultdict(float); elu_d=collections.defaultdict(float)  # elusive*att / att
    pg_n=collections.defaultdict(float); pg_d=collections.defaultdict(float)     # pass_grade*db / db
    pos={}
    # team defense
    cov_n=collections.defaultdict(float); cov_d=collections.defaultdict(float)
    run_n=collections.defaultdict(float); run_d=collections.defaultdict(float)
    for w in range(1, upto+1):
        for r in load_ep(w,"receiving"):
            k=norm(r.get("player")); rt=r.get("routes") or 0; yd=r.get("yards") or 0
            if rt: rr[k]+=rt; ry[k]+=yd; pos.setdefault(k,r.get("position","WR"))
        for r in load_ep(w,"rushing"):
            k=norm(r.get("player")); at=r.get("attempts") or 0; el=r.get("elusive_rating")
            if at and el is not None: elu_n[k]+=el*at; elu_d[k]+=at; pos[k]="RB"
        for r in load_ep(w,"passing"):
            k=norm(r.get("player")); db=r.get("dropbacks") or 0; g=r.get("grades_pass")
            if db and g is not None: pg_n[k]+=g*db; pg_d[k]+=db; pos.setdefault(k,"QB")
        for r in load_ep(w,"defense"):   # defense_summary carries BOTH coverage & run-def grades
            t=tfix(r.get("team"))
            sc=r.get("snap_counts_coverage") or 0; gc=r.get("grades_coverage_defense")
            if sc and gc is not None: cov_n[t]+=gc*sc; cov_d[t]+=sc
            sr=r.get("snap_counts_run_defense") or 0; gr=r.get("grades_run_defense")
            if sr and gr is not None: run_n[t]+=gr*sr; run_d[t]+=sr
    yprr={k: ry[k]/rr[k] for k in rr if rr[k]>=30}
    elu={k: elu_n[k]/elu_d[k] for k in elu_d if elu_d[k]>=15}
    pgr={k: pg_n[k]/pg_d[k] for k in pg_d if pg_d[k]>=30}
    dcov={t: cov_n[t]/cov_d[t] for t in cov_d if cov_d[t]}
    drun={t: run_n[t]/run_d[t] for t in run_d if run_d[t]}
    covm=np.mean(list(dcov.values())) if dcov else 60.0
    runm=np.mean(list(drun.values())) if drun else 60.0
    return dict(yprr=yprr,elu=elu,pgr=pgr,dcov=dcov,drun=drun,covm=covm,runm=runm)

# ---------- PFF factor (EXACT shipped formulas) ----------
def pff_factor(pos, name, opp, S):
    k=norm(name); tf=1.0
    if pos in ("WR","TE") and k in S["yprr"]: tf=1+0.08*(clamp((S["yprr"][k]-1.2)/1.6,0,1)-0.5)*2
    elif pos=="RB" and k in S["elu"]:         tf=1+0.10*(clamp((S["elu"][k]-40)/55,0,1)-0.5)*2
    elif pos=="QB" and k in S["pgr"]:         tf=1+0.08*(clamp((S["pgr"][k]-55)/35,0,1)-0.5)*2
    tf=clamp(tf,0.94,1.08)
    mfp=1.0; o=tfix(opp)
    if pos in ("WR","TE") and o in S["dcov"]: mfp=1+0.10*(S["covm"]-S["dcov"][o])/8
    elif pos=="RB" and o in S["drun"]:        mfp=1+0.10*(S["runm"]-S["drun"][o])/8
    elif pos=="QB" and o in S["dcov"]:        mfp=1+0.07*(S["covm"]-S["dcov"][o])/8
    mfp=clamp(mfp,0.90,1.12)
    return tf, mfp   # decomposed

def main():
    print("loading nflverse 2025 weekly...")
    r=requests.get(f"{NFV}/stats_player/stats_player_week_2025.csv",timeout=90); r.raise_for_status()
    W=pd.read_csv(io.StringIO(r.text),low_memory=False)
    W=W[W.position.isin(["QB","RB","WR","TE"])].copy()
    W["fp"]=pd.to_numeric(W.get("fantasy_points_ppr"),errors="coerce").fillna(0)
    tcol="team" if "team" in W.columns else "recent_team"
    W=W.rename(columns={tcol:"team"})
    maxwk=int(W.week.max()); print("weeks available:",maxwk)

    # accumulate SSE for baseline + 3 variants (talent-only, matchup-only, both), by pos and by phase
    def blank(): return dict(n=0,e0=0.0,et=0.0,em=0.0,eb=0.0,mat_better=0,mat_moved=0)
    agg=collections.defaultdict(blank)
    for Wk in range(5, maxwk+1):
        S=pff_through(Wk-1)
        hist=W[W.week<Wk]; cur=W[W.week==Wk]
        phase="early(5-9)" if Wk<=9 else "late(10+)"
        for _,row in cur.iterrows():
            pid=row.player_id; pos=row.position; name=row.player_display_name
            h=hist[hist.player_id==pid].sort_values("week")
            if len(h)<2: continue
            s2d=h.fp.mean(); l3=h.fp.tail(3).mean(); proj0=0.5*s2d+0.5*l3
            if proj0<3: continue
            act=row.fp; tf,mfp=pff_factor(pos,name,row.get("opponent_team"),S)
            pt=proj0*tf; pm=proj0*clamp(mfp,0.90,1.12); pb=proj0*clamp(tf*mfp,0.88,1.14)
            # SMART: talent only for TE/QB, no matchup, and only once PFF sample is mature (Wk>=8)
            smart = tf if (pos in ("TE","QB") and Wk>=8) else 1.0
            ps=proj0*smart
            for key in ("ALL",pos,pos+" "+phase):
                a=agg[key]; a["n"]+=1
                a["e0"]+=abs(proj0-act); a["et"]+=abs(pt-act); a["em"]+=abs(pm-act); a["eb"]+=abs(pb-act)
                a["es"]=a.get("es",0.0)+abs(ps-act)
                if mfp!=1.0:
                    a["mat_moved"]+=1
                    if abs(pm-act)<abs(proj0-act): a["mat_better"]+=1
    def line(key):
        a=agg.get(key)
        if not a or not a["n"]: return
        n=a["n"]; m0=a["e0"]/n
        print(f"{key:16s} {n:5d} {m0:8.3f} {a['et']/n-m0:+8.3f} {a['em']/n-m0:+8.3f} {a['eb']/n-m0:+8.3f} {a.get('es',0)/n-m0:+8.3f}")
    print(f"\n{'group':16s} {'n':>5s} {'MAEbase':>8s} {'dTALENT':>8s} {'dMATCH':>8s} {'dBOTH':>8s} {'dSMART':>8s}")
    print("-"*74)
    for key in ("ALL","QB","RB","WR","TE"): line(key)
    print("-"*74)
    for pos in ("QB","RB","WR","TE"):
        for ph in ("early(5-9)","late(10+)"): line(pos+" "+ph)
    print("\ndX = change in MAE from that layer alone (negative = REDUCES error = good).")

if __name__=="__main__": main()
