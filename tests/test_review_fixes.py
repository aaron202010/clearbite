"""Cases from the pre-ship review of 2026-10-29 (codex on app/rules.py, Kimi K3 on app/filer.py)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import filer, rules

PH = rules.load("philhealth_oph")
TRIO = ["oral_exam", "prophylaxis", "fluoride_varnish"]


def check(chart):
    base = {"service_date": "2026-03-01", "birth_date": "1990-01-01", "kpp_registered": True, "teeth": {}, "emergency_pain": False}
    return rules.check(dict(base, **chart), [], PH, "2026-03-01")


def state(r, s):
    return next(p["state"] for p in r["procedures"] if p["service"] == s)


def test_extraction_asked_only_through_teeth_still_needs_pain():
    r = check({"services": TRIO, "teeth": {"extraction": [11]}})
    assert state(r, "extraction") == "refused" and any("severe tooth pain" in p for p in r["problems"])


def test_refused_extraction_without_teeth_is_shown_refused():
    r = check({"services": TRIO + ["extraction"]})
    assert state(r, "extraction") == "refused"


def test_non_numeric_tooth_does_not_crash():
    r = check({"services": TRIO + ["sealant"], "teeth": {"sealant": ["A"]}})
    assert any("not a real tooth" in p for p in r["problems"])
    assert not rules.valid_tooth(None) and not rules.valid_tooth(True) and rules.valid_tooth("16")


def test_vet_allows_plain_input_on_the_portal():
    acts = [{"type": "click", "x": 10, "y": 20}, {"type": "type", "text": "Juan"}, {"type": "keypress", "keys": ["Tab"]},
            {"type": "keypress", "keys": ["shift", "tab"]}, {"type": "wait"}]
    assert filer.vet(filer.PORTAL_URL, acts) is None


def test_vet_stops_everything_else():
    P = filer.PORTAL_URL
    assert filer.vet("https://example.com/", [{"type": "wait"}])                         # off the portal
    assert filer.vet(P, [{"type": "drag", "path": [{"x": 1, "y": 1}]}])                  # not an allowed action
    assert filer.vet(P, [{"type": "keypress", "keys": ["ctrl", "l"]}])                    # address bar
    assert filer.vet(P, [{"type": "keypress", "keys": []}])                               # malformed
    assert filer.vet(P, [{"type": "click"}])                                              # no point
    assert filer.vet(P, [{"type": "click", "x": 99999, "y": 5}])                          # outside the screen
    assert filer.vet(P, [{"type": "type", "text": "x" * 500}])                           # too long
    assert filer.vet(P, [{"type": "wait"}] * (filer.MAX_ACTIONS + 1))                     # too many
