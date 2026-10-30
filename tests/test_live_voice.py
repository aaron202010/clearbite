"""Live voice next to replay (CLAIM_REPLAY=1 with CLAIM_LIVE_VOICE=1): a visitor's own recording goes to the live models, the saved
visits and the filing stay replayed, and live recordings are capped per visitor and per day. Meta is never called: stubs."""
import pytest
from fastapi.testclient import TestClient
from app import main, replay


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv("CLAIM_REPLAY", "1")
    monkeypatch.setenv("CLAIM_REPLAY_DELAY", "0")
    monkeypatch.setenv("CLAIM_LIVE_VOICE", "1")
    monkeypatch.setattr(main, "LIVE_HITS", {}); monkeypatch.setattr(main, "LIVE_DAY", main.deque())
    saved = replay.visits()
    calls = []
    monkeypatch.setattr(main.meta, "transcribe", lambda path: calls.append("asr") or saved["e4"]["heard"])
    monkeypatch.setattr(main.meta, "chart_from_text", lambda text: calls.append("chart") or saved["e4"]["chart"])
    c = TestClient(main.app); c.calls = calls
    return c


def record(c, ip="203.0.113.7"):
    return c.post("/visit", files={"audio": ("visit.webm", b"fake-audio-bytes", "audio/webm")}, headers={"X-Forwarded-For": ip})


def test_patient_says_live_voice_only_when_both_flags_are_on(demo, monkeypatch):
    assert demo.get("/patient").json()["live_voice"] is True
    monkeypatch.delenv("CLAIM_LIVE_VOICE")
    assert demo.get("/patient").json()["live_voice"] is False


def test_a_recording_goes_to_the_live_models_and_the_rules_check_runs(demo):
    r = record(demo)
    assert r.status_code == 200, r.text
    body = r.json()
    assert demo.calls == ["asr", "chart"]
    assert body["heard"] == replay.visits()["e4"]["heard"] and body["source"] == "audio"
    assert "check" in body or "rules" in body or "claim" in body


def test_saved_visits_stay_replayed_with_no_model_call(demo):
    r = demo.post("/visit", json={"visit_id": "e4"})
    assert r.status_code == 200 and r.json()["source"] == "saved"
    assert demo.calls == []


def test_without_the_live_flag_replay_still_refuses_recordings(demo, monkeypatch):
    monkeypatch.delenv("CLAIM_LIVE_VOICE")
    assert record(demo).status_code == 409 and demo.calls == []


def test_live_recordings_are_capped_per_visitor_per_hour(demo):
    for _ in range(main.LIVE_PER_HOUR):
        assert record(demo, "198.51.100.1").status_code == 200
    r = record(demo, "198.51.100.1")
    assert r.status_code == 429 and "Play a saved visit" in r.json()["detail"]
    assert record(demo, "198.51.100.2").status_code == 200   # another visitor still has their own allowance


def test_the_cap_reads_the_last_forwarded_hop_not_a_forged_first_one(demo):
    for i in range(main.LIVE_PER_HOUR):
        assert record(demo, f"10.0.0.{i}, 198.51.100.9").status_code == 200
    assert record(demo, "10.9.9.9, 198.51.100.9").status_code == 429


def test_the_daily_cap_covers_the_whole_demo(demo, monkeypatch):
    monkeypatch.setattr(main, "LIVE_PER_DAY", 3)
    for i in range(3):
        assert record(demo, f"198.51.100.{20 + i}").status_code == 200
    assert record(demo, "198.51.100.99").status_code == 429


def test_the_hourly_window_slides(demo):
    assert all(main.live_allowed("x", now=1000.0) for _ in range(main.LIVE_PER_HOUR))
    assert not main.live_allowed("x", now=1000.0)
    assert main.live_allowed("x", now=1000.0 + 3601)


def test_a_failed_live_call_is_a_502_with_no_key_in_it(demo, monkeypatch):
    def boom(path):
        raise RuntimeError("Bearer secret-key-value")
    monkeypatch.setattr(main.meta, "transcribe", boom)
    r = record(demo)
    assert r.status_code == 502 and "secret" not in r.text


def test_filing_stays_the_recorded_replay_in_live_voice_mode(demo, monkeypatch):
    used = []
    monkeypatch.setattr(main.filer, "file_claim", lambda *a, **k: used.append("live") or (_ for _ in ()).throw(AssertionError("live filing")))
    chart = demo.post("/visit", json={"visit_id": "e4"}).json()["chart"]
    with demo.stream("POST", "/file", json={"approved": True, "chart": chart}) as r:
        text = "".join(r.iter_text())
    assert used == [] and "event: done" in text


def test_a_tooth_set_from_the_screen_is_checked_like_a_spoken_one(demo):
    """Tapping a tooth sends the edited chart to /check (no model call); the sealant limit applies to it."""
    chart = demo.post("/visit", json={"visit_id": "e4"}).json()["chart"]
    chart["teeth"]["sealant"] = sorted(set(chart["teeth"]["sealant"]) | {47})
    r = demo.post("/check", json={"chart": chart})
    assert r.status_code == 200, r.text
    refused = r.json()["check"].get("refused_teeth", {}).get("sealant", [])
    assert 47 in refused and demo.calls == []
