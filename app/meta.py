"""Meta Model API calls: speech to text (Muse Voice Transcribe) and dictation to chart (Muse Spark, structured output).
Docs read 2026-10-29: dev.meta.ai/docs/speech-to-text, /docs/structured-output."""
import json, os, subprocess, tempfile
import httpx

BASE = "https://api.meta.ai/v1"
ASR_MODEL, CHART_MODEL = "muse-voice-transcribe-1.0", "muse-spark-1.3"
KEYWORDS = ["oral exam", "prophylaxis", "prophy", "fluoride varnish", "sealant", "pit and fissure", "Class V",
            "root surface protection", "extraction", "PhilHealth", "Konsulta"]
SERVICES = ["oral_exam", "prophylaxis", "fluoride_varnish", "sealant", "class_v", "extraction"]


def key():
    if "MODEL_API_KEY" not in os.environ:
        for line in open("/root/.creds/meta-model-api.env"):
            if line.startswith("MODEL_API_KEY="):
                os.environ["MODEL_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
    return os.environ["MODEL_API_KEY"]


def to_wav(path):
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "a.wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", path, "-ac", "1", "-ar", "24000", "-c:a", "pcm_s16le", out], check=True)
        return open(out, "rb").read()


def transcribe(path):
    req = {"model": ASR_MODEL, "audioEncoding": "WAV", "languageBias": ["English", "Tagalog"], "keywords": KEYWORDS}
    r = httpx.post(BASE + "/asr/transcribe", headers={"Authorization": "Bearer " + key(), "Accept": "application/json"},
                   files={"request": (None, json.dumps(req), "application/json"), "audio": ("d.wav", to_wav(path), "audio/wav")}, timeout=120)
    r.raise_for_status()
    return (r.json().get("transcript") or "").strip()


teeth = {"type": "array", "items": {"type": "integer"}}
CHART_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["services", "teeth", "emergency_pain"],
                "properties": {
                    "services": {"type": "object", "additionalProperties": False, "required": SERVICES,
                                 "properties": {s: {"type": "boolean"} for s in SERVICES}},
                    "teeth": {"type": "object", "additionalProperties": False, "required": ["sealant", "class_v", "extraction"],
                              "properties": {"sealant": teeth, "class_v": teeth, "extraction": teeth}},
                    "emergency_pain": {"type": "boolean"}}}

CHART_PROMPT = """You turn a dentist's spoken notes (English, Tagalog or Taglish) into a dental chart for one visit.
Mark a service true only when the dentist says it was done in this visit. Said but not done ("hindi na nag-fluoride") is false.
cleaning, prophy, linis = prophylaxis. sealant, pit and fissure = sealant. Class V, root surface protection = class_v. bunot, extraction = extraction.
Tooth numbers are FDI, two digits: "sixteen" or "one six" = 16, "dalawampu't anim" = 26.
List each tooth under the service done on it. emergency_pain is true only when the dentist says the patient is in severe pain or it is an emergency."""


def chart_from_text(text):
    r = httpx.post(BASE + "/chat/completions", headers={"Authorization": "Bearer " + key()}, timeout=120, json={
        "model": CHART_MODEL, "temperature": 0,
        "messages": [{"role": "system", "content": CHART_PROMPT}, {"role": "user", "content": text}],
        "response_format": {"type": "json_schema", "json_schema": {"name": "chart", "strict": True, "schema": CHART_SCHEMA}}})
    r.raise_for_status()
    return json.loads(r.json()["choices"][0]["message"]["content"])
