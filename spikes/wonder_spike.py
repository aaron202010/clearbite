"""Day 1 computer-use spike: a Muse model fills one claim on the sample portal through the observe-act loop
(dev.meta.ai/docs/computer-use, read 2026-10-29). Since day 2 the loop lives in app/filer.py; this script runs it for the
one fixed claim below and writes the same files as before (wonder_step*.png, wonder_final.png, wonder_spike_<model>.json).
Safety checks are never auto-acknowledged unless --ack-local is given: the run stops and logs them.
Usage: python3 wonder_spike.py [model]   (default muse-spark-1.3; muse-wonder-1.0 rejects the computer tool on this key)"""
import json, os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import filer

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
MODEL = ARGS[0] if ARGS else filer.MODEL
ACK_LOCAL = "--ack-local" in sys.argv   # the developer reviewed the checks for the local sample portal; see filer.review()
CLAIM = {"patient": "Juan Dela Cruz (sample)", "pin": "12-345678901-2", "kpp": "Sample Konsulta Clinic", "date": "2026-10-29",
         "visit": "2", "code": "OPH02A", "services": ["oral_exam", "prophylaxis", "fluoride_varnish", "sealant"], "teeth": "16",
         "dentist": "0123456"}


def main():
    t0 = time.time()
    res = filer.file_claim(CLAIM, model=MODEL, ack_local=ACK_LOCAL, save_dir=OUT)
    bad = [r["field"] for r in res["readback"] if not r["ok"]]
    got = res["submitted"]
    if got: got["services"] = sorted(got.get("services") or [])
    json.dump({"model": MODEL, "steps": res["steps"], "seconds": round(time.time() - t0), "final": res["final"], "submitted": got,
               "wrong_fields": bad, "acknowledged": res["acknowledged"], "actions": res["actions"]},
              open(os.path.join(OUT, f"wonder_spike_{MODEL}.json"), "w"), indent=1)
    print(f"model {MODEL}: {res['steps']} turns, {round(time.time() - t0)} s, {len(res['actions'])} actions, {len(res['acknowledged'])} safety checks acknowledged")
    print("model said:", (res["final"] or "")[:300])
    print(f"fields read back right: {res['right']}/{res['total']}", "wrong:", bad or "none", "=>", "PASS" if not bad else "FAIL")


main()
