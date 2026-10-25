#!/usr/bin/env python3
"""
ONE COMMAND = rebuild BOTH editions and deploy — and NEVER ship PFF to the public site.

  PUBLIC  (open-data, PFF-free)  -> data/      -> deployed to GitHub Pages (chargeable/public)
  PRIVATE (PFF)                  -> private/    -> encrypted to assets/private.enc (password-gated; phone)

Public pipelines use nflverse ONLY (NOPFF / *_nopff). Private pipelines pull PFF via restish (local auth).
Order: build PRIVATE first (snapshot -> private/, encrypt), THEN build PUBLIC so data/ ENDS open-data.
A COMPLIANCE GUARD re-reads data/ before deploy and ABORTS if any PFF is detected. Only data/*.json
(open-data) + assets/private.enc (ciphertext) are ever pushed; private/*.json never deploys.

  python pipeline/refresh_all.py --deploy                  # both editions (needs restish; PPW for enc)
  PPW='your-pass' python pipeline/refresh_all.py --deploy  # also refresh the encrypted phone bundle
  python pipeline/refresh_all.py --public-only --deploy    # fast: open-data public only (no PFF/restish)
"""
import subprocess, sys, os, base64, json, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
APP  = os.path.dirname(HERE)
DATA = os.path.join(APP, "data")
PRIV = os.path.join(APP, "private")
SHARED = ["draft","week","lineup","meta","crosswalk","adp","fpros","pff","trenches"]
PUBLIC_ONLY = "--public-only" in sys.argv
DEPLOY = "--deploy" in sys.argv

def run(label, script, env_extra=None):
    print(f"\n=== {label} ===", flush=True)
    env = dict(os.environ); env.update(env_extra or {})
    r = subprocess.run([sys.executable, os.path.join("pipeline", script)], cwd=APP, env=env)
    ok = r.returncode == 0
    print(("[ok] " if ok else "[FAIL] ") + label)
    return ok

def deploy(path, msg):
    sha = subprocess.run(["gh","api",f"repos/chukse/ttt-fantasy/contents/{path}","--jq",".sha"],
                         capture_output=True, text=True).stdout.strip()
    body = {"message": msg, "content": base64.b64encode(open(os.path.join(APP,path),"rb").read()).decode()}
    if sha: body["sha"] = sha
    open("/tmp/_rf.json","w").write(json.dumps(body))
    subprocess.run(["gh","api","--method","PUT",f"repos/chukse/ttt-fantasy/contents/{path}",
                    "--input","/tmp/_rf.json","--jq",".commit.html_url"], capture_output=True, text=True)
    print(f"  deployed {path}")

# ---------------- PRIVATE (PFF) edition -> private/ + encrypt ----------------
enc = False
if not PUBLIC_ONLY:
    print("\n######## PRIVATE (PFF) build -> private/ ########")
    p1 = run("private 1/3 projections (PFF prior)", "weekly_update.py")   # default = PFF
    run("private 2/3 trenches (PFF facets)",        "trenches_weekly.py")
    run("private 3/3 favorite matchups (PFF)",      "pff_ingest.py")
    if p1:
        os.makedirs(PRIV, exist_ok=True)
        for f in SHARED:
            s = os.path.join(DATA, f+".json")
            if os.path.exists(s): shutil.copy(s, os.path.join(PRIV, f+".json"))
        print("  snapshot -> private/ (PFF)")
        if os.environ.get("PPW"):
            enc = run("private encrypt -> assets/private.enc", "encrypt_private.py")
        else:
            print("  [skip] no PPW env -> assets/private.enc NOT refreshed (set PPW to update the phone bundle)")
    else:
        print("  [FAIL] private projections failed -> private snapshot unchanged")

# ---------------- PUBLIC (open-data) edition -> data/ (this is what deploys) ----------------
print("\n######## PUBLIC (open-data, PFF-free) build -> data/ ########")
run("public 1/3 projections (NOPFF)",          "weekly_update.py", {"NOPFF":"1"})
run("public 2/3 trenches (nflverse only)",     "trenches_nopff.py")
run("public 3/3 favorite matchups (nflverse)", "pff_ingest.py",    {"MATCHUP_NOPFF":"1"})

# ---------------- COMPLIANCE GUARD: data/ MUST be PFF-free before any deploy ----------------
def _cites_pff(s):   # true only if PFF is actually referenced (ignores "no pff"/"open data" disclaimers)
    s = (s or "").lower()
    for benign in ("no pff", "open data", "pff-free", "without pff"): s = s.replace(benign, "")
    return "pff" in s
def public_is_clean():
    try:
        m  = json.load(open(os.path.join(DATA,"meta.json")))
        pf = json.load(open(os.path.join(DATA,"pff.json")))
        tr = json.load(open(os.path.join(DATA,"trenches.json")))
        if m.get("edition") != "public" or _cites_pff(m.get("note","")): return False, "meta.json not public/clean"
        if any(_cites_pff(x.get("why","")) for x in pf.get("matchups",[])):  return False, "pff.json why cites PFF"
        if _cites_pff(tr.get("note","")):                                    return False, "trenches.json note cites PFF"
        return True, "ok"
    except Exception as e:
        return False, f"read error: {e}"

clean, why = public_is_clean()
print(f"\nCOMPLIANCE GUARD — public data/ PFF-free: {'PASS' if clean else 'FAIL — '+why}")

if DEPLOY:
    if not clean:
        sys.exit("\nABORT: public data/ is not PFF-free (" + why + ") — refusing to deploy. Compliance guard.")
    print("\n=== deploying PUBLIC (open-data) ===")
    for f in ["week","meta","pff","trenches","adp","fpros"]:
        if os.path.exists(os.path.join(DATA,f+".json")):
            deploy(f"data/{f}.json", "data: daily refresh — open-data (PFF-free) [refresh_all]")
    if enc and os.path.exists(os.path.join(APP,"assets","private.enc")):
        deploy("assets/private.enc", "data: daily refresh — encrypted private (PFF) bundle [refresh_all]")
    print("\nDONE — public is PFF-free; private " +
          ("re-encrypted" if enc else ("snapshot updated (no PPW -> enc unchanged)" if not PUBLIC_ONLY else "untouched (--public-only)")))
else:
    print("\n(dry run — pass --deploy to push)")
