"""No money anywhere on the screen: the screen HTML and what the screen shows (the patient, a visit, the filing stream) never carry
a peso sign, "Php", "PHP", "peso" or a dollar amount. The scan is itself tested on known bad samples."""
import json, re
import pytest
from fastapi.testclient import TestClient
from app import main

MONEY = re.compile(r"₱|₱|\bphp\b|\bpesos?\b|\$\s?\d|\bUSD\b|\bamount due\b", re.I)


def money_in(text):
    return sorted({m.group(0) for m in MONEY.finditer(text)})


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CLAIM_REPLAY", "1")
    monkeypatch.setenv("CLAIM_REPLAY_DELAY", "0")
    return TestClient(main.app)


def test_screen_and_sample_visit_have_no_money(client):
    html = client.get("/").text
    patient = client.get("/patient").text
    visits = [client.post("/visit", json={"visit_id": f"e{i}"}).text for i in range(1, 6)]
    chart = client.post("/visit", json={"visit_id": "e4"}).json()["chart"]
    stream = client.post("/file", json={"approved": True, "chart": chart}).text
    assert len(html) > 10_000 and "Approve and file" in html and len(stream) > 100_000
    for name, text in [("screen", html), ("patient", patient), ("filing stream", stream)] + [(f"visit {i + 1}", v) for i, v in enumerate(visits)]:
        assert money_in(text) == [], f"money marker in {name}"
    assert money_in(html + json.dumps(json.loads(visits[3]))) == []


@pytest.mark.parametrize("bad", [
    "Benefit: ₱1,500", "Php 300 per tooth", "Total PHP 2,000", "paid in pesos", "the peso amount", "Cost $45", "USD 12", "Amount due today",
    '<span class="fee">PhP</span>',
])
def test_the_scan_catches_known_bad_samples(bad):
    assert money_in(bad), bad


@pytest.mark.parametrize("fine", ["Left this year: 0 teeth, 0 visits", "Benefit code OPH02A", "Member PIN 12-345678901-2", "phpinfo is not a price", "Sample Konsulta Clinic"])
def test_the_scan_leaves_clean_text_alone(fine):
    assert money_in(fine) == []
