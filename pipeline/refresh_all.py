#!/usr/bin/env python3
"""
ONE COMMAND = refresh EVERY data facet of the app (run locally; PFF needs restish auth).
  1) data/week.json     projections / waiver / optimal lineup / injuries / next-man-up / 0-game-backup fix
  2) data/trenches.json OL + opponent-adjusted DEF rankings, this-week matchups, start/sit leans (fresh PFF pull)
  3) data/pff.json       favorite-matchups board (PFF scheme/coverage)
Note: week.json ALSO auto-refreshes on GitHub Actions (Wed+Sun). pff/trenches are PFF-gated -> local only.
After this finishes, commit the data/ files (or run with --deploy to push them to GitHub Pages).
"""
import subprocess, sys, os, base64, json

HERE = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.dirname(HERE)

def run(label, script, extra=None):
    print(f"\n=== {label} ===", flush=True)
    r = subprocess.run([sys.executable, os.path.join("pipeline", script)] + (extra or []), cwd=APP)
    print(("[ok] " if r.returncode == 0 else "[FAIL] ") + label)
    return r.returncode == 0

def deploy(path, msg):
    sha = subprocess.run(["gh","api",f"repos/chukse/ttt-fantasy/contents/{path}","--jq",".sha"],
                         capture_output=True, text=True).stdout.strip()
    body = {"message": msg, "content": base64.b64encode(open(os.path.join(APP,path),"rb").read()).decode()}
    if sha: body["sha"] = sha
    open("/tmp/_rf.json","w").write(json.dumps(body))
    r = subprocess.run(["gh","api","--method","PUT",f"repos/chukse/ttt-fantasy/contents/{path}",
                        "--input","/tmp/_rf.json","--jq",".commit.html_url"], capture_output=True, text=True)
    print(f"  deployed {path}")

ok  = run("1/3 projections (week.json)", "weekly_update.py")
ok &= run("2/3 trenches OL/DEF (fresh PFF facets)", "trenches_weekly.py")
ok &= run("3/3 favorite matchups (pff.json)", "pff_ingest.py")

print("\n" + ("ALL FACETS REFRESHED" if ok else "SOME FACETS FAILED — check above"))
if "--deploy" in sys.argv and ok:
    print("\n=== deploying data to GitHub Pages ===")
    deploy("data/week.json",     "data: weekly refresh — projections/injuries/lineup [refresh_all]")
    deploy("data/trenches.json", "data: weekly refresh — trenches [refresh_all]")
    deploy("data/pff.json",      "data: weekly refresh — favorite matchups [refresh_all]")
    print("done.")
