"""Score a real recorded take: cut one wav into visits at given times, run each through Muse Voice + Spark, and compare
with the expected charts in a dictations file. Usage: python3 real_take.py <wav> <dictations.json> <start-end> ..."""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import meta

wav, lines, cuts = sys.argv[1], json.load(open(sys.argv[2])), sys.argv[3:]
total = right = 0; rows = []
for d, cut in zip(lines, cuts):
    a, b = cut.split("-")
    with tempfile.TemporaryDirectory() as t:
        seg = os.path.join(t, "seg.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", wav, "-ss", a] + (["-to", b] if b else []) + ["-c", "copy", seg], check=True)
        heard = meta.transcribe(seg)
    chart = meta.chart_from_text(heard); e = d["expect"]; misses = []
    for s in meta.SERVICES:
        total += 1; ok = chart["services"][s] == (s in e["services"]); right += ok
        if not ok: misses.append(s)
    for s in ("sealant", "class_v", "extraction"):
        total += 1; ok = sorted(chart["teeth"][s]) == sorted(e["teeth"].get(s, [])); right += ok
        if not ok: misses.append(f"teeth.{s}={chart['teeth'][s]}")
    total += 1; ok = chart["emergency_pain"] == e["emergency_pain"]; right += ok
    if not ok: misses.append("emergency_pain")
    rows.append({"id": d["id"], "cut": cut, "heard": heard, "chart": chart, "misses": misses})
    print(f"{d['id']} [{cut}] heard: {heard}\n    misses: {misses or 'none'}")
out = os.path.join(os.path.dirname(__file__), "out", "real_take_" + os.path.splitext(os.path.basename(wav))[0] + ".json")
json.dump(rows, open(out, "w"), indent=1)
pct = 100 * right / total
print(f"fields right: {right}/{total} = {pct:.0f} percent, pass mark 90: {'PASS' if pct >= 90 else 'FAIL'}")
