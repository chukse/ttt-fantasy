#!/usr/bin/env python3
"""
OPEN-DATA trench rankings (OL + opponent-adjusted DEF), 1-32, plus upcoming-week
matchups and start/sit leans. ZERO PFF — built entirely from nflverse play-by-play
(EPA, success, sacks, QB hits, CPOE) + the ridge opponent-adjustment.

Writes data/trenches.json with the SAME schema as the PFF builder (trenches_weekly.py),
so the app renders it unchanged. "Grade" fields are pseudo-grades (0-99) derived from
the nflverse composites; rate/EPA fields are the real nflverse values.

This is the PUBLIC edition's trench source. The PFF version (trenches_weekly.py) stays
for the private/local edition only.
"""
import os, json, datetime
import numpy as np, pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NFL  = os.path.join(ROOT, "nflverse_daily", "data")
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SEASON = 2026

def z(s): return (s - s.mean()) / s.std(ddof=0)
def resid_z(y, x):
    b = np.cov(x, y, ddof=0)[0, 1] / np.var(x); return z(y - b * x)
def pg(zs):  # pseudo-grade on a PFF-like 0-99 scale from a z-score
    return (50 + 15 * zs).clip(1, 99).round(1)

# ---------- weeks ----------
games = pd.read_parquet(os.path.join(NFL, "games.parquet"))
gs = games[games.season == SEASON]
done = sorted(gs[gs.home_score.notna()].week.unique())
LATEST = int(max(done)) if done else 1
upc = [w for w in sorted(gs.week.unique()) if w > LATEST]
UPCOMING = int(upc[0]) if upc else LATEST
# align to the projections' canonical week (meta.json) so every facet agrees
try:
    _mw = json.load(open(os.path.join(DATA, "meta.json"))).get("week")
    if _mw: UPCOMING = int(_mw); LATEST = max(1, int(_mw) - 1)
except Exception: pass
print(f"[trenches-nopff] season {SEASON} · reg weeks 1-{LATEST} (nflverse only) · upcoming = wk{UPCOMING}")

# ---------- load pbp ----------
cols = ["posteam", "defteam", "pass", "rush", "qb_dropback", "epa", "success", "sack",
        "qb_hit", "cpoe", "yards_gained", "complete_pass", "interception", "penalty", "penalty_team"]
pbp_all = pd.read_parquet(os.path.join(NFL, "play_by_play_2026.parquet"),
                          columns=[c for c in cols if c in pd.read_parquet(os.path.join(NFL, "play_by_play_2026.parquet")).columns])
# re-read safely with only existing columns
have = list(pd.read_parquet(os.path.join(NFL, "play_by_play_2026.parquet"), columns=None).columns)
cols = [c for c in cols if c in have]
pbp_all = pd.read_parquet(os.path.join(NFL, "play_by_play_2026.parquet"), columns=cols)
for c in ["penalty"]:
    if c not in pbp_all: pbp_all[c] = 0

# ================= OFFENSIVE LINE (open-data proxies, per posteam) =================
o = pbp_all[pbp_all.posteam.notna()]
orows = []
for tm, g in o.groupby("posteam"):
    db = g[g.qb_dropback == 1]; rus = g[g["rush"] == 1]
    ndb = max(len(db), 1); nrush = max(len(rus), 1)
    orows.append(dict(team=tm,
        sack_rate=100 * db.sack.sum() / ndb,
        qbhit_rate=100 * db.qb_hit.sum() / ndb,
        rush_epa=rus.epa.mean(), rush_sr=rus.success.mean(),
        stuff=100 * (rus.yards_gained <= 0).mean(),
        expl_run=100 * (rus.yards_gained >= 10).mean(),
        o_pen=100 * g.penalty.sum() / max(len(g), 1)))
O = pd.DataFrame(orows).set_index("team")

# pass protection: fewer sacks + hits allowed = better
protect_z = -(0.6 * z(O.sack_rate) + 0.4 * z(O.qbhit_rate))
# run blocking proxy: EPA/SR up, stuffs down, explosives up
runblk_z = 0.45 * z(O.rush_epa) + 0.30 * z(O.rush_sr) - 0.20 * z(O.stuff) + 0.05 * z(O.expl_run)

P = pd.DataFrame(index=O.index); P.index.name = "team"
P["pb_grade"] = pg(z(protect_z)); P["tps_grade"] = P["pb_grade"]
P["press_rate"] = O.qbhit_rate.round(2); P["sack_rate"] = O.sack_rate.round(2); P["hurry_rate"] = O.qbhit_rate.round(2)
P["pen_rate"] = O.o_pen.round(2)
R = pd.DataFrame(index=O.index); R.index.name = "team"
R["rb_grade"] = pg(z(runblk_z)); R["gap_grade"] = R["rb_grade"]; R["zone_grade"] = R["rb_grade"]
R["ybc_att"] = O.rush_epa  # orthogonalized "results" proxy

Gp = z(P.pb_grade)
Op_perp = resid_z(z(-(0.75 * z(P.press_rate) + 0.25 * z(P.sack_rate))), Gp)
P["pass_score"] = 0.60 * Gp + 0.40 * Op_perp
Gr = z(R.rb_grade)
Or_perp = resid_z(z(R.ybc_att), Gr)
R["run_score"] = 0.70 * Gr + 0.30 * Or_perp
OL = P.join(R)
OL["pass_rank"] = OL.pass_score.rank(ascending=False).astype(int)
OL["run_rank"]  = OL.run_score.rank(ascending=False).astype(int)
OL["overall"]   = 0.52 * z(OL.pass_score) + 0.43 * z(OL.run_score) - 0.05 * z(OL.pen_rate)
OL = OL.sort_values("overall", ascending=False); OL["rank"] = range(1, len(OL) + 1)

# ================= DEFENSE (open-data, per defteam) =================
dft = pbp_all[pbp_all.defteam.notna()]
drows = []
for tm, g in dft.groupby("defteam"):
    pas = g[g["pass"] == 1]; rus = g[g["rush"] == 1]; db = g[g.qb_dropback == 1]
    ndb = max(len(db), 1)
    drows.append(dict(team=tm,
        sack_rate=100 * db.sack.sum() / ndb, qbhit_rate=100 * db.qb_hit.sum() / ndb,
        pass_epa=pas.epa.mean(), pass_sr=pas.success.mean(),
        expl_pass=100 * ((pas.complete_pass == 1) & (pas.yards_gained >= 20)).mean(),
        int_rate=100 * pas.interception.mean(), cpoe_allow=pas.cpoe.mean(),
        rush_epa=rus.epa.mean(), rush_sr=rus.success.mean(),
        expl_run=100 * (rus.yards_gained >= 10).mean(),
        stuff_rate=100 * (rus.yards_gained <= 0).mean(),
        d_pen=100 * g.penalty.sum() / max(len(g), 1)))
DF = pd.DataFrame(drows).set_index("team")

# pseudo-grades (higher = better defense)
prg_z = 0.5 * z(DF.sack_rate) + 0.5 * z(DF.qbhit_rate)
cov_z = -(0.5 * z(DF.pass_epa) + 0.25 * z(DF.cpoe_allow) + 0.25 * z(DF.expl_pass))
run_z = -(0.6 * z(DF.rush_epa) + 0.2 * z(DF.rush_sr)) + 0.2 * z(DF.stuff_rate)
DF["pr_grade"] = pg(prg_z); DF["cov_grade"] = pg(cov_z); DF["run_grade"] = pg(run_z)

Gpass = z(0.45 * prg_z + 0.55 * cov_z)
res_pass = z(-0.30 * z(DF.pass_epa) - 0.15 * z(DF.pass_sr) - 0.10 * z(DF.expl_pass)
             + 0.12 * z(DF.sack_rate) + 0.10 * z(DF.qbhit_rate) + 0.08 * z(DF.int_rate) - 0.07 * z(DF.cpoe_allow))
DF["pass_def"] = 0.55 * Gpass + 0.45 * resid_z(res_pass, Gpass)
Grun = z(run_z)
res_run = z(-0.35 * z(DF.rush_epa) - 0.22 * z(DF.rush_sr) - 0.13 * z(DF.expl_run) + 0.30 * z(DF.stuff_rate))
DF["run_def"] = 0.60 * Grun + 0.40 * resid_z(res_run, Grun)
DF["passrush_rank"] = (0.5 * z(DF.sack_rate) + 0.5 * z(DF.qbhit_rate)).rank(ascending=False).astype(int)
DF["cov_rank"] = (-(z(DF.pass_epa) + z(DF.cpoe_allow) + 0.5 * z(DF.expl_pass))).rank(ascending=False).astype(int)
DF["pass_rank"] = DF.pass_def.rank(ascending=False).astype(int)
DF["run_rank"]  = DF.run_def.rank(ascending=False).astype(int)
DF["overall"] = 0.55 * z(DF.pass_def) + 0.45 * z(DF.run_def) - 0.05 * z(DF.d_pen)
DF = DF.sort_values("overall", ascending=False); DF["rank"] = range(1, len(DF) + 1)

# ---------- opponent adjustment (ridge APM on EPA) ----------
dd = pbp_all[(pbp_all.posteam.notna()) & (pbp_all.defteam.notna()) & (pbp_all.epa.notna())
             & ((pbp_all["pass"] == 1) | (pbp_all["rush"] == 1))].copy()
teams = sorted(set(dd.posteam) | set(dd.defteam)); idx = {t: i for i, t in enumerate(teams)}; nt = len(teams)
def fit(sub, lam=100.0):
    y = sub.epa.values - sub.epa.mean(); m = len(sub); X = np.zeros((m, 2 * nt))
    X[np.arange(m), sub.posteam.map(idx).values] = 1; X[np.arange(m), nt + sub.defteam.map(idx).values] = 1
    beta = np.linalg.solve(X.T @ X + lam * np.eye(2 * nt), X.T @ y)
    return pd.Series(beta[nt:], index=teams)
adj_all, adj_pass, adj_rush = fit(dd), fit(dd[dd["pass"] == 1]), fit(dd[dd["rush"] == 1])
ADJ = pd.DataFrame({"adj_def": adj_all, "adj_pass": adj_pass, "adj_rush": adj_rush})
ADJ["adj_rank"] = ADJ.adj_def.rank().astype(int)          # more negative = better = rank 1
ADJ["adj_pass_rank"] = ADJ.adj_pass.rank().astype(int)
ADJ["adj_rush_rank"] = ADJ.adj_rush.rank().astype(int)

# ================= UPCOMING-WEEK MATCHUPS + START/SIT LEANS =================
olx = pd.DataFrame(index=OL.index)
olx["olp"] = z(OL.pass_score); olx["olr"] = z(OL.run_score); olx["olo"] = z(OL.overall)
olx["olp_rk"] = OL.pass_rank; olx["olr_rk"] = OL.run_rank
dfx = pd.DataFrame(index=DF.index)
dfx["dpass"] = z(DF.pass_def); dfx["drun"] = z(DF.run_def); dfx["dovr"] = z(DF.overall)
dfx["drush"] = z(0.5 * z(DF.sack_rate) + 0.5 * z(DF.qbhit_rate))
dfx["dpass_rk"] = DF.pass_rank; dfx["drun_rk"] = DF.run_rank; dfx["dovr_rk"] = DF["rank"]; dfx["drush_rk"] = DF.passrush_rank
gU = gs[gs.week == UPCOMING][["home_team", "away_team"]]
matchups, leans, team_adj = [], [], {}
for _, r in gU.iterrows():
    for off, opp in [(r.away_team, r.home_team), (r.home_team, r.away_team)]:
        if off not in olx.index or opp not in dfx.index: continue
        oo, de = olx.loc[off], dfx.loc[opp]
        pass_edge = oo.olp - de.drush; run_edge = oo.olr - de.drun
        matchups.append(dict(off=off, opp=opp, pass_edge=round(pass_edge, 2), run_edge=round(run_edge, 2),
            olp_rk=int(oo.olp_rk), drush_rk=int(de.drush_rk), olr_rk=int(oo.olr_rk), drun_rk=int(de.drun_rk)))
        rb_l = oo.olr - de.drun; pas_l = 0.5 * oo.olp - de.dpass
        dst_l = 0.55 * de.dovr + 0.45 * (de.drush - oo.olp) - 0.25 * oo.olo
        leans.append(dict(off=off, opp=opp, rb=round(rb_l, 2), pas=round(pas_l, 2), dst=round(dst_l, 2),
            olr_rk=int(oo.olr_rk), drun_rk=int(de.drun_rk), olp_rk=int(oo.olp_rk), dpass_rk=int(de.dpass_rk), dovr_rk=int(de.dovr_rk)))
        team_adj[off] = {"rb": round(rb_l, 2), "pass": round(pas_l, 2)}
L = pd.DataFrame(leans)
def rank_leans(col):
    s = L.sort_values(col, ascending=False)
    pick = lambda row: {"team": row.opp if col == "dst" else row.off, "opp": row.off if col == "dst" else row.opp,
                        "edge": round(row[col], 2),
                        "a": int(row.olr_rk if col == "rb" else row.olp_rk),
                        "b": int(row.drun_rk if col == "rb" else row.dpass_rk if col == "pas" else row.dovr_rk)}
    return {"start": [pick(r) for _, r in s.head(8).iterrows()], "sit": [pick(r) for _, r in s.tail(8).iloc[::-1].iterrows()]}

# ---------- assemble JSON (identical schema) ----------
def ol_row(t):
    r = OL.loc[t]
    return {"team": t, "rank": int(r["rank"]), "pass_rank": int(r.pass_rank), "run_rank": int(r.run_rank),
            "pb_grade": round(float(r.pb_grade), 1), "press_rate": round(float(r.press_rate), 2),
            "sack_rate": round(float(r.sack_rate), 2), "rb_grade": round(float(r.rb_grade), 1),
            "gap_grade": round(float(r.gap_grade), 1), "zone_grade": round(float(r.zone_grade), 1)}
def df_row(t):
    r = DF.loc[t]; a = ADJ.loc[t] if t in ADJ.index else None
    out = {"team": t, "rank": int(r["rank"]), "pass_rank": int(r.pass_rank), "run_rank": int(r.run_rank),
           "passrush_rank": int(r.passrush_rank), "cov_rank": int(r.cov_rank),
           "pr_grade": round(float(r.pr_grade), 1), "cov_grade": round(float(r.cov_grade), 1),
           "run_grade": round(float(r.run_grade), 1), "pass_epa": round(float(r.pass_epa), 3),
           "rush_epa": round(float(r.rush_epa), 3)}
    if a is not None:
        out.update(adj_rank=int(a.adj_rank), adj_pass_rank=int(a.adj_pass_rank), adj_rush_rank=int(a.adj_rush_rank))
    return out

out = {
    "season": SEASON, "week": UPCOMING, "through_week": LATEST,
    "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    "edition": "public",
    "note": f"OL + opponent-adjusted DEF trench rankings through wk{LATEST}; matchups/leans for wk{UPCOMING}. nflverse EPA + pressure/sack rates (open data only).",
    "ol":  [ol_row(t) for t in OL.index],
    "def": [df_row(t) for t in DF.index],
    "matchups": sorted(matchups, key=lambda x: -(x["pass_edge"] + x["run_edge"])),
    "leans": {"rb": rank_leans("rb"), "pass": rank_leans("pas"), "dst": rank_leans("dst")},
    "team_adj": team_adj,
}
os.makedirs(DATA, exist_ok=True)
json.dump(out, open(os.path.join(DATA, "trenches.json"), "w"), separators=(",", ":"))
print(f"[trenches-nopff] wrote data/trenches.json — OL+DEF 1-32, {len(matchups)} matchup sides, leans for wk{UPCOMING}")
print("  OL top5 :", [o["team"] for o in out["ol"][:5]])
print("  DEF top5:", [d["team"] for d in out["def"][:5]])
print("  RB smash:", [x["team"] for x in out["leans"]["rb"]["start"][:4]])
print("  Pass smash:", [x["team"] for x in out["leans"]["pass"]["start"][:4]])
print("  DST streams:", [x["team"] for x in out["leans"]["dst"]["start"][:4]])
