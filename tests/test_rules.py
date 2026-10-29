import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import rules

R = rules.load()
TRIO = ["oral_exam", "prophylaxis", "fluoride_varnish"]


def chart(services=TRIO, teeth=None, date="2026-10-29", kpp=True, pain=False):
    return {"service_date": date, "kpp_registered": kpp, "services": list(services), "teeth": teeth or {}, "emergency_pain": pain}


def run(c, history=(), filed="2026-10-29"):
    return rules.check(c, list(history), R, filed)


def test_first_visit_plain_is_oph01():
    r = run(chart())
    assert r["code"] == "OPH01" and r["claimable"] and r["problems"] == []


def test_first_visit_one_sealant_is_oph01a():
    assert run(chart(TRIO + ["sealant"], {"sealant": [16]}))["code"] == "OPH01A"


def test_first_visit_two_teeth_is_oph01b():
    assert run(chart(TRIO + ["sealant", "class_v"], {"sealant": [16], "class_v": [36]}))["code"] == "OPH01B"


def test_second_visit_codes():
    prior = [chart(date="2026-03-02")]
    assert run(chart(), prior)["code"] == "OPH02"
    assert run(chart(TRIO + ["sealant"], {"sealant": [26]}), prior)["code"] == "OPH02A"


def test_missing_fluoride_blocks_the_claim():
    r = run(chart(["oral_exam", "prophylaxis"]))
    assert not r["claimable"] and r["code"] is None
    assert any("Missing: fluoride varnish" in p for p in r["problems"])


def test_tooth_cap_two_a_year_counts_earlier_visits():
    prior = [chart(TRIO + ["sealant"], {"sealant": [36]}, date="2026-03-02")]
    r = run(chart(TRIO + ["sealant"], {"sealant": [16, 26, 46]}), prior)
    assert r["code"] == "OPH02A" and r["covered_teeth"] == {"sealant": [16]}
    assert r["left"]["teeth"] == 0
    assert any("1 already used this year, 1 left" in p and "26, 46" in p for p in r["problems"])


def test_cap_resets_next_year():
    prior = [chart(TRIO + ["sealant"], {"sealant": [36, 46]}, date="2025-11-02")]
    r = run(chart(TRIO + ["sealant"], {"sealant": [16, 26]}), prior)
    assert r["code"] == "OPH01B" and r["left"]["teeth"] == 0 and r["visit"] == 1


def test_extraction_needs_emergency_pain():
    r = run(chart(TRIO + ["extraction"], {"extraction": [46]}))
    assert any("severe tooth pain" in p for p in r["problems"]) and "extraction" not in r["covered_teeth"]
    r2 = run(chart(TRIO + ["extraction"], {"extraction": [46]}, pain=True))
    assert r2["problems"] == [] and r2["covered_teeth"] == {"extraction": [46]}


def test_filing_after_60_days_blocks():
    assert run(chart(date="2026-08-29"), filed="2026-10-28")["claimable"]   # 60 days
    r = run(chart(date="2026-08-29"), filed="2026-10-29")                  # 61 days
    assert not r["claimable"] and any("within 60 days" in p for p in r["problems"])


def test_third_visit_has_no_code():
    prior = [chart(date="2026-02-01"), chart(date="2026-06-01")]
    r = run(chart(), prior)
    assert not r["claimable"] and r["visit"] == 3 and r["left"]["visits"] == 0


def test_not_registered_with_kpp_blocks():
    r = run(chart(kpp=False))
    assert not r["claimable"] and any("Konsulta Package Provider" in p for p in r["problems"])


def test_fdi_tooth_numbers():
    assert rules.valid_tooth(11) and rules.valid_tooth(48) and rules.valid_tooth(85)
    assert not rules.valid_tooth(19) and not rules.valid_tooth(49) and not rules.valid_tooth(56)
    r = run(chart(TRIO + ["sealant"], {"sealant": [19]}))
    assert r["code"] == "OPH01" and any("not a real tooth" in p for p in r["problems"])


def test_no_money_in_checker_output():
    import json
    out = json.dumps(run(chart(TRIO + ["sealant"], {"sealant": [16, 26, 36]})))
    for bad in ("Php", "PHP", "₱", "peso"):
        assert bad not in out
