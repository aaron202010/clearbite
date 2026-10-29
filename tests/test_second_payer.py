"""The second payer (Washington Apple Health, Medicaid dental): the rules from rules/wa_apple_health.json, the two sample patients,
the payer and patient switches (POST /check) and the guarantee that app/rules.py stays free of payer names.
Every number below comes from the regulation text in the research note (WAC 182-535-1082, 182-535-1080, 182-502-0150)."""
import json, os, re, sys
from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import main, replay, rules

W, P = rules.load("wa_apple_health"), rules.load("philhealth_oph")
TRIO = ["oral_exam", "prophylaxis", "fluoride_varnish"]
TODAY = date(2026, 10, 29)
PATIENTS = {p["id"]: p for p in json.load(open(os.path.join(os.path.dirname(__file__), "..", "data", "patients.json")))}
JUAN, ANA = PATIENTS["sample-001"], PATIENTS["sample-002"]
MONEY = re.compile(r"₱|\bphp\b|\bpesos?\b|\$\s?\d|\bUSD\b|\bamount due\b", re.I)


def ago(days):
    return (TODAY - timedelta(days=days)).isoformat()


def born(age, extra_days=0):
    """A birth date that makes the patient exactly this age on 2026-10-29 (extra_days past the birthday)."""
    return (date(TODAY.year - age, TODAY.month, TODAY.day) - timedelta(days=extra_days)).isoformat()


def chart(services=TRIO, teeth=None, age=12, day=TODAY.isoformat(), birth=None):
    return {"service_date": day, "birth_date": birth or born(age), "services": list(services), "teeth": teeth or {}, "emergency_pain": False}


def past(date_, services=TRIO, teeth=None):
    return {"service_date": date_, "services": list(services), "teeth": teeth or {}, "emergency_pain": False}


def run(c, history=(), filed=TODAY.isoformat(), rl=W):
    return rules.check(c, list(history), rl, filed)


def line(r, rule_id):
    return next(l for l in r["lines"] if l["id"] == rule_id)


def state(r, service):
    return next(p["state"] for p in r["procedures"] if p["service"] == service)


# ---------- age on the service date ----------

def test_age_is_counted_on_the_service_date():
    assert rules.age_on("2014-03-09", "2026-10-29") == 12
    assert rules.age_on("2014-03-09", "2026-03-08") == 11 and rules.age_on("2014-03-09", "2026-03-09") == 12
    assert rules.age_on("2008-02-29", "2026-02-28") == 17 and rules.age_on("2008-02-29", "2026-03-01") == 18
    assert (ANA["birth_date"], JUAN["birth_date"]) == ("2014-03-09", "1986-05-14")
    assert rules.age_on(JUAN["birth_date"], "2026-10-29") == 40 and rules.age_on(ANA["birth_date"], "2026-10-29") == 12


def test_a_rule_that_needs_the_age_says_so_when_the_birth_date_is_missing():
    c = chart(TRIO + ["sealant"], {"sealant": [16]}); c["birth_date"] = None
    r = run(c)
    assert r["age"] is None and not line(r, "age:sealant")["ok"] and "date of birth is needed" in line(r, "age:sealant")["detail"]
    assert state(r, "sealant") == "refused" and r["covered_teeth"] == {}
    c = chart(["oral_exam", "prophylaxis"]); c["birth_date"] = None
    r = run(c)
    assert state(r, "prophylaxis") == "refused" and "date of birth is needed" in line(r, "frequency:prophylaxis")["detail"]
    assert state(r, "oral_exam") == "covered"   # the exam limit does not depend on age


# ---------- sealants ----------

def test_sealants_refused_for_an_adult_by_age():
    r = run(chart(TRIO + ["sealant"], {"sealant": [16, 26, 36]}, age=40))
    assert r["covered_teeth"] == {} and r["refused_teeth"] == {"sealant": [16, 26, 36]} and state(r, "sealant") == "refused"
    l = line(r, "age:sealant")
    assert not l["ok"] and "Age 40" in l["detail"] and "age 20 and younger" in l["detail"] and l["source"] == "WAC 182-535-1082"


def test_sealant_age_limit_is_20_and_younger_on_the_service_date():
    c = lambda age, extra=0: chart(TRIO + ["sealant"], {"sealant": [16]}, age=age, birth=born(age, extra))
    assert run(c(20))["covered_teeth"] == {"sealant": [16]}          # turns 20 today
    assert run(c(20, 364))["covered_teeth"] == {"sealant": [16]}     # 20 until the day before the 21st birthday
    assert run(c(21))["covered_teeth"] == {}                          # turns 21 today


def test_ana_gets_sealants_on_16_26_and_36():
    r = run(chart(TRIO + ["sealant"], {"sealant": [16, 26, 36]}), ANA["history"])
    assert r["claimable"] and r["code"] is None and r["age"] == 12
    assert r["covered_teeth"] == {"sealant": [16, 26, 36]} and r["refused_teeth"] == {} and r["problems"] == []
    assert [p["service"] for p in r["procedures"] if p["state"] == "covered"] == TRIO + ["sealant"]


@pytest.mark.parametrize("tooth", [17, 16, 26, 27, 37, 36, 46, 47])
def test_the_eight_eligible_teeth_are_covered(tooth):
    assert run(chart(TRIO + ["sealant"], {"sealant": [tooth]}))["covered_teeth"] == {"sealant": [tooth]}


@pytest.mark.parametrize("tooth", [15, 14, 11, 25, 35, 45, 18, 28, 38, 48, 31])
def test_a_tooth_off_the_list_is_refused_as_not_eligible(tooth):
    r = run(chart(TRIO + ["sealant"], {"sealant": [16, tooth]}))
    assert r["covered_teeth"] == {"sealant": [16]} and r["refused_teeth"] == {"sealant": [tooth]}
    l = line(r, "teeth:sealant")
    assert not l["ok"] and f"Tooth {tooth} is not an eligible tooth" in l["detail"] and l["source"].startswith("WAC 182-535-1082")


def test_a_tooth_sealed_20_months_earlier_is_refused_and_one_sealed_40_months_earlier_is_covered():
    c = chart(TRIO + ["sealant"], {"sealant": [16, 26]})
    r = run(c, [past("2025-02-28", ["sealant"], {"sealant": [16]}), past("2023-06-29", ["sealant"], {"sealant": [26]})])
    assert r["covered_teeth"] == {"sealant": [26]} and r["refused_teeth"] == {"sealant": [16]}
    l = line(r, "window:sealant")
    assert not l["ok"] and "Tooth 16 already had sealant on 28 Feb 2025" in l["detail"] and "26" not in l["detail"]


def test_the_three_year_window_counts_back_from_the_service_date():
    c = chart(TRIO + ["sealant"], {"sealant": [16]})
    assert run(c, [past("2023-10-29", ["sealant"], {"sealant": [16]})])["covered_teeth"] == {"sealant": [16]}   # exactly 36 months
    assert run(c, [past("2023-10-30", ["sealant"], {"sealant": [16]})])["covered_teeth"] == {}                   # a day inside
    assert run(c, [past("2025-02-28", ["sealant"], {"sealant": [26]})])["covered_teeth"] == {"sealant": [16]}   # another tooth


def test_no_two_teeth_a_year_cap_in_this_file():
    r = run(chart(TRIO + ["sealant"], {"sealant": [16, 17, 26, 27, 36, 37, 46, 47]}))
    assert r["covered_teeth"] == {"sealant": [16, 17, 26, 27, 36, 37, 46, 47]} and r["left"] == {"teeth": None, "visits": None}


# ---------- cleaning, fluoride, exam: how often, by age ----------

@pytest.mark.parametrize("age,days,covered", [
    (18, 150, False), (18, 185, True),     # age 18 and younger: once every 6 months
    (19, 220, False), (19, 330, False), (19, 366, True),   # age 19 and older: once every 12 months
])
def test_cleaning_frequency_by_age(age, days, covered):
    r = run(chart(["prophylaxis"], age=age), [past(ago(days), ["prophylaxis"])])
    assert (state(r, "prophylaxis") == "covered") is covered
    assert line(r, "frequency:prophylaxis")["source"] == "WAC 182-535-1082"


def test_cleaning_six_month_edge_for_a_child():
    assert state(run(chart(["prophylaxis"], age=12), [past("2026-04-29", ["prophylaxis"])]), "prophylaxis") == "covered"   # six months to the day
    assert state(run(chart(["prophylaxis"], age=12), [past("2026-04-30", ["prophylaxis"])]), "prophylaxis") == "refused"


def test_oral_exam_once_every_six_months_at_any_age():
    for age in (5, 12, 40):
        assert state(run(chart(["oral_exam"], age=age), [past(ago(150), ["oral_exam"])]), "oral_exam") == "refused"
        r = run(chart(["oral_exam"], age=age), [past(ago(190), ["oral_exam"])])
        assert state(r, "oral_exam") == "covered" and line(r, "frequency:oral_exam")["source"] == "WAC 182-535-1080"


def fluoride(age, *days_ago):
    return run(chart(["fluoride_varnish"], age=age), [past(ago(d), ["fluoride_varnish"]) for d in days_ago])


def test_fluoride_age_6_and_younger_three_times_a_year_110_days_apart():
    assert state(fluoride(5), "fluoride_varnish") == "covered"
    assert state(fluoride(5, 90), "fluoride_varnish") == "refused"           # too soon after the last one
    assert "110 days apart" in line(fluoride(5, 90), "frequency:fluoride_varnish")["detail"]
    assert state(fluoride(5, 120), "fluoride_varnish") == "covered"
    assert state(fluoride(5, 240, 120), "fluoride_varnish") == "covered"     # the third in 12 months
    r = fluoride(5, 330, 220, 110)                                             # a fourth in 12 months
    assert state(r, "fluoride_varnish") == "refused" and "3 allowed" in line(r, "frequency:fluoride_varnish")["detail"]
    assert state(fluoride(5, 400, 330, 220), "fluoride_varnish") == "covered"  # only two in the last 12 months


def test_fluoride_ages_7_to_18_two_times_a_year_170_days_apart():
    assert state(fluoride(7, 160), "fluoride_varnish") == "refused"
    assert state(fluoride(12, 180), "fluoride_varnish") == "covered"
    assert state(fluoride(18, 300, 180), "fluoride_varnish") == "refused"    # two already in 12 months
    assert state(fluoride(18, 400, 180), "fluoride_varnish") == "covered"
    assert state(fluoride(6, 120), "fluoride_varnish") == "covered" and state(fluoride(7, 120), "fluoride_varnish") == "refused"   # the band changes at 7


def test_fluoride_age_19_and_older_once_a_year():
    assert state(fluoride(19, 200), "fluoride_varnish") == "refused"
    assert state(fluoride(40, 300), "fluoride_varnish") == "refused"
    assert state(fluoride(40, 366), "fluoride_varnish") == "covered"
    assert state(fluoride(18, 200), "fluoride_varnish") == "covered"        # one day of age earlier it is twice a year


def test_juan_adult_gets_only_the_exam_for_visit_4():
    r = run(chart(TRIO + ["sealant"], {"sealant": [16, 26, 36]}, birth=JUAN["birth_date"]), JUAN["history"])
    assert r["claimable"] and r["code"] is None
    assert {p["service"]: p["state"] for p in r["procedures"]} == {"oral_exam": "covered", "prophylaxis": "refused", "fluoride_varnish": "refused", "sealant": "refused"}
    assert r["covered_teeth"] == {} and r["refused_teeth"] == {"sealant": [16, 26, 36]}


# ---------- filing ----------

def test_filing_within_365_days():
    day = "2025-10-29"
    r = run(chart(day=day), filed="2026-10-29")      # 365 days
    assert r["claimable"] and line(r, "deadline")["source"] == "WAC 182-502-0150" and "within 365 days" in line(r, "deadline")["title"]
    r = run(chart(day=day), filed="2026-10-30")      # 366 days
    assert not r["claimable"] and any("within 365 days" in p for p in r["problems"])


# ---------- what this file does not have ----------

def test_rules_the_file_does_not_have_are_shown_as_no_rule_in_this_file_and_nothing_is_invented():
    r = run(chart(["oral_exam"], {"class_v": [31], "extraction": [46]}, age=40))       # no cleaning, no fluoride, class V and extraction
    assert r["claimable"] and r["code"] is None                                          # no "all three every visit", no benefit code
    none = [l for l in r["lines"] if l["id"].startswith("none:")]
    assert [l["id"] for l in none] == ["none:mandatory", "none:tooth_cap", "none:code", "none:class_v_extraction"]
    assert all(l["ok"] and l["na"] and l["detail"] == "No rule in this file." and l["source"] is None for l in none)
    assert r["unruled_teeth"] == {"class_v": [31], "extraction": [46]} and r["covered_teeth"] == {} and r["refused_teeth"] == {}
    assert {p["service"]: p["state"] for p in r["procedures"]} == {"oral_exam": "covered", "class_v": "no_rule", "extraction": "no_rule"}
    ids = [l["id"] for l in r["lines"] if not l["id"].startswith("none:")]
    assert "mandatory" not in ids and "visits" not in ids and not any(i.startswith(("cap:", "conditional:", "eligibility:")) for i in ids)


def test_nothing_covered_means_no_claim():
    r = run(chart(["prophylaxis"], {"class_v": [31]}, age=40), [past(ago(100), ["prophylaxis"])])
    assert not r["claimable"] and state(r, "prophylaxis") == "refused" and state(r, "class_v") == "no_rule"


# ---------- sources ----------

@pytest.mark.parametrize("rl", [P, W], ids=["first payer", "second payer"])
def test_every_rule_line_carries_a_source(rl):
    c = chart(TRIO + ["sealant", "class_v", "extraction"], {"sealant": [16], "class_v": [26], "extraction": [46]})
    c["kpp_registered"] = True
    r = run(c, rl=rl)
    ruled = [l for l in r["lines"] if l["id"] != "tooth_numbers" and not l["id"].startswith("none:")]
    assert len(ruled) >= 5 and all(isinstance(l["source"], str) and 6 < len(l["source"]) < 80 for l in ruled), [l["id"] for l in ruled if not l["source"]]
    for kind in ("eligibility", "tooth_caps", "conditional_services", "age_limits", "eligible_teeth", "tooth_windows", "frequency"):
        assert all(x.get("source") for x in rl.get(kind, [])), kind


def test_second_payer_sources_are_the_wac_sections_from_the_research_note():
    r = run(chart(TRIO + ["sealant"], {"sealant": [16]}))
    got = {l["id"]: l["source"] for l in r["lines"] if l["source"]}
    assert got["age:sealant"] == got["window:sealant"] == got["frequency:prophylaxis"] == got["frequency:fluoride_varnish"] == "WAC 182-535-1082"
    assert got["frequency:oral_exam"] == "WAC 182-535-1080" and got["deadline"] == "WAC 182-502-0150"
    assert got["teeth:sealant"].startswith("WAC 182-535-1082") and "Universal 2, 3, 14, 15, 18, 19, 30, 31" in got["teeth:sealant"]


# ---------- the first payer does not change ----------

def test_first_payer_decisions_do_not_depend_on_age():
    visit4 = chart(TRIO + ["sealant"], {"sealant": [16, 26, 36]})
    juan = run({**visit4, "birth_date": JUAN["birth_date"], "kpp_registered": True}, JUAN["history"], rl=P)
    ana = run({**visit4, "birth_date": ANA["birth_date"], "kpp_registered": True}, ANA["history"], rl=P)
    assert juan["code"] == "OPH02A" and juan["covered_teeth"] == {"sealant": [16]} and juan["refused_teeth"] == {"sealant": [26, 36]}
    assert ana["code"] == "OPH02B" and ana["covered_teeth"] == {"sealant": [16, 26]} and ana["refused_teeth"] == {"sealant": [36]}
    assert [l["id"] for l in juan["lines"]] == [l["id"] for l in ana["lines"]] and juan["unruled_teeth"] == {}


# ---------- app/rules.py has no payer in it ----------

def test_rules_py_names_no_payer():
    src = open(rules.__file__, encoding="utf-8").read().lower()
    names = {"philhealth", "washington", "medicaid", "apple health", "konsulta", "kpp", "tamang sagot"}
    for pid in rules.payers():
        r = rules.load(pid)
        names |= {pid.lower(), r["payer"].lower(), r["short_name"].lower()}
    assert len(rules.payers()) == 2 and [n for n in names if n in src] == []
    assert not re.search(r"\b(wac|oph\d*)\b", src)
    assert rules.default() == "philhealth_oph" and rules.load() == P


def test_a_payer_id_is_a_file_name_not_a_path():
    with pytest.raises(ValueError):
        rules.load("../data/patients")


# ---------- the screen's endpoints ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CLAIM_REPLAY", "1")
    monkeypatch.setenv("CLAIM_REPLAY_DELAY", "0")
    for name in ("chart_from_text", "transcribe"):
        monkeypatch.setattr(main.meta, name, lambda *a, **k: pytest.fail("no Meta call"))
    return TestClient(main.app)


def visit4_chart(client, **extra):
    d = client.post("/visit", json={"visit_id": "e4", **extra}).json()
    return d["chart"], d


def check(client, chart_, **extra):
    r = client.post("/check", json={"chart": chart_, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_patient_endpoint_lists_both_payers_and_both_patients(client):
    j = client.get("/patient").json()
    assert j["payer_id"] == "philhealth_oph" and [p["id"] for p in j["payers"]] == ["philhealth_oph", "wa_apple_health"]
    assert [p["name"] for p in j["payers"]] == ["PhilHealth", "Washington Apple Health (Medicaid)"]
    wa = j["payers"][1]
    assert j["payers"][0]["patient_facts"] == ["pin", "kpp", "kpp_registered", "dentist"]
    assert wa["per_procedure"] and not wa["filing_demo"] and wa["patient_facts"] == ["born", "age"] and wa["filing_note"] == "The filing demo uses the PhilHealth sample portal."
    assert j["payers"][0]["filing_demo"] and not j["payers"][0]["per_procedure"]
    assert [(p["name"], p["age"]) for p in j["patients"]] == [("Juan Dela Cruz (sample)", 40), ("Ana Reyes (sample)", 12)]
    assert j["patient"]["id"] == "sample-001" and j["patient"]["birth_date"] == "1986-05-14"
    ana = j["patients"][1]
    assert not any(h["teeth"].get("sealant") for h in ana["history"])


def test_check_endpoint_gives_a_different_answer_for_each_payer_and_patient(client):
    chart_, first = visit4_chart(client)
    assert first["payer"] == "philhealth_oph" and first["check"]["code"] == "OPH02A"
    ph_juan = check(client, chart_)
    ph_ana = check(client, chart_, patient_id="sample-002")
    wa_juan = check(client, chart_, payer="wa_apple_health")
    wa_ana = check(client, chart_, payer="wa_apple_health", patient_id="sample-002")
    assert ph_juan["check"] == first["check"] and ph_juan["claim"]["code"] == "OPH02A"
    assert ph_ana["check"]["code"] == "OPH02B" and ph_ana["check"]["covered_teeth"] == {"sealant": [16, 26]} and ph_ana["claim"]["patient"] == "Ana Reyes (sample)"
    assert wa_juan["check"]["code"] is None and wa_juan["check"]["covered_teeth"] == {} and wa_juan["check"]["refused_teeth"] == {"sealant": [16, 26, 36]}
    assert wa_ana["check"]["covered_teeth"] == {"sealant": [16, 26, 36]} and wa_ana["check"]["refused_teeth"] == {} and wa_ana["patient"]["age"] == 12
    assert [wa_juan["payer"], wa_ana["payer"]] == ["wa_apple_health"] * 2 and wa_juan["patient"]["id"] == "sample-001"
    assert wa_juan["summary"] == "3 teeth asked: none filed, 16, 26 and 36 left off by rule" and wa_ana["summary"] is None


def test_second_payer_cannot_be_filed_and_says_why(client):
    chart_, _ = visit4_chart(client)
    for pid in ("sample-001", "sample-002"):
        d = check(client, chart_, payer="wa_apple_health", patient_id=pid)
        assert d["claim"] is None and d["file_blocked"] == "The filing demo uses the PhilHealth sample portal."
        r = client.post("/file", json={"approved": True, "chart": chart_, "payer": "wa_apple_health", "patient_id": pid})
        assert r.status_code == 400 and r.json()["detail"] == "The filing demo uses the PhilHealth sample portal."


def test_first_payer_filing_still_works_for_the_recorded_claim_only(client):
    chart_, d = visit4_chart(client)
    assert d["file_blocked"] is None
    assert client.post("/file", json={"approved": True, "chart": chart_}).status_code == 200
    assert client.post("/file", json={"approved": True, "chart": chart_, "patient_id": "sample-001", "payer": "philhealth_oph"}).status_code == 200
    r = client.post("/file", json={"approved": True, "chart": chart_, "patient_id": "sample-002"})
    assert r.status_code == 409 and "Juan's claim" in r.json()["detail"]


def test_inferred_notes_follow_the_payer(client):
    chart_, _ = visit4_chart(client)
    ph = check(client, chart_)["inferred"]
    wa = check(client, chart_, payer="wa_apple_health")["inferred"]
    assert len(ph) == 2 and len(wa) == 3 and any("Universal numbering" in t for t in wa) and not any("circular" in t for t in wa)


def test_visit_endpoint_uses_the_chosen_payer_and_patient(client):
    d = client.post("/visit", json={"visit_id": "e4", "payer": "wa_apple_health", "patient_id": "sample-002"}).json()
    assert d["payer"] == "wa_apple_health" and d["patient"]["name"] == "Ana Reyes (sample)" and d["check"]["covered_teeth"] == {"sealant": [16, 26, 36]}
    assert d["heard"] and d["source"] == "saved"


def test_visit_with_a_recording_carries_the_choice_too(monkeypatch):
    monkeypatch.delenv("CLAIM_REPLAY", raising=False)
    monkeypatch.setenv("CLAIM_DATE", "2026-10-29")
    saved = replay.visits()["e4"]
    monkeypatch.setattr(main.meta, "transcribe", lambda path: saved["heard"])
    monkeypatch.setattr(main.meta, "chart_from_text", lambda text: saved["chart"])
    live = TestClient(main.app)
    d = live.post("/visit", files={"audio": ("v.webm", b"abc", "audio/webm")}, data={"payer": "wa_apple_health", "patient_id": "sample-002"}).json()
    assert d["payer"] == "wa_apple_health" and d["check"]["covered_teeth"] == {"sealant": [16, 26, 36]} and d["source"] == "audio"
    plain = live.post("/visit", files={"audio": ("v.webm", b"abc", "audio/webm")}).json()
    assert plain["payer"] == "philhealth_oph" and plain["check"]["code"] == "OPH02A"


@pytest.mark.parametrize("extra,status", [
    ({"payer": "nope"}, 404), ({"payer": "../data/patients"}, 404), ({"payer": ["wa_apple_health"]}, 404), ({"payer": 5}, 404),
    ({"patient_id": "sample-009"}, 404), ({"patient_id": ["sample-001"]}, 404),
])
def test_check_rejects_an_unknown_payer_or_patient(client, extra, status):
    chart_, _ = visit4_chart(client)
    assert client.post("/check", json={"chart": chart_, **extra}).status_code == status
    assert client.post("/visit", json={"visit_id": "e4", **extra}).status_code == status


@pytest.mark.parametrize("body", [None, [], {}, {"chart": None}, {"chart": {"services": {}, "teeth": {"sealant": ["16"]}}}])
def test_check_rejects_a_bad_body(client, body):
    r = client.post("/check", content=b"not json") if body is None else client.post("/check", json=body)
    assert r.status_code == 400


def test_check_rejects_a_bad_date(client):
    chart_, _ = visit4_chart(client)
    assert client.post("/check", json={"chart": chart_, "service_date": "29/10/2026"}).status_code == 400


def test_a_late_second_payer_claim_blocks_after_365_days(client):
    chart_, _ = visit4_chart(client)
    d = check(client, chart_, payer="wa_apple_health", patient_id="sample-002", filing_date="2027-10-29")   # 365 days
    assert d["check"]["claimable"]
    d = check(client, chart_, payer="wa_apple_health", patient_id="sample-002", filing_date="2027-10-30")   # 366 days
    assert not d["check"]["claimable"]


def test_no_money_in_the_second_payer_screen_data(client):
    chart_, _ = visit4_chart(client)
    texts = [client.get("/patient").text, client.get("/").text]
    for pid in ("sample-001", "sample-002"):
        texts.append(json.dumps(check(client, chart_, payer="wa_apple_health", patient_id=pid)))
    assert [m.group(0) for t in texts for m in MONEY.finditer(t)] == []


def test_screen_has_the_two_switches_and_the_per_procedure_box(client):
    html = client.get("/").text
    assert 'id="seg-payer"' in html and 'id="seg-patient"' in html and "Per-procedure claim" in html and "No rule in this file" in html
    assert "PhilHealth rule check" in html and "Born" in html and "Age at visit" in html
