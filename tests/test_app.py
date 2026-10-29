"""Endpoint tests. Meta is never called: replay mode answers from the saved outputs, and the live path runs with stubs."""
import json
import pytest
from fastapi.testclient import TestClient
from app import filer, main, replay, rules


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CLAIM_REPLAY", "1")
    monkeypatch.setenv("CLAIM_REPLAY_DELAY", "0")
    return TestClient(main.app)


@pytest.fixture
def live(monkeypatch):
    """Not replay: Meta calls are stubbed with the saved take."""
    monkeypatch.delenv("CLAIM_REPLAY", raising=False)
    monkeypatch.setenv("CLAIM_DATE", "2026-10-29")
    saved = replay.visits()
    by_heard = {v["heard"]: v["chart"] for v in saved.values()}
    calls = []
    monkeypatch.setattr(main.meta, "chart_from_text", lambda text: calls.append(("chart", text)) or by_heard[text])
    monkeypatch.setattr(main.meta, "transcribe", lambda path: calls.append(("asr", open(path, "rb").read())) or saved["e4"]["heard"])
    c = TestClient(main.app); c.calls = calls
    return c


def events(text):
    out = []
    for block in text.split("\n\n"):
        if block.startswith("event: "):
            ev, data = block.split("\n", 1)
            out.append((ev[7:], json.loads(data[6:])))
    return out


def visit(client, vid):
    r = client.post("/visit", json={"visit_id": vid})
    assert r.status_code == 200, r.text
    return r.json()


# ---------- patient and screen ----------

def test_sample_patient_is_obviously_fake_with_one_earlier_sealant(client):
    j = client.get("/patient").json()
    assert j["patient"]["name"] == "Juan Dela Cruz (sample)" and j["replay"] is True
    h = j["patient"]["history"]
    assert len(h) == 1 and h[0]["service_date"].startswith("2026") and h[0]["teeth"] == {"sealant": [46]}
    assert j["saved_visits"] == ["e1", "e2", "e3", "e4", "e5"]


def test_screen_is_served_and_shows_the_replay_tag_only_in_replay(client, monkeypatch):
    html = client.get("/").text
    assert 'data-replay="1"' in html and 'id="replay-tag" class="tag" title=' in html and ">replay</span>" in html
    monkeypatch.delenv("CLAIM_REPLAY")
    html = TestClient(main.app).get("/").text
    assert 'data-replay="0"' in html and 'id="replay-tag" class="tag" hidden' in html


# ---------- /visit ----------

def test_visit_4_sealants_three_teeth_one_left(client):
    d = visit(client, "e4")
    assert "sealant on sixteen" in d["heard"] and d["source"] == "saved" and d["replay"] is True
    assert d["chart"]["teeth"]["sealant"] == [16, 26, 36]
    c = d["check"]
    assert c["code"] == "OPH02A" and c["claimable"] and c["visit"] == 2
    assert c["covered_teeth"] == {"sealant": [16]} and c["refused_teeth"] == {"sealant": [26, 36]}
    assert c["left"] == {"teeth": 0, "visits": 0}
    assert any(not l["ok"] and "26, 36" in l["detail"] for l in c["lines"])
    assert d["claim"]["code"] == "OPH02A" and d["claim"]["teeth"] == "16" and d["file_blocked"] is None


def test_visit_3_without_fluoride_cannot_be_filed(client):
    d = visit(client, "e3")
    assert d["check"]["code"] is None and not d["check"]["claimable"]
    assert d["claim"] is None and d["file_blocked"]
    assert any(l["id"] == "mandatory" and not l["ok"] and "fluoride varnish" in l["detail"] for l in d["check"]["lines"])


def test_visit_5_emergency_extraction_is_covered(client):
    d = visit(client, "e5")
    assert d["check"]["covered_teeth"] == {"extraction": [46]} and d["check"]["refused_teeth"] == {}
    assert d["claim"]["services"][-1] == "extraction" and d["claim"]["teeth"] == "46"


def test_visit_has_inferred_notes_and_no_tagalog_on_screen_data(client):
    d = visit(client, "e1")
    assert len(d["inferred"]) == 2 and all(not t.startswith("inferred") for t in d["inferred"])
    assert "sa loob" not in json.dumps(d)


def test_replay_refuses_what_it_has_not_saved(client):
    assert client.post("/visit", json={"text": "exam and cleaning today"}).status_code == 409
    assert client.post("/visit", files={"audio": ("v.webm", b"abc", "audio/webm")}).status_code == 409
    assert client.post("/visit", json={"visit_id": "e9"}).status_code == 404
    heard = replay.visits()["e2"]["heard"]
    assert client.post("/visit", json={"text": heard.upper()}).json()["source"] == "text"


@pytest.mark.parametrize("body", [{}, {"text": "   "}, {"text": 5}, [], {"text": "x" * 5000}])
def test_visit_rejects_bad_input(client, body):
    assert client.post("/visit", json=body).status_code in (400, 413)


def test_visit_rejects_bad_dates(client):
    assert client.post("/visit", json={"visit_id": "e4", "service_date": "29/10/2026"}).status_code == 400


def test_live_text_and_audio_go_through_the_meta_calls(live):
    heard = replay.visits()["e4"]["heard"]
    d = live.post("/visit", json={"text": heard}).json()
    assert d["source"] == "text" and d["check"]["code"] == "OPH02A" and d["replay"] is False
    a = live.post("/visit", files={"audio": ("visit.webm", b"fake audio bytes", "audio/webm")}).json()
    assert a["source"] == "audio" and a["heard"] == heard and a["check"]["covered_teeth"] == {"sealant": [16]}
    assert ("asr", b"fake audio bytes") in live.calls and ("chart", heard) in live.calls


def test_live_meta_failure_is_a_plain_502_without_details(live, monkeypatch):
    def boom(text): raise RuntimeError("secret detail Bearer abc123")
    monkeypatch.setattr(main.meta, "chart_from_text", boom)
    r = live.post("/visit", json={"text": "exam"})
    assert r.status_code == 502 and "abc123" not in r.text and "secret" not in r.text


def test_late_filing_blocks_the_claim(client):
    d = client.post("/visit", json={"visit_id": "e4", "filing_date": "2027-01-15"}).json()
    assert not d["check"]["claimable"] and any("within 60 days" in p for p in d["check"]["problems"])


# ---------- /file ----------

def body(client, vid="e4", **extra):
    d = visit(client, vid)
    return {"approved": True, "chart": d["chart"], "service_date": d["service_date"], **extra}


def test_file_refuses_without_approval(client, monkeypatch):
    monkeypatch.setattr(filer, "replay_claim", lambda *a, **k: pytest.fail("the agent must not start"))
    monkeypatch.setattr(filer, "file_claim", lambda *a, **k: pytest.fail("the agent must not start"))
    b = body(client)
    for bad in ({k: v for k, v in b.items() if k != "approved"}, {**b, "approved": False}, {**b, "approved": "true"}, {**b, "approved": 1}):
        assert client.post("/file", json=bad).status_code == 400
    assert client.post("/file", content=b"not json").status_code == 400
    assert client.post("/file", json=[]).status_code == 400


def test_file_refuses_a_claim_the_checker_did_not_clear(client):
    r = client.post("/file", json=body(client, "e3"))
    assert r.status_code == 400 and "benefit code" in r.json()["detail"]


def test_file_ignores_a_code_sent_by_the_browser(client):
    b = body(client); b["claim"] = {"code": "OPH01B"}; b["code"] = "OPH01B"
    ev = events(client.post("/file", json=b).text)
    assert ev[0][1]["claim"]["code"] == "OPH02A"


def test_file_rejects_a_malformed_chart(client):
    for chart in (None, {}, {"services": {}, "teeth": {"sealant": ["16"]}}, {"services": {}, "teeth": {"sealant": [True]}}):
        assert client.post("/file", json={"approved": True, "chart": chart}).status_code == 400


def test_replay_filing_streams_every_step_then_the_readback(client):
    r = client.post("/file", json=body(client))
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = events(r.text)
    kinds = [k for k, _ in ev]
    assert kinds[0] == "start" and kinds[-1] == "done" and kinds.count("step") == 11
    steps = [d for k, d in ev if k == "step"]
    assert [s["n"] for s in steps] == list(range(1, 12))
    assert all(s["image"].startswith("data:image/jpeg;base64,") and len(s["image"]) < 120_000 and s["action"] for s in steps)
    done = ev[-1][1]
    assert done["all_ok"] and done["right"] == done["total"] == 9 and done["replay"] is True and done["stopped"] is None
    assert {r["field"] for r in done["readback"]} == {"patient", "pin", "kpp", "date", "visit", "code", "services", "teeth", "dentist"}
    assert done["acknowledged"] == 11 and done["image"].startswith("data:image/jpeg")


def test_replay_filing_only_plays_the_recorded_claim(client):
    assert client.post("/file", json=body(client, "e5")).status_code == 409
    assert client.post("/file", json=body(client, "e2")).status_code == 200   # visit 2 files the same claim as visit 4


def test_live_filing_runs_the_agent_only_after_approval(live, monkeypatch):
    seen = {}

    def fake(claim, emit, stop=None):
        seen["claim"] = claim
        emit("step", {"n": 1, "action": "click", "image": "data:image/jpeg;base64,AA==", "acknowledged": True})
        return {"model": "m", "steps": 2, "seconds": 1, "final": "ok", "stopped": None, "readback": [], "all_ok": False, "right": 0,
                "total": 0, "image": "", "acknowledged": [{}], "actions": []}

    monkeypatch.setattr(filer, "file_claim", fake)
    heard = replay.visits()["e4"]["heard"]
    chart = live.post("/visit", json={"text": heard}).json()["chart"]
    assert live.post("/file", json={"chart": chart}).status_code == 400 and not seen
    ev = events(live.post("/file", json={"approved": True, "chart": chart}).text)
    assert [k for k, _ in ev] == ["start", "step", "done"] and seen["claim"]["code"] == "OPH02A"


def test_a_failing_agent_ends_with_an_error_event_and_frees_the_lock(live, monkeypatch):
    def boom(claim, emit, stop=None): raise RuntimeError("Bearer abc123")
    monkeypatch.setattr(filer, "file_claim", boom)
    chart = live.post("/visit", json={"text": replay.visits()["e4"]["heard"]}).json()["chart"]
    for _ in range(2):   # the second run proves the lock was released
        r = live.post("/file", json={"approved": True, "chart": chart})
        ev = events(r.text)
        assert ev[-1][0] == "error" and "abc123" not in r.text


# ---------- the filer's safety-check policy and read-back ----------

class Page:
    def __init__(self, url): self.url = url


def test_safety_checks_are_acknowledged_only_on_the_local_portal_for_plain_actions():
    chk = {"pending_safety_checks": [{"code": "x"}], "actions": [{"type": "click"}, {"type": "type", "text": "a"}]}
    acked = []
    assert filer.review(Page(filer.PORTAL_URL), chk, acked, True) and len(acked) == 1 and acked[0]["actions"] == chk["actions"]
    assert not filer.review(Page(filer.PORTAL_URL), chk, [], False)                        # no ack flag: stop
    assert not filer.review(Page("https://example.com/"), chk, [], True)                   # another page: stop
    assert not filer.review(Page("file:///etc/passwd"), chk, [], True)
    assert not filer.review(Page(filer.PORTAL_URL + "-copy"), chk, [], True)
    assert not filer.review(Page(filer.PORTAL_URL), {**chk, "actions": [{"type": "click"}, {"type": "open_url"}]}, [], True)  # not a plain input


def test_readback_flags_a_wrong_field():
    claim = {"patient": "A", "pin": "1", "kpp": "K", "date": "2026-10-29", "visit": "2", "code": "OPH02A",
             "services": ["oral_exam", "sealant"], "teeth": "16, 26", "dentist": "9"}
    got = {**claim, "services": ["sealant", "oral_exam"], "teeth": "26,16", "code": "OPH02B"}
    rows = {r["field"]: r["ok"] for r in filer.readback(claim, got)}
    assert rows["code"] is False and rows["services"] and rows["teeth"] and sum(rows.values()) == 8
    assert not any(r["ok"] for r in filer.readback(claim, None))


def test_the_task_for_the_saved_claim_matches_the_day_1_task():
    c = replay.json.load(open(filer.RECORDED))["submitted"]
    t = filer.task_text({**c, "services": c["services"]})
    assert "Visit this year: 2nd visit" in t and "Services done: Oral exam, Prophylaxis, Fluoride varnish, Pit and fissure sealant (leave the others unchecked)" in t


# ---------- the checker's added fields ----------

def test_checker_lines_cover_every_rule_and_do_not_change_the_decision():
    R = rules.load()
    chart = {"service_date": "2026-10-29", "kpp_registered": True, "services": ["oral_exam", "prophylaxis", "fluoride_varnish", "extraction"],
             "teeth": {"extraction": [46]}, "emergency_pain": False}
    r = rules.check(chart, [], R, "2026-10-29")
    assert [l["id"] for l in r["lines"]] == ["eligibility:kpp_registered", "mandatory", "tooth_numbers", "visits", "cap:sealant+class_v", "conditional:extraction", "deadline"]
    assert r["refused_teeth"] == {"extraction": [46]} and r["code"] == "OPH01"
    assert [l["ok"] for l in r["lines"]] == [True, True, True, True, True, False, True]


# ---------- the model call ----------

class Resp:
    def __init__(self, code, body=None): self.status_code, self._b = code, body or {}
    def json(self): return self._b


def test_model_call_retries_a_server_error_then_succeeds(monkeypatch):
    seq = [Resp(503), Resp(429), Resp(200, {"ok": 1})]
    monkeypatch.setattr(filer.httpx, "post", lambda *a, **k: seq.pop(0))
    monkeypatch.setattr(filer.meta, "key", lambda: "k"); monkeypatch.setattr(filer.time, "sleep", lambda s: None)
    assert filer.call({}) == {"ok": 1} and not seq


def test_model_call_gives_up_with_a_status_and_never_retries_a_client_error(monkeypatch):
    n = []
    monkeypatch.setattr(filer.httpx, "post", lambda *a, **k: n.append(1) or Resp(400, {"error": "Bearer abc123"}))
    monkeypatch.setattr(filer.meta, "key", lambda: "k"); monkeypatch.setattr(filer.time, "sleep", lambda s: None)
    with pytest.raises(filer.ModelError) as e:
        filer.call({})
    assert "HTTP 400" in str(e.value) and "abc123" not in str(e.value) and len(n) == 1
    monkeypatch.setattr(filer.httpx, "post", lambda *a, **k: Resp(502))
    with pytest.raises(filer.ModelError, match="HTTP 502"):
        filer.call({})


def test_the_screen_gets_the_model_status_when_the_agent_fails(live, monkeypatch):
    def boom(claim, emit, stop=None): raise filer.ModelError("The model service answered HTTP 503.")
    monkeypatch.setattr(filer, "file_claim", boom)
    chart = live.post("/visit", json={"text": replay.visits()["e4"]["heard"]}).json()["chart"]
    ev = events(live.post("/file", json={"approved": True, "chart": chart}).text)
    assert ev[-1][0] == "error" and "HTTP 503" in ev[-1][1]["message"]
