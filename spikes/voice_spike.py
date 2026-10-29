"""Day 1 voice spike: 5 scripted Taglish dictations, synthetic fil-PH voice -> Muse Voice -> Muse Spark chart.
Scores 10 fields per dictation (6 services, 3 tooth lists, emergency pain). Pass at 90 percent. Saves every input and
output in spikes/out/ so the demo can replay them."""
import json, os, subprocess, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import meta

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
VOICE = sys.argv[1] if len(sys.argv) > 1 else "fil-PH-AngeloNeural"
LINES = sys.argv[2] if len(sys.argv) > 2 else "dictations.json"
total = right = 0; rows = []
for d in json.load(open(os.path.join(HERE, LINES))):
    mp3 = os.path.join(OUT, f"{d['id']}_{VOICE}.mp3")
    if not os.path.exists(mp3):
        subprocess.run(["uvx", "--from", "edge-tts==7.3.1", "edge-tts", "--voice", VOICE, "--rate=-5%", "--text", d["text"],
                        "--write-media", mp3], check=True, capture_output=True)
    heard = meta.transcribe(mp3)
    chart = meta.chart_from_text(heard)
    e = d["expect"]; misses = []
    for s in meta.SERVICES:
        total += 1
        if chart["services"][s] == (s in e["services"]): right += 1
        else: misses.append(s)
    for s in ("sealant", "class_v", "extraction"):
        total += 1
        if sorted(chart["teeth"][s]) == sorted(e["teeth"].get(s, [])): right += 1
        else: misses.append(f"teeth.{s}={chart['teeth'][s]}")
    total += 1
    if chart["emergency_pain"] == e["emergency_pain"]: right += 1
    else: misses.append("emergency_pain")
    rows.append({"id": d["id"], "voice": VOICE, "said": d["text"], "heard": heard, "chart": chart, "misses": misses})
    print(f"{d['id']}: heard: {heard}\n    misses: {misses or 'none'}")
json.dump(rows, open(os.path.join(OUT, f"voice_spike_{VOICE}.json"), "w"), indent=1, ensure_ascii=False)
pct = 100 * right / total
print(f"fields right: {right}/{total} = {pct:.0f} percent, pass mark 90: {'PASS' if pct >= 90 else 'FAIL'}")
