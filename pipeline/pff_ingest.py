#!/usr/bin/env python3
"""
PFF ingest -> data/pff.json

Reads the PFF Developer API pulls (rookie_ladder/pff_2026/*.json), joins them to our
weekly board (data/week.json) by normalized name, and produces:
  - players : per-skill-player PFF advanced stats (yprr/aDOT/elusive/btt...) for the explorer
  - teams   : per-team offense & defense unit grades (regressed to league mean; small sample)
  - matchups: this week's Favorite Matchups (top skill-player spots), ranked with a star grade
  - streams : best streaming defenses this week

Grades are blended toward the league mean because we're only a few games in — we don't
overreact to 3-game PFF samples. Team defense grades are snap-weighted.
"""
import json, os, re, math, collections, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.dirname(HERE)
PFF  = os.path.join(os.path.dirname(APP), "rookie_ladder", "pff_2026")   # ../rookie_ladder/pff_2026
DATA = os.path.join(APP, "data")
ENG  = os.path.join(APP, "engine")

# PFF team codes -> nflverse/app codes (Rams=LA & Chargers=LAC match already)
TEAMFIX = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
def tfix(t): return TEAMFIX.get(t, t)

SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}
def norm(n):
    n = (n or "").lower().replace("’", "'")
    n = re.sub(r"[^a-z0-9' ]", "", n)
    toks = [t for t in n.split() if t not in SUFFIX and t != "'"]
    return " ".join(toks).replace("'", "").strip()

def load(name):
    p = os.path.join(PFF, name)
    with open(p) as f:
        d = json.load(f)
    if isinstance(d, dict):
        for k in d:
            if isinstance(d[k], list):
                return d[k]
    return d

def pct(v, lo, hi):
    if hi <= lo: return 0.5
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))

# ---------- load PFF ----------
recv = load("receiving.json")
rush = load("rushing.json")
pas  = load("passing.json")
cov  = load("coverage.json")
dfn  = load("defense.json")

# ---------- per-player advanced stats (skill players) ----------
players = {}   # norm-name -> stat dict
def put(name, pos, team, d):
    k = norm(name)
    if not k: return
    d = {kk: vv for kk, vv in d.items() if vv is not None}
    d.update({"pos": pos, "team": tfix(team)})
    players[k] = {**players.get(k, {}), **d}

for r in recv:
    if (r.get("routes") or 0) < 20: continue
    put(r["player"], r.get("position", "WR"), r.get("team", ""), {
        "yprr": r.get("yprr"), "adot": r.get("avg_depth_of_target"),
        "ccr": r.get("contested_catch_rate"), "slot_rate": r.get("slot_rate"),
        "drop_rate": r.get("drop_rate"), "yac_r": r.get("yards_after_catch_per_reception"),
        "route_grade": r.get("grades_pass_route"), "tprr": (r.get("targets") or 0) / max(1, r.get("routes") or 1),
        "recv_grade": r.get("grades_offense"), "tgt_rating": r.get("targeted_qb_rating"),
    })
for r in rush:
    if (r.get("attempts") or 0) < 10: continue
    put(r["player"], "RB", r.get("team", ""), {
        "elusive": r.get("elusive_rating"), "yco_att": r.get("yco_attempt"),
        "breakaway": r.get("breakaway_percent"), "run_grade": r.get("grades_run"),
        "avoided": r.get("avoided_tackles"), "ypa": r.get("ypa"),
    })
for r in pas:
    if (r.get("dropbacks") or 0) < 30: continue
    put(r["player"], "QB", r.get("team", ""), {
        "btt_rate": r.get("btt_rate"), "twp_rate": r.get("twp_rate"),
        "ttt": r.get("avg_time_to_throw"), "pass_grade": r.get("grades_pass"),
        "p2s": r.get("pressure_to_sack_rate"), "acc": r.get("accuracy_percent"),
        "qb_adot": r.get("avg_depth_of_target"),
    })

# ---------- team unit grades (snap-weighted, then regressed to league mean) ----------
def wmean(rows, gkey, skey):
    num = den = 0.0
    for r in rows:
        g = r.get(gkey); s = r.get(skey) or 0
        if g is not None and s:
            num += g * s; den += s
    return (num / den) if den else None

# defense: coverage / pass-rush / run-def, per team
def_cov = collections.defaultdict(lambda: [0.0, 0.0])
def_run = collections.defaultdict(lambda: [0.0, 0.0])
for r in cov:
    g = r.get("grades_coverage_defense"); s = r.get("snap_counts_coverage") or 0
    if g is not None and s: t = tfix(r["team"]); def_cov[t][0] += g * s; def_cov[t][1] += s
for r in dfn:
    g = r.get("grades_run_defense"); s = r.get("snap_counts_run_defense") or 0
    if g is not None and s: t = tfix(r["team"]); def_run[t][0] += g * s; def_run[t][1] += s
prsh = collections.defaultdict(float)      # team total pressures (pass-rush proxy)
prsh_snaps = collections.defaultdict(float)
for r in dfn:
    t = tfix(r["team"]); prsh[t] += (r.get("total_pressures") or 0); prsh_snaps[t] += (r.get("snap_counts_pass_rush") or 0)

# offense: pass grade (team QBs) + receiving corps yprr; run grade (team RBs)
off_pass = collections.defaultdict(lambda: [0.0, 0.0])
off_run  = collections.defaultdict(lambda: [0.0, 0.0])
off_yprr = collections.defaultdict(lambda: [0.0, 0.0])
for r in pas:
    g = r.get("grades_pass"); s = r.get("dropbacks") or 0
    if g is not None and s: t = tfix(r["team"]); off_pass[t][0] += g * s; off_pass[t][1] += s
for r in rush:
    g = r.get("grades_run"); s = r.get("attempts") or 0
    if g is not None and s: t = tfix(r["team"]); off_run[t][0] += g * s; off_run[t][1] += s
for r in recv:
    y = r.get("yprr"); s = r.get("routes") or 0
    if y is not None and s: t = tfix(r["team"]); off_yprr[t][0] += y * s; off_yprr[t][1] += s

def collapse(d): return {t: v[0] / v[1] for t, v in d.items() if v[1]}
DC, DR = collapse(def_cov), collapse(def_run)
OP, OR_, OY = collapse(off_pass), collapse(off_run), collapse(off_yprr)
PR = {t: (prsh[t] / prsh_snaps[t]) for t in prsh if prsh_snaps[t]}   # pressures per pass-rush snap

def league_mean(d): return sum(d.values()) / len(d) if d else 50.0
def regress(d, K=4):
    """Light shrinkage toward league mean (3-game sample, but PFF grades stabilize fast — keep the signal)."""
    m = league_mean(d); out = {}
    n = 3  # games played this season (wk3)
    for t, v in d.items():
        out[t] = (n * v + K * m) / (n + K)
    return out, m

DCr, DCm = regress(DC); DRr, DRm = regress(DR)
OPr, OPm = regress(OP); ORr, ORm = regress(OR_)
PRr, PRm = regress(PR, K=3)
OYm = league_mean(OY)

teams = {}
allt = set(DCr) | set(DRr) | set(OPr) | set(ORr)
for t in allt:
    teams[t] = {
        "def_pass": round(DCr.get(t, DCm), 1),   # coverage grade (higher = tougher vs pass)
        "def_run":  round(DRr.get(t, DRm), 1),    # run-def grade  (higher = tougher vs run)
        "prsh":     round(PRr.get(t, PRm), 3),    # pressure rate  (higher = tougher on QB)
        "off_pass": round(OPr.get(t, OPm), 1),
        "off_run":  round(ORr.get(t, ORm), 1),
        "off_yprr": round(OY.get(t, OYm), 2),
    }

# opponent softness ranks (1 = softest / most favorable to attack)
def soft_rank(key):
    order = sorted(teams, key=lambda t: teams[t].get(key, 60))   # ascending grade => softest first
    return {t: i + 1 for i, t in enumerate(order)}
SOFT_PASS = soft_rank("def_pass")
SOFT_RUN  = soft_rank("def_run")
def ordn(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))

# merge nflverse scheme (screen/PA/PROE/pace + def box/blitz) for the explorer cards
def read_csv(path):
    import csv
    with open(path) as f: return list(csv.DictReader(f))
try:
    for row in read_csv(os.path.join(ENG, "scheme_2026_off.csv")):
        t = tfix(row["team"]); teams.setdefault(t, {})
        teams[t].update({"proe": float(row["proe"]), "screen_rate": float(row["screen_rate"]),
                          "pa_rate": float(row["pa_rate"]), "pace": float(row["plays_pg"])})
    for row in read_csv(os.path.join(ENG, "scheme_2026_def.csv")):
        t = tfix(row["team"]); teams.setdefault(t, {})
        teams[t].update({"blitz": float(row["blitz_rate"]), "light_box": float(row["light_box_rate"])})
except Exception as e:
    print("scheme merge skipped:", e)

# ---------- weekly Favorite Matchups ----------
week = json.load(open(os.path.join(DATA, "week.json")))
meta = json.load(open(os.path.join(DATA, "meta.json")))
WK = meta.get("week")

def opp_of(s):
    if not s: return None
    m = re.search(r"([A-Z]{2,3})$", s.strip())
    return m.group(1) if m else None

# league bounds for normalization
def bounds(vals):
    vals = [v for v in vals if v is not None]
    if not vals: return (0, 1)
    vals.sort(); n = len(vals)
    return (vals[max(0, int(n * 0.05))], vals[min(n - 1, int(n * 0.95))])

projs = {p: [] for p in ("QB", "RB", "WR", "TE")}
for r in week:
    if r["pos"] in projs: projs[r["pos"]].append(r.get("proj") or 0)
pb = {p: bounds(v) for p, v in projs.items()}

MINPROJ = {"QB": 15.0, "RB": 8.0, "WR": 7.0, "TE": 5.0}   # startable floor — keep backups/noise out
cand = []
for r in week:
    pos = r["pos"]
    if pos not in ("QB", "RB", "WR", "TE"): continue
    if r.get("inj") == "O": continue
    if (r.get("proj") or 0) < MINPROJ[pos]: continue
    opp = opp_of(r.get("opp"))
    if not opp or opp not in teams: continue
    dt = teams[opp]; ot = teams.get(r["team"], {})
    pf = players.get(norm(r["name"]), {})

    # opponent weakness for this role (positive = favorable), league-mean centered
    if pos in ("WR", "TE"):
        weak = (DCm - dt.get("def_pass", DCm)) / 10.0                 # soft coverage = good
        talent = pct(pf.get("yprr", OYm), 1.2, 2.8) - 0.5            # yprr talent
        talent += (pct(pf.get("route_grade", 60), 55, 85) - 0.5) * 0.5
        own = (ot.get("off_pass", OPm) - OPm) / 12.0
    elif pos == "RB":
        weak = 0.65 * (DRm - dt.get("def_run", DRm)) / 10.0 + 0.35 * (DCm - dt.get("def_pass", DCm)) / 10.0
        talent = pct(pf.get("elusive", 55), 40, 95) - 0.5
        own = (ot.get("off_run", ORm) - ORm) / 12.0 + (ot.get("screen_rate", 8) - 8) / 20.0
    else:  # QB
        weak = 0.6 * (DCm - dt.get("def_pass", DCm)) / 10.0 + 0.4 * (PRm - dt.get("prsh", PRm)) / 0.08
        talent = pct(pf.get("pass_grade", 65), 55, 90) - 0.5
        own = (ot.get("off_pass", OPm) - OPm) / 12.0

    lo, hi = pb[pos]
    vol = pct(r.get("proj") or 0, lo, hi) - 0.5                       # projected volume/role
    delta_nudge = (r.get("delta") or 0) / 20.0                        # stay coherent w/ nflverse matchup

    score = 50 + 22 * weak + 14 * talent + 16 * vol + 9 * own + 6 * delta_nudge
    score = max(1.0, min(99.0, score))
    cand.append({
        "name": r["name"], "pos": pos, "team": r["team"], "opp": r.get("opp"),
        "proj": r.get("proj"), "own": r.get("own"), "score": round(score),
        "weak": round(weak, 2), "soft_pass": SOFT_PASS.get(opp), "soft_run": SOFT_RUN.get(opp),
        "pff": {k: pf.get(k) for k in
                 ("yprr", "adot", "elusive", "yco_att", "route_grade", "pass_grade", "btt_rate") if pf.get(k) is not None},
        "def_pass": dt.get("def_pass"), "def_run": dt.get("def_run"),
    })

cand.sort(key=lambda x: -x["score"])
# select 15: guarantee a position mix, cap 2 per team
POSMAX = {"QB": 2, "RB": 6, "WR": 7, "TE": 4}
POSMIN = {"RB": 4, "WR": 5, "TE": 2}
seen_team = collections.Counter(); pos_ct = collections.Counter(); fav = []; taken = set()
def try_add(c, respect_max=True):
    if id(c) in taken: return False
    if seen_team[c["team"]] >= 2: return False
    if respect_max and pos_ct[c["pos"]] >= POSMAX[c["pos"]]: return False
    fav.append(c); taken.add(id(c)); seen_team[c["team"]] += 1; pos_ct[c["pos"]] += 1
    return True
for pos, need in POSMIN.items():                       # 1) reserve the minimum mix
    for c in cand:
        if pos_ct[pos] >= need: break
        if c["pos"] == pos: try_add(c)
for c in cand:                                          # 2) fill the rest by score
    if len(fav) >= 15: break
    try_add(c)
fav.sort(key=lambda x: -x["score"]); fav = fav[:15]

# star grade from score within the chosen set
if fav:
    smax = fav[0]["score"]; smin = fav[-1]["score"]
    for c in fav:
        c["stars"] = min(5, 5 if c["score"] == smax else max(3, round(3 + 2 * pct(c["score"], smin, smax))))

def why(c):
    last = c["name"].split()[-1]; opp = opp_of(c["opp"]) or c["opp"]; pff = c["pff"]
    if c["pos"] in ("WR", "TE"):
        s = f"{opp}: {ordn(c['soft_pass'])}-softest pass D (PFF {c['def_pass']})."
        if pff.get("yprr"): s += f" {last} runs {pff['yprr']} yds/route."
        return s
    if c["pos"] == "RB":
        s = f"{opp}: {ordn(c['soft_run'])}-softest run D (PFF {c['def_run']})."
        if pff.get("elusive"): s += f" {pff['elusive']} elusive rating."
        return s
    s = f"{opp} rushes soft, sits {ordn(c['soft_pass'])}-softest in coverage."
    if pff.get("pass_grade"): s += f" {last} at {pff['pass_grade']} PFF passing."
    return s
for c in fav: c["why"] = why(c)

# ---------- streaming defenses (team D vs a weak opponent offense) ----------
# who does each team play? infer from any player on that team's opp
team_opp = {}
for r in week:
    o = opp_of(r.get("opp"))
    if o: team_opp[r["team"]] = r.get("opp")
streams = []
for t, prof in teams.items():
    opp = opp_of(team_opp.get(t, "")) if team_opp.get(t) else None
    if not opp or opp not in teams: continue
    o = teams[opp]
    # good stream = strong pass rush + opponent weak passing offense
    s = 50 + 22 * ((prof.get("prsh", PRm) - PRm) / 0.08) + 22 * ((OPm - o.get("off_pass", OPm)) / 12.0)
    s = max(1, min(99, s))
    streams.append({"team": t, "opp": team_opp.get(t), "score": round(s),
                    "why": f"{opp} offense grades {o.get('off_pass')} passing; {t} pressures at {prof.get('prsh')}/snap."})
streams.sort(key=lambda x: -x["score"]); streams = streams[:6]
for i, c in enumerate(streams): c["stars"] = 5 if i == 0 else max(3, 5 - i // 2)

# ---------- model-facing prior (committed for the CI pipeline, which can't pull PFF live) ----------
# keyed by weekly_update.py's norm(): lowercase, strip suffixes, letters only (no spaces)
def wnorm(s):
    return re.sub(r"[^a-z]", "", re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", (s or "").lower()))
prior = {
    "means": {"cov": round(DCm, 2), "run": round(DRm, 2), "prsh": round(PRm, 4)},
    "teams": {t: {"def_pass": teams[t].get("def_pass"), "def_run": teams[t].get("def_run"),
                  "prsh": teams[t].get("prsh")} for t in teams if teams[t].get("def_pass") is not None},
    "players": {},
}
for k, v in players.items():                       # k is pff-norm (with spaces) -> re-key to wnorm
    name = None
    # recover a display name is unnecessary; wnorm the pff key by stripping spaces/nonletters
    wk_ = re.sub(r"[^a-z]", "", k)
    row = {kk: v[kk] for kk in ("yprr", "elusive", "pass_grade", "route_grade") if v.get(kk) is not None}
    if row and wk_: prior["players"][wk_] = row
with open(os.path.join(HERE, "pff_prior.json"), "w") as f:
    json.dump(prior, f, separators=(",", ":"))
print(f"wrote pipeline/pff_prior.json — {len(prior['teams'])} teams · {len(prior['players'])} players")

# ---------- write ----------
out = {
    "week": WK,
    "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    "note": "PFF advanced stats through the games played this season; team grades regressed to league mean (small sample).",
    "teams": teams,
    "players": {k: v for k, v in players.items()},
    "matchups": fav,
    "streams": streams,
}
with open(os.path.join(DATA, "pff.json"), "w") as f:
    json.dump(out, f, separators=(",", ":"))
print(f"wrote data/pff.json — week {WK} · {len(teams)} teams · {len(players)} players · {len(fav)} favorite matchups · {len(streams)} streams")
print("\nTOP FAVORITE MATCHUPS:")
for c in fav[:15]:
    print(f"  {c['stars']}★ {c['name']:22s} {c['pos']:2s} {c['opp']:8s} score {c['score']:>2}  own {c['own']}%  — {c['why']}")
print("\nSTREAMING DEFENSES:")
for c in streams:
    print(f"  {c['stars']}★ {c['team']:4s} {c['opp']:8s} score {c['score']}  — {c['why']}")
