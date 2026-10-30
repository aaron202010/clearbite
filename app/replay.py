"""Replay mode (env CLAIM_REPLAY=1): every Meta call is answered from the outputs saved in spikes/out/, so the demo
runs with no network. The five visits are the founder's own recorded take (real_take_take1.json)."""
import json, os, re

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "spikes", "out")
DEMO_DATE = "2026-10-29"   # the day the saved computer-use run filled the portal; the screenshots show this date


def on():
    return os.environ.get("CLAIM_REPLAY") == "1"


def live_voice():
    """CLAIM_LIVE_VOICE=1 next to replay: a visitor's own recording goes to the live Meta models (speech to text, then the chart);
    the saved visits and the filing stay replayed."""
    return os.environ.get("CLAIM_LIVE_VOICE") == "1"


def visits():
    return {v["id"]: v for v in json.load(open(os.path.join(OUT, "real_take_take1.json")))}


def _norm(text):
    return re.sub(r"\W+", " ", text.lower()).strip()


def by_text(text):
    """A saved visit whose heard text equals this text, or None."""
    return next((v for v in visits().values() if _norm(v["heard"]) == _norm(text)), None)
