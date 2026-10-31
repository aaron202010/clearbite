"""Fixes from the pre-submit check of 2026-10-31: the yearly cap names left-off teeth in the plural, out-of-range dates are refused
instead of crashing, replayed filings never wait on each other, HEAD on the screen answers, and the replay tag says what is live.
Meta is never called."""
import threading
import pytest
from fastapi.testclient import TestClient
from app import filer, main, replay


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CLAIM_REPLAY", "1")
    monkeypatch.setenv("CLAIM_REPLAY_DELAY", "0")
    monkeypatch.delenv("CLAIM_LIVE_VOICE", raising=False)
    return TestClient(main.app)


def cap_line(d):
    return next(l for l in d["check"]["lines"] if l["id"].startswith("cap:"))


def test_the_yearly_cap_names_two_left_off_teeth_in_the_plural(client):
    d = client.post("/visit", json={"visit_id": "e4"}).json()   # sealant on 16, 26, 36 with one tooth left this year
    assert cap_line(d)["detail"] == "1 already used this year, 1 left. Not covered: teeth 26, 36."
    assert any(p.endswith("Not covered: teeth 26, 36.") for p in d["check"]["problems"])
    one = client.post("/visit", json={"visit_id": "e2"}).json()   # sealant 16 and Class V 31: only 31 is left off
    assert cap_line(one)["detail"] == "1 already used this year, 1 left. Not covered: tooth 31."


def test_the_yearly_cap_lists_left_off_teeth_in_order(client):
    chart = client.post("/visit", json={"visit_id": "e4"}).json()["chart"]
    chart["teeth"] = {"sealant": [16, 36], "class_v": [11], "extraction": []}
    chart["services"]["class_v"] = True
    d = client.post("/check", json={"chart": chart}).json()
    assert cap_line(d)["detail"] == "1 already used this year, 1 left. Not covered: teeth 11, 36."
    assert d["check"]["covered_teeth"] == {"sealant": [16]}   # which tooth is kept does not change


@pytest.mark.parametrize("path", ["/visit", "/check", "/file"])
def test_a_date_out_of_range_is_refused_not_a_crash(client, path):
    chart = client.post("/visit", json={"visit_id": "e4"}).json()["chart"]
    body = {"visit_id": "e4", "chart": chart, "approved": True, "payer": "wa_apple_health"}
    for day in ("0001-01-01", "1899-12-31", "2101-01-01"):
        r = client.post(path, json={**body, "service_date": day})
        assert r.status_code == 400 and "between 1900 and 2100" in r.json()["detail"], (path, day, r.status_code)
    assert client.post(path, json={**body, "service_date": "2026-10-29", "filing_date": "9999-01-01"}).status_code == 400


def test_a_filing_date_before_the_service_date_is_refused(client):
    r = client.post("/visit", json={"visit_id": "e4", "service_date": "2026-10-29", "filing_date": "2020-01-01"})
    assert r.status_code == 400 and r.json()["detail"] == "The filing date cannot be before the service date."
    assert client.post("/visit", json={"visit_id": "e4", "service_date": "2026-10-29", "filing_date": "2026-10-29"}).status_code == 200


def test_a_replayed_filing_never_waits_on_another_one(client):
    """A replay plays saved screenshots and drives no browser, so a second visitor is never told a filing is already running."""
    d = client.post("/visit", json={"visit_id": "e4"}).json()
    assert main.FILING.acquire(blocking=False)   # as if another filing were running
    try:
        r = client.post("/file", json={"approved": True, "chart": d["chart"]})
        assert r.status_code == 200 and "event: done" in r.text
    finally:
        main.FILING.release()


def test_two_replayed_filings_at_once_both_finish(client, monkeypatch):
    monkeypatch.setenv("CLAIM_REPLAY_DELAY", "0.03")   # long enough for the two runs to overlap
    chart = client.post("/visit", json={"visit_id": "e4"}).json()["chart"]
    out = {}

    def run(k):
        r = TestClient(main.app).post("/file", json={"approved": True, "chart": chart})
        out[k] = (r.status_code, "event: done" in r.text)

    ts = [threading.Thread(target=run, args=(k,)) for k in "ab"]
    [t.start() for t in ts]; [t.join(30) for t in ts]
    assert out == {"a": (200, True), "b": (200, True)}


def test_live_filings_still_run_one_at_a_time(monkeypatch):
    """Live filing drives one real browser: the lock stays for it."""
    monkeypatch.delenv("CLAIM_REPLAY", raising=False)
    monkeypatch.setenv("CLAIM_DATE", "2026-10-29")
    monkeypatch.setattr(filer, "file_claim", lambda *a, **k: pytest.fail("the agent must not start"))
    c = TestClient(main.app)
    chart = replay.visits()["e4"]["chart"]
    assert main.FILING.acquire(blocking=False)
    try:
        r = c.post("/file", json={"approved": True, "chart": chart})
        assert r.status_code == 409 and r.json()["detail"] == "A filing is already running."
    finally:
        main.FILING.release()


def test_head_on_the_screen_answers(client):
    """Link checkers and uptime monitors send HEAD; it used to answer 405."""
    assert client.head("/").status_code == 200


def test_the_replay_tag_says_what_runs_live(client, monkeypatch):
    assert "No network is used" in client.get("/").text   # replay only: every model call is answered from saved outputs
    monkeypatch.setenv("CLAIM_LIVE_VOICE", "1")
    html = client.get("/").text
    assert "No network is used" not in html and "Your own recording runs live" in html
