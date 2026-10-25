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

OPEN-DATA MODE (MATCHUP_NOPFF=1): rebuilds the identical output schema from nflverse only
(play_by_play + stats_player_week + games) — no PFF, no restish. Defense softness, player
usage, scores and `why` strings are all derived from open EPA + usage numbers.
"""
import json, os, re, math, collections, datetime

# Open-data mode: build the same board from nflverse only (no PFF, no restish).
NOPFF = bool(os.environ.get("MATCHUP_NOPFF"))

HERE = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.dirname(HERE)
PFF  = os.path.join(os.path.dirname(APP), "rookie_ladder", "pff_2026")   # ../rookie_ladder/pff_2026
DATA = os.path.join(APP, "data")
ENG  = os.path.join(APP, "engine")
NFLV = os.path.join(os.path.dirname(APP), "nflverse_daily", "data")      # ../nflverse_daily/data

# PFF team codes -> nflverse/app codes (Rams=LA & Chargers=LAC match already)
TEAMFIX = {"ARZ": "ARI", "BLT": "BAL", "CLV": "CLE", "HST": "HOU"}
def tfix(t): return TEAMFIX.get(t, t)

SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}
def norm(n):
    n = (n or "").lower().replace("’", "'")
    n = re.sub(r"[^a-z0-9' ]", "", n)
    toks = [t for t in n.split() if t not in SUFFIX and t != "'"]
    return " ".join(toks).replace("'", "").strip()

def pct(v, lo, hi):
    if hi <= lo: return 0.5
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))

def opp_of(s):
    if not s: return None
    m = re.search(r"([A-Z]{2,3})$", s.strip())
    return m.group(1) if m else None

def ordn(n):
    return "%d%s" % (n, "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


if not NOPFF:
    # ======================================================================
    # DEFAULT (PFF) PATH — unchanged
    # ======================================================================
    def load(name):
        p = os.path.join(PFF, name)
        with open(p) as f:
            d = json.load(f)
        if isinstance(d, dict):
            for k in d:
                if isinstance(d[k], list):
                    return d[k]
        return d

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

    NOTE = "PFF advanced stats through the games played this season; team grades regressed to league mean (small sample)."

else:
    # ======================================================================
    # OPEN-DATA PATH (MATCHUP_NOPFF=1) — nflverse only, no PFF / no restish
    # Same output schema; `pff` sub-object carries open usage stats instead.
    # ======================================================================
    import pandas as pd

    # ---------- upcoming week + "through wkN" from games.parquet ----------
    games = pd.read_parquet(os.path.join(NFLV, "games.parquet"))
    games = games[games["season"] == 2026]
    played = games[games["home_score"].notna()]
    unplayed = games[games["home_score"].isna()]
    THROUGH = int(played["week"].max()) if len(played) else 0
    WK = int(unplayed["week"].min()) if len(unplayed) else THROUGH + 1
    # align to the projections' canonical week (meta.json) so every facet agrees
    try:
        _mw = json.load(open(os.path.join(DATA, "meta.json"))).get("week")
        if _mw: WK = int(_mw); THROUGH = max(0, int(_mw) - 1)
    except Exception: pass

    # ---------- play-by-play: defense softness + offense weakness ----------
    PBP = pd.read_parquet(
        os.path.join(NFLV, "play_by_play_2026.parquet"),
        columns=["season_type", "week", "posteam", "defteam", "pass", "rush",
                 "qb_dropback", "epa", "success", "sack", "qb_hit"],
    )
    PBP = PBP[(PBP["season_type"] == "REG") & (PBP["week"] <= THROUGH)]
    passp = PBP[(PBP["pass"] == 1) & PBP["posteam"].notna() & PBP["epa"].notna()]
    rushp = PBP[(PBP["rush"] == 1) & PBP["posteam"].notna() & PBP["epa"].notna()]
    db = PBP[(PBP["qb_dropback"] == 1) & PBP["posteam"].notna()]

    # per-defense allowed
    def_pass_epa = passp.groupby("defteam")["epa"].mean()          # higher = softer vs pass
    def_run_epa  = rushp.groupby("defteam")["epa"].mean()          # higher = softer vs run
    def_pass_sr  = passp.groupby("defteam")["success"].mean()
    def_run_sr   = rushp.groupby("defteam")["success"].mean()
    # pressure proxy: (sack|qb_hit) per dropback faced by the offense == generated by defense
    db["prz"] = ((db["sack"] == 1) | (db["qb_hit"] == 1)).astype(float)
    def_prz = db.groupby("defteam")["prz"].mean()                 # higher = more pressure = tougher

    # per-offense
    off_pass_epa = passp.groupby("posteam")["epa"].mean()         # lower = weaker passing offense
    off_run_epa  = rushp.groupby("posteam")["epa"].mean()
    off_sack = db.groupby("posteam").apply(lambda g: (g["sack"] == 1).mean())  # sack rate taken

    ALLT = sorted(set(def_pass_epa.index) | set(off_pass_epa.index))

    def zscore(series):
        m, sd = series.mean(), series.std(ddof=0)
        if not sd: sd = 1.0
        return {t: (series.get(t, m) - m) / sd for t in ALLT}, float(m), float(sd)

    # weakness z (positive = softer/weaker = better to attack)
    PASS_W, dpm, _ = zscore(def_pass_epa)   # high EPA allowed -> high z -> soft
    RUN_W,  drm, _ = zscore(def_run_epa)
    OFFPASS_Z, opm, _ = zscore(off_pass_epa)  # low z -> weak passing offense

    # softness ranks: 1 = softest (highest EPA allowed)
    def rank_desc(series):
        order = sorted(ALLT, key=lambda t: -series.get(t, series.mean()))
        return {t: i + 1 for i, t in enumerate(order)}
    SOFT_PASS = rank_desc(def_pass_epa)
    SOFT_RUN  = rank_desc(def_run_epa)

    # ---------- player usage/quality from stats_player_week ----------
    SPW = pd.read_parquet(os.path.join(NFLV, "stats_player_week_2026.parquet"))
    SPW = SPW[(SPW["season_type"] == "REG") & (SPW["week"] <= THROUGH)]
    # games played per player (for per-game rates)
    gp = SPW.groupby("player_display_name")["week"].nunique()
    agg = SPW.groupby("player_display_name").agg(
        targets=("targets", "sum"),
        receptions=("receptions", "sum"),
        rec_yards=("receiving_yards", "sum"),
        rec_air=("receiving_air_yards", "sum"),
        tgt_share=("target_share", "mean"),
        rec_epa=("receiving_epa", "sum"),
        carries=("carries", "sum"),
        rush_yards=("rushing_yards", "sum"),
        rush_epa=("rushing_epa", "sum"),
        pass_att=("attempts", "sum"),
        pass_epa=("passing_epa", "sum"),
        cpoe=("passing_cpoe", "mean"),
    )
    USAGE = {}
    for name, row in agg.iterrows():
        g = int(gp.get(name, 0)) or 1
        USAGE[norm(name)] = {
            "g": g,
            "tgt_pg": (row["targets"] or 0) / g,
            "tgt_share": row["tgt_share"] if pd.notna(row["tgt_share"]) else None,
            "air_pg": (row["rec_air"] or 0) / g,
            "rec_ypg": (row["rec_yards"] or 0) / g,
            "rec_epa_play": (row["rec_epa"] / row["targets"]) if (row["targets"] or 0) else None,
            "car_pg": (row["carries"] or 0) / g,
            "rush_ypg": (row["rush_yards"] or 0) / g,
            "ypc": (row["rush_yards"] / row["carries"]) if (row["carries"] or 0) else None,
            "rush_epa_play": (row["rush_epa"] / row["carries"]) if (row["carries"] or 0) else None,
            "epa_play": (row["pass_epa"] / row["pass_att"]) if (row["pass_att"] or 0) else None,
            "cpoe": row["cpoe"] if pd.notna(row["cpoe"]) else None,
        }

    # ---------- teams map (open context) ----------
    def r3(x):
        return round(float(x), 3) if x is not None and pd.notna(x) else None
    teams = {}
    for t in ALLT:
        teams[t] = {
            "def_pass": r3(def_pass_epa.get(t)),   # EPA/play allowed vs pass (higher = softer)
            "def_run":  r3(def_run_epa.get(t)),    # EPA/play allowed vs run
            "prsh":     r3(def_prz.get(t)),        # pressure rate (sack|qb_hit)/dropback
            "off_pass": r3(off_pass_epa.get(t)),   # offense pass EPA/play
            "off_run":  r3(off_run_epa.get(t)),
        }

    # ---------- weekly board join (proj/own/opp from week.json) ----------
    week = json.load(open(os.path.join(DATA, "week.json")))

    MINPROJ = {"QB": 15.0, "RB": 8.0, "WR": 7.0, "TE": 5.0}

    # league bounds for projection normalization
    def bounds(vals):
        vals = sorted(v for v in vals if v is not None)
        if not vals: return (0, 1)
        n = len(vals)
        return (vals[max(0, int(n * 0.05))], vals[min(n - 1, int(n * 0.95))])
    projs = {p: [] for p in ("QB", "RB", "WR", "TE")}
    for r in week:
        if r["pos"] in projs: projs[r["pos"]].append(r.get("proj") or 0)
    pb = {p: bounds(v) for p, v in projs.items()}
    # usage bounds for quality normalization
    tgt_pg_vals = [u["tgt_pg"] for u in USAGE.values() if u["tgt_pg"]]
    air_pg_vals = [u["air_pg"] for u in USAGE.values() if u["air_pg"]]
    car_pg_vals = [u["car_pg"] for u in USAGE.values() if u["car_pg"]]
    TGT_B = bounds(tgt_pg_vals); AIR_B = bounds(air_pg_vals); CAR_B = bounds(car_pg_vals)

    cand = []
    for r in week:
        pos = r["pos"]
        if pos not in ("QB", "RB", "WR", "TE"): continue
        if r.get("inj") == "O": continue
        if (r.get("proj") or 0) < MINPROJ[pos]: continue
        opp = opp_of(r.get("opp"))
        if not opp or opp not in teams: continue
        u = USAGE.get(norm(r["name"]), {})

        lo, hi = pb[pos]
        vol = pct(r.get("proj") or 0, lo, hi) - 0.5
        delta_nudge = (r.get("delta") or 0) / 20.0
        own_blend = ((r.get("own") or 0) / 100.0 - 0.5) * 0.4   # heavier roles are startable

        if pos in ("WR", "TE"):
            weak = PASS_W[opp]                                   # soft pass D (z)
            # quality from open usage: target rate + air yards
            tq = pct(u.get("tgt_pg") or 0, *TGT_B) - 0.5
            aq = pct(u.get("air_pg") or 0, *AIR_B) - 0.5
            talent = 0.6 * tq + 0.4 * aq
            softpack = {"soft": SOFT_PASS[opp], "deps": round(teams[opp]["def_pass"], 2)}
        elif pos == "RB":
            weak = 0.7 * RUN_W[opp] + 0.3 * PASS_W[opp]          # mostly run, some pass (receiving back)
            cq = pct(u.get("car_pg") or 0, *CAR_B) - 0.5
            ypc = u.get("ypc")
            eq = pct(ypc if ypc is not None else 4.2, 3.2, 5.2) - 0.5
            talent = 0.6 * cq + 0.4 * eq
            softpack = {"soft": SOFT_RUN[opp], "deps": round(teams[opp]["def_run"], 2)}
        else:  # QB
            weak = 0.7 * PASS_W[opp] + 0.3 * (def_prz.mean() - def_prz.get(opp, def_prz.mean())) / (def_prz.std(ddof=0) or 1)
            epa = u.get("epa_play")
            cp = u.get("cpoe")
            eq = pct(epa if epa is not None else 0.0, -0.1, 0.35) - 0.5
            cq = pct(cp if cp is not None else 0.0, -4.0, 6.0) - 0.5
            talent = 0.6 * eq + 0.4 * cq
            softpack = {"soft": SOFT_PASS[opp], "deps": round(teams[opp]["def_pass"], 2)}

        score = 50 + 16 * weak + 14 * talent + 16 * vol + 6 * delta_nudge + 6 * own_blend
        score = max(1.0, min(99.0, score))

        # open-data pff sub-object (2-3 clean numbers per position)
        if pos in ("WR", "TE"):
            opff = {}
            if u.get("tgt_share") is not None: opff["tgt_share"] = round(u["tgt_share"], 3)
            if u.get("air_pg"): opff["air_yards_pg"] = round(u["air_pg"], 1)
            if u.get("rec_ypg"): opff["ypg"] = round(u["rec_ypg"], 1)
        elif pos == "RB":
            opff = {}
            if u.get("car_pg"): opff["carries_pg"] = round(u["car_pg"], 1)
            if u.get("ypc") is not None: opff["ypc"] = round(u["ypc"], 2)
            if u.get("rush_epa_play") is not None: opff["rush_epa"] = round(u["rush_epa_play"], 3)
        else:
            opff = {}
            if u.get("epa_play") is not None: opff["epa_play"] = round(u["epa_play"], 3)
            if u.get("cpoe") is not None: opff["cpoe"] = round(u["cpoe"], 1)

        cand.append({
            "name": r["name"], "pos": pos, "team": r["team"], "opp": r.get("opp"),
            "proj": r.get("proj"), "own": r.get("own"), "score": round(score),
            "weak": round(float(weak), 2), "soft_pass": SOFT_PASS.get(opp), "soft_run": SOFT_RUN.get(opp),
            "pff": opff,
            "def_pass": r3(def_pass_epa.get(opp)), "def_run": r3(def_run_epa.get(opp)),
            "_u": u, "_softpack": softpack,
        })

    cand.sort(key=lambda x: -x["score"])
    # select 15 with the same position-mix guarantees and 2-per-team cap
    POSMAX = {"QB": 2, "RB": 6, "WR": 7, "TE": 4}
    POSMIN = {"RB": 4, "WR": 5, "TE": 2}
    seen_team = collections.Counter(); pos_ct = collections.Counter(); fav = []; taken = set()
    def try_add(c, respect_max=True):
        if id(c) in taken: return False
        if seen_team[c["team"]] >= 2: return False
        if respect_max and pos_ct[c["pos"]] >= POSMAX[c["pos"]]: return False
        fav.append(c); taken.add(id(c)); seen_team[c["team"]] += 1; pos_ct[c["pos"]] += 1
        return True
    for pos, need in POSMIN.items():
        for c in cand:
            if pos_ct[pos] >= need: break
            if c["pos"] == pos: try_add(c)
    for c in cand:
        if len(fav) >= 15: break
        try_add(c)
    fav.sort(key=lambda x: -x["score"]); fav = fav[:15]

    if fav:
        smax = fav[0]["score"]; smin = fav[-1]["score"]
        for c in fav:
            c["stars"] = min(5, 5 if c["score"] == smax else max(3, round(3 + 2 * pct(c["score"], smin, smax))))

    def sgn(x):
        return ("+%.2f" % x) if x >= 0 else ("%.2f" % x)

    def why(c):
        last = c["name"].split()[-1]
        opp = opp_of(c["opp"]) or c["opp"]
        u = c["_u"]; sp = c["_softpack"]
        if c["pos"] in ("WR", "TE"):
            s = f"{opp}: {ordn(sp['soft'])}-softest pass D ({sgn(sp['deps'])} EPA/play allowed)."
            bits = []
            if u.get("tgt_share") is not None: bits.append(f"{round(u['tgt_share']*100)}% target share")
            if u.get("air_pg"): bits.append(f"{round(u['air_pg'])} air yds/gm")
            if bits: s += f" {last} on " + ", ".join(bits) + "."
            return s
        if c["pos"] == "RB":
            s = f"{opp}: {ordn(sp['soft'])}-softest run D ({sgn(sp['deps'])} EPA/play allowed)."
            bits = []
            if u.get("car_pg"): bits.append(f"{round(u['car_pg'])} carries/gm")
            if u.get("ypc") is not None: bits.append(f"{round(u['ypc'],1)} YPC")
            if bits: s += f" {last}: " + ", ".join(bits) + "."
            return s
        s = f"{opp}: {ordn(sp['soft'])}-softest pass D ({sgn(sp['deps'])} EPA/play allowed)."
        if u.get("epa_play") is not None: s += f" {last} at {sgn(u['epa_play'])} EPA/play."
        return s
    for c in fav:
        c["why"] = why(c)
        c.pop("_u", None); c.pop("_softpack", None)

    # ---------- streaming defenses: strong pass D vs weak passing offense ----------
    team_opp = {}
    for r in week:
        o = opp_of(r.get("opp"))
        if o: team_opp[r["team"]] = r.get("opp")
    prz_mean = float(def_prz.mean()); prz_sd = float(def_prz.std(ddof=0) or 1)
    dpe_mean = float(def_pass_epa.mean()); dpe_sd = float(def_pass_epa.std(ddof=0) or 1)
    streams = []
    for t in teams:
        oppraw = team_opp.get(t)
        opp = opp_of(oppraw) if oppraw else None
        if not opp or opp not in teams: continue
        # defense strength: low pass EPA allowed (good) + high pressure (good)
        d_epa_z = (dpe_mean - def_pass_epa.get(t, dpe_mean)) / dpe_sd   # positive = stingy pass D
        d_prz_z = (def_prz.get(t, prz_mean) - prz_mean) / prz_sd        # positive = more pressure
        # opponent passing-offense weakness: negative off_pass z = weak
        opp_weak = -OFFPASS_Z[opp]
        s = 50 + 16 * d_epa_z + 10 * d_prz_z + 16 * opp_weak
        s = max(1, min(99, s))
        oe = teams[opp]["off_pass"]
        streams.append({
            "team": t, "opp": oppraw, "score": round(s),
            "why": f"{opp} offense: {sgn(oe)} pass EPA/play; {t} allows {sgn(teams[t]['def_pass'])} "
                   f"and pressures at {round(def_prz.get(t, prz_mean)*100)}% of dropbacks.",
        })
    streams.sort(key=lambda x: -x["score"]); streams = streams[:6]
    for i, c in enumerate(streams): c["stars"] = 5 if i == 0 else max(3, 5 - i // 2)

    # players name-index (keep the key; open mode uses the usage map)
    players = {k: {"pos": None} for k in USAGE}

    NOTE = f"Open-data matchups — nflverse EPA + usage (open data only). Through wk{THROUGH}."


# ======================================================================
# WRITE (shared) — identical schema in both modes
# ======================================================================
out = {
    "week": WK,
    "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    "note": NOTE,
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
