#!/usr/bin/env python3
"""
TRENCHES WEEKLY — rolling OL + Defense trench rankings + this-week matchups + start/sit leans.

Each run pulls PFF facets cumulatively for regular-season weeks 1..latest (compounding sample),
rebuilds the OL rankings and the opponent-ADJUSTED defense rankings (same decorrelated scoring
as the standalone builds), crosses them for the upcoming week, derives fantasy start/sit leans,
and writes data/trenches.json for the app.

MUST run locally (PFF Developer API via restish needs the cached OAuth token; GitHub Actions
can't authenticate). Pull syntax: `--week 1,2,3` (comma) = cumulative reg-season aggregate.
Sources: PFF facet-offense-(blocking/pass-blocking/run-blocking) + passing/rushing;
facet-defense-(summary/pass-rush/coverage/run); nflverse play_by_play + games.
"""
import json, os, subprocess, time, sys
import numpy as np, pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.dirname(HERE)
ROOT = os.path.dirname(APP)                                   # NFL DATA (real)
NFL  = os.path.join(ROOT, "nflverse_daily", "data")
WORK = os.path.join(HERE, "trenches_raw")
DATA = os.path.join(APP, "data")
RESTISH = os.path.expanduser("~/.local/bin/restish")
SEASON = 2026
P2N = {"ARZ":"ARI","BLT":"BAL","CLV":"CLE","HST":"HOU"}       # PFF -> nflverse team codes
n   = lambda t: P2N.get(str(t), str(t))
OL_POS = {"T","G","C"}

def z(s): return (s - s.mean()) / s.std(ddof=0)
def resid_z(y, x):
    b = np.cov(x, y, ddof=0)[0,1] / np.var(x); return z(y - b*x)
def wavg(df, v, w):
    d = df.dropna(subset=[v, w]); d = d[d[w] > 0]
    return np.average(d[v], weights=d[w]) if d[w].sum() else np.nan

# ---------- weeks ----------
games = pd.read_parquet(os.path.join(NFL, "games.parquet"))
gs = games[games.season == SEASON]
done = sorted(gs[gs.home_score.notna()].week.unique())
LATEST = int(max(done)) if done else 1
upc = [w for w in sorted(gs.week.unique()) if w > LATEST]
UPCOMING = int(upc[0]) if upc else LATEST
WEEKS = ",".join(str(w) for w in range(1, LATEST+1))
print(f"[trenches] season {SEASON} · reg weeks 1-{LATEST} (cumulative) · upcoming = wk{UPCOMING}")

# ---------- pull PFF facets ----------
ENDPOINTS = {
    "blocking":"facet-offense-blocking", "pass_blocking":"facet-offense-pass-blocking",
    "run_blocking":"facet-offense-run-blocking", "passing":"passing", "rushing":"rushing",
    "def_summary":"facet-defense-summary", "def_passrush":"facet-defense-pass-rush",
    "def_coverage":"facet-defense-coverage", "def_run":"facet-defense-run",
}
def pull(stem, cmd):
    out = os.path.join(WORK, stem + ".json")
    for _ in range(3):
        try:
            with open(out, "wb") as f:
                subprocess.run([RESTISH,"pff",cmd,"--league","nfl","--season",str(SEASON),"--week",WEEKS],
                               stdout=f, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=120, check=False)
            d = json.load(open(out))
            if any(isinstance(v, list) and v for v in d.values()): return out
        except Exception: pass
        time.sleep(4)
    raise RuntimeError(f"PFF pull failed: {cmd} (auth expired? re-run a restish cmd in an interactive wsl shell)")

if "--reuse" not in sys.argv:
    os.makedirs(WORK, exist_ok=True)
    for stem, cmd in ENDPOINTS.items():
        pull(stem, cmd); print(f"  pulled {stem}")

def load(stem):
    d = json.load(open(os.path.join(WORK, stem + ".json")))
    return pd.DataFrame(d[list(d.keys())[0]])

# ================= OFFENSIVE LINE =================
blk, pblk, rblk = load("blocking"), load("pass_blocking"), load("run_blocking")
qb, rb = load("passing"), load("rushing")
bo = blk[blk.position.isin(OL_POS)].copy(); po = pblk[pblk.position.isin(OL_POS)].copy()
rows = []
for tm, g in bo.groupby("team"):
    pg = po[po.team == tm]; sn = g.snap_counts_pass_block.sum()
    tps_sn = pg.true_pass_set_snap_counts_pass_block.sum(); tps_pr = pg.true_pass_set_pressures_allowed.sum()
    rows.append(dict(team=tm,
        pb_grade=wavg(g,"grades_pass_block","snap_counts_pass_block"),
        tps_grade=wavg(pg,"true_pass_set_grades_pass_block","true_pass_set_snap_counts_pass_block"),
        press_rate=100*g.pressures_allowed.sum()/sn, sack_rate=100*g.sacks_allowed.sum()/sn,
        hurry_rate=100*g.hurries_allowed.sum()/sn))
P = pd.DataFrame(rows).set_index("team")
ro = rblk[rblk.position.isin(OL_POS)].copy(); rows = []
for tm, g in ro.groupby("team"):
    rows.append(dict(team=tm, rb_grade=wavg(g,"grades_run_block","snap_counts_run_block"),
        gap_grade=wavg(g,"gap_grades_run_block","gap_snap_counts_run_block"),
        zone_grade=wavg(g,"zone_grades_run_block","zone_snap_counts_run_block")))
R = pd.DataFrame(rows).set_index("team")
rbh = rb[rb.position.isin(["HB","FB"])].copy(); rows = []
for tm, g in rbh.groupby("team"):
    att = g.attempts.sum()
    if att: rows.append(dict(team=tm, ybc_att=((g.ypa*g.attempts).sum()-g.yards_after_contact.sum())/att))
R = R.join(pd.DataFrame(rows).set_index("team"))
pen = bo.groupby("team").agg(pen=("penalties","sum"), sn=("snap_counts_block","sum"))
P["pen_rate"] = 100*pen["pen"]/pen["sn"]
# decorrelated scoring (grade factor whole + results orthogonalized)
Gp = z(0.70*z(P.pb_grade)+0.30*z(P.tps_grade))
Op_perp = resid_z(z(-(0.75*z(P.press_rate)+0.25*z(P.sack_rate))), Gp)
P["pass_score"] = 0.60*Gp + 0.40*Op_perp
Gr = z(0.70*z(R.rb_grade)+0.15*z(R.gap_grade)+0.15*z(R.zone_grade))
Or_perp = resid_z(z(R.ybc_att), Gr)
R["run_score"] = 0.70*Gr + 0.30*Or_perp
OL = P.join(R)
OL["pass_rank"] = OL.pass_score.rank(ascending=False).astype(int)
OL["run_rank"]  = OL.run_score.rank(ascending=False).astype(int)
OL["overall"]   = 0.52*z(OL.pass_score)+0.43*z(OL.run_score)-0.05*z(OL.pen_rate)
OL = OL.sort_values("overall", ascending=False); OL["rank"] = range(1, len(OL)+1)

# ================= DEFENSE =================
pr, cov, run = load("def_passrush"), load("def_coverage"), load("def_run")
rows = {}
for tm, g in pr.groupby("team"):
    gg = g[g.snap_counts_pass_rush > 0]
    rows.setdefault(tm, {}).update(pr_grade=wavg(gg,"grades_pass_rush_defense","snap_counts_pass_rush"),
        pr_winrate=wavg(gg,"pass_rush_win_rate","pass_rush_opp"), pr_sacks=gg.sacks.sum())
for tm, g in cov.groupby("team"):
    gg = g[g.snap_counts_coverage > 0]
    rows.setdefault(tm, {}).update(cov_grade=wavg(gg,"grades_coverage_defense","snap_counts_coverage"),
        ypcs=gg.yards.sum()/gg.snap_counts_coverage.sum(), int_=gg.interceptions.sum())
for tm, g in run.groupby("team"):
    gg = g[g.snap_counts_run > 0]
    rows.setdefault(tm, {}).update(run_grade=wavg(gg,"grades_run_defense","snap_counts_run"),
        stop_pct=100*gg.stops.sum()/gg.run_stop_opp.sum())
DP = pd.DataFrame(rows).T; DP.index.name = "team"; DP["nfl"] = [n(t) for t in DP.index]
# nflverse outcome layer
pbp = pd.read_parquet(os.path.join(NFL, "play_by_play_2026.parquet"),
       columns=["posteam","defteam","pass","rush","qb_dropback","epa","success","sack","qb_hit","cpoe","yards_gained","complete_pass","interception"])
d = pbp[pbp.defteam.notna()]; nf = []
for tm, g in d.groupby("defteam"):
    pas = g[g["pass"]==1]; rus = g[g["rush"]==1]; db = g[g.qb_dropback==1]
    nf.append(dict(nfl=tm, pass_epa=pas.epa.mean(), pass_sr=pas.success.mean(),
        expl_pass=100*((pas.complete_pass==1)&(pas.yards_gained>=20)).mean(),
        sack_rate=100*db.sack.sum()/len(db), int_rate=100*pas.interception.sum()/len(pas),
        cpoe_allow=pas.cpoe.mean(), rush_epa=rus.epa.mean(), rush_sr=rus.success.mean(),
        expl_run=100*(rus.yards_gained>=10).mean(), stuff_rate=100*(rus.yards_gained<=0).mean()))
N = pd.DataFrame(nf).set_index("nfl")
DF = DP.reset_index().merge(N, on="nfl", how="inner").set_index("team")
assert len(DF) == 32, f"def merge lost teams: {len(DF)}"
Gpass = z(0.45*z(DF.pr_grade)+0.55*z(DF.cov_grade))
res_pass = z(-0.30*z(DF.pass_epa)-0.15*z(DF.pass_sr)-0.10*z(DF.expl_pass)+0.12*z(DF.sack_rate)
             +0.10*z(DF.pr_winrate)+0.08*z(DF.int_rate)-0.10*z(DF.ypcs)-0.05*z(DF.cpoe_allow))
DF["pass_def"] = 0.55*Gpass + 0.45*resid_z(res_pass, Gpass)
Grun = z(DF.run_grade)
res_run = z(-0.35*z(DF.rush_epa)-0.20*z(DF.rush_sr)-0.12*z(DF.expl_run)+0.18*z(DF.stuff_rate)+0.15*z(DF.stop_pct))
DF["run_def"] = 0.60*Grun + 0.40*resid_z(res_run, Grun)
DF["passrush_rank"] = (0.6*z(DF.pr_grade)+0.4*z(DF.pr_winrate)).rank(ascending=False).astype(int)
DF["cov_rank"] = (0.6*z(DF.cov_grade)-0.4*z(DF.ypcs)).rank(ascending=False).astype(int)
DF["pass_rank"] = DF.pass_def.rank(ascending=False).astype(int)
DF["run_rank"]  = DF.run_def.rank(ascending=False).astype(int)
summ = load("def_summary")
pen2 = summ.groupby("team").agg(pen=("penalties","sum"), sn=("snap_counts_defense","sum"))
DF = DF.join(pen2); DF["pen_rate"] = 100*DF.pen/DF.sn
DF["overall"] = 0.55*z(DF.pass_def)+0.45*z(DF.run_def)-0.05*z(DF.pen_rate)
DF = DF.sort_values("overall", ascending=False); DF["rank"] = range(1, len(DF)+1)

# ---------- opponent adjustment (ridge APM on EPA) ----------
dd = pbp[(pbp.posteam.notna())&(pbp.defteam.notna())&(pbp.epa.notna())&((pbp["pass"]==1)|(pbp["rush"]==1))].copy()
teams = sorted(set(dd.posteam)|set(dd.defteam)); idx = {t:i for i,t in enumerate(teams)}; nt = len(teams)
def fit(sub, lam=100.0):
    y = sub.epa.values - sub.epa.mean(); m = len(sub); X = np.zeros((m, 2*nt))
    X[np.arange(m), sub.posteam.map(idx).values] = 1; X[np.arange(m), nt+sub.defteam.map(idx).values] = 1
    beta = np.linalg.solve(X.T@X + lam*np.eye(2*nt), X.T@y)
    return pd.Series(beta[nt:], index=teams)
adj_all, adj_pass, adj_rush = fit(dd), fit(dd[dd["pass"]==1]), fit(dd[dd["rush"]==1])
ADJ = pd.DataFrame({"adj_def":adj_all, "adj_pass":adj_pass, "adj_rush":adj_rush})
ADJ["adj_rank"] = ADJ.adj_def.rank().astype(int)          # more negative = better = rank 1
ADJ["adj_pass_rank"] = ADJ.adj_pass.rank().astype(int)
ADJ["adj_rush_rank"] = ADJ.adj_rush.rank().astype(int)

# ================= UPCOMING-WEEK MATCHUPS + START/SIT LEANS =================
olx = pd.DataFrame(index=[n(t) for t in OL.index])
olx["olp"]=z(OL.pass_score).values; olx["olr"]=z(OL.run_score).values; olx["olo"]=z(OL.overall).values
olx["olp_rk"]=OL.pass_rank.values; olx["olr_rk"]=OL.run_rank.values
dfx = pd.DataFrame(index=[n(t) for t in DF.index])
dfx["dpass"]=z(DF.pass_def).values; dfx["drun"]=z(DF.run_def).values; dfx["dovr"]=z(DF.overall).values
dfx["drush"]=z(0.6*z(DF.pr_grade)+0.4*z(DF.pr_winrate)).values
dfx["dpass_rk"]=DF.pass_rank.values; dfx["drun_rk"]=DF.run_rank.values; dfx["dovr_rk"]=DF["rank"].values
dfx["drush_rk"]=DF.passrush_rank.values
gU = gs[gs.week == UPCOMING][["home_team","away_team"]]
matchups, leans, team_adj = [], [], {}
for _, r in gU.iterrows():
    for off, opp in [(r.away_team, r.home_team), (r.home_team, r.away_team)]:
        if off not in olx.index or opp not in dfx.index: continue
        o, de = olx.loc[off], dfx.loc[opp]
        pass_edge = o.olp - de.drush; run_edge = o.olr - de.drun
        matchups.append(dict(off=off, opp=opp, pass_edge=round(pass_edge,2), run_edge=round(run_edge,2),
            olp_rk=int(o.olp_rk), drush_rk=int(de.drush_rk), olr_rk=int(o.olr_rk), drun_rk=int(de.drun_rk)))
        rb_l = o.olr - de.drun
        pas_l = 0.5*o.olp - de.dpass
        dst_l = 0.55*de.dovr + 0.45*(de.drush - o.olp) - 0.25*o.olo
        leans.append(dict(off=off, opp=opp, rb=round(rb_l,2), pas=round(pas_l,2), dst=round(dst_l,2),
            olr_rk=int(o.olr_rk), drun_rk=int(de.drun_rk), olp_rk=int(o.olp_rk), dpass_rk=int(de.dpass_rk),
            dovr_rk=int(de.dovr_rk)))
        # compact per-team adjustment the app folds (lightly) into its lineup optimizer
        team_adj[off] = {"rb": round(rb_l,2), "pass": round(pas_l,2)}
L = pd.DataFrame(leans)
def rank_leans(col, who):   # who='off' for RB/pass, 'opp'(=dst team) for DST
    s = L.sort_values(col, ascending=False)
    pick = lambda row: {"team": row.opp if col=="dst" else row.off, "opp": row.off if col=="dst" else row.opp,
                        "edge": round(row[col],2),
                        "a": int(row.olr_rk if col=="rb" else row.olp_rk),
                        "b": int(row.drun_rk if col=="rb" else row.dpass_rk if col=="pas" else row.dovr_rk)}
    return {"start":[pick(r) for _,r in s.head(8).iterrows()], "sit":[pick(r) for _,r in s.tail(8).iloc[::-1].iterrows()]}

# ---------- assemble JSON ----------
def ol_row(t, r):
    return {"team": n(t), "rank": int(r["rank"]), "pass_rank": int(r.pass_rank), "run_rank": int(r.run_rank),
            "pb_grade": round(float(r.pb_grade),1), "press_rate": round(float(r.press_rate),2),
            "sack_rate": round(float(r.sack_rate),2), "rb_grade": round(float(r.rb_grade),1),
            "gap_grade": round(float(r.gap_grade),1), "zone_grade": round(float(r.zone_grade),1)}
def df_row(t, r):
    nflc = n(t); a = ADJ.loc[nflc] if nflc in ADJ.index else None
    out = {"team": nflc, "rank": int(r["rank"]), "pass_rank": int(r.pass_rank), "run_rank": int(r.run_rank),
           "passrush_rank": int(r.passrush_rank), "cov_rank": int(r.cov_rank),
           "pr_grade": round(float(r.pr_grade),1), "cov_grade": round(float(r.cov_grade),1),
           "run_grade": round(float(r.run_grade),1), "pass_epa": round(float(r.pass_epa),3),
           "rush_epa": round(float(r.rush_epa),3)}
    if a is not None:
        out.update(adj_rank=int(a.adj_rank), adj_pass_rank=int(a.adj_pass_rank), adj_rush_rank=int(a.adj_rush_rank))
    return out

out = {
    "season": SEASON, "week": UPCOMING, "through_week": LATEST,
    "generated": None,   # stamped by caller / left null (no Date in sandbox-safe runs)
    "note": f"OL + opponent-adjusted DEF trench rankings through wk{LATEST}; matchups/leans for wk{UPCOMING}. PFF grades + nflverse EPA, decorrelated.",
    "ol":  [ol_row(t, OL.loc[t]) for t in OL.index],
    "def": [df_row(t, DF.loc[t]) for t in DF.index],
    "matchups": sorted(matchups, key=lambda x: -(x["pass_edge"]+x["run_edge"])),
    "leans": {"rb": rank_leans("rb","off"), "pass": rank_leans("pas","off"), "dst": rank_leans("dst","opp")},
    "team_adj": team_adj,
}
import datetime
out["generated"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
os.makedirs(DATA, exist_ok=True)
json.dump(out, open(os.path.join(DATA, "trenches.json"), "w"), separators=(",", ":"))
print(f"[trenches] wrote data/trenches.json — OL+DEF 1-32, {len(matchups)} matchup sides, leans for wk{UPCOMING}")
print("  OL top5:", [o["team"] for o in out["ol"][:5]])
print("  DEF top5 (composite):", [d["team"] for d in out["def"][:5]])
print("  RB smash spots:", [f'{x["team"]}' for x in out["leans"]["rb"]["start"][:4]])
print("  Pass smash spots:", [f'{x["team"]}' for x in out["leans"]["pass"]["start"][:4]])
print("  DST streams:", [f'{x["team"]}' for x in out["leans"]["dst"]["start"][:4]])
