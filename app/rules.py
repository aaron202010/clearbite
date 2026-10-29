"""The claim checker. It reads one payer's rules from a JSON file (rules/<payer>.json) and checks a chart against them.
No payer logic lives in this file: a second payer is a second rules file."""
import json, os
from datetime import date

RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "rules")
TOOTH_SERVICES = ("sealant", "class_v", "extraction")


def load(payer="philhealth_oph"):
    return json.load(open(os.path.join(RULES_DIR, payer + ".json")))


def valid_tooth(n):
    """FDI numbering: permanent 11-48, baby teeth 51-85."""
    q, t = divmod(int(n), 10)
    return (1 <= q <= 4 and 1 <= t <= 8) or (5 <= q <= 8 and 1 <= t <= 5)


def _year(d):
    return date.fromisoformat(d).year


def check(chart, history, rules, filing_date):
    """chart: {"service_date", "kpp_registered", "services": [...], "teeth": {service: [FDI...]}, "emergency_pain"}
    history: earlier claims for this patient, same shape. filing_date: "YYYY-MM-DD".
    -> {"code", "claimable", "visit", "problems": [str], "covered_teeth": {service: [...]}, "left": {"teeth", "visits"}}"""
    problems, services, teeth = [], set(chart.get("services", [])), chart.get("teeth", {})
    label = lambda s: rules["labels"].get(s, s)
    for rule in rules["eligibility"]:
        if not chart.get(rule["field"]):
            problems.append(rule["reason"])
    missing = [s for s in rules["mandatory_services"] if s not in services]
    if missing:
        problems.append("Every visit needs " + ", ".join(label(s) for s in rules["mandatory_services"])
                        + ". Missing: " + ", ".join(label(s) for s in missing) + ".")
    for s in TOOTH_SERVICES:
        bad = [n for n in teeth.get(s, []) if not valid_tooth(n)]
        if bad:
            problems.append(f"Tooth number {', '.join(map(str, bad))} is not a real tooth (FDI numbering).")
    yr = _year(chart["service_date"])
    same_year = [h for h in history if _year(h["service_date"]) == yr]
    visit = len(same_year) + 1
    max_visit = max(c["visit"] for c in rules["codes"])
    if visit > max_visit:
        problems.append(f"This is visit {visit} this year. The benefit codes cover {max_visit} visits a year.")
    covered = {s: [n for n in teeth.get(s, []) if valid_tooth(n)] for s in TOOTH_SERVICES if teeth.get(s)}
    teeth_left = None
    for cap in rules["tooth_caps"]:
        used = sum(len(h.get("teeth", {}).get(s, [])) for h in same_year for s in cap["services"])
        left = max(cap["max_teeth_per_year"] - used, 0)
        asked = [(s, n) for s in cap["services"] for n in covered.get(s, [])]
        if len(asked) > left:
            dropped = asked[left:]
            problems.append(f"{cap['reason']} {used} already used this year, {left} left. "
                            f"Not covered: tooth {', '.join(str(n) for _, n in dropped)}.")
            for s, n in dropped:
                covered[s].remove(n)
        teeth_left = left - min(len(asked), left)
    for rule in rules["conditional_services"]:
        if rule["service"] in services and not chart.get(rule["requires"]):
            problems.append(rule["reason"])
            covered.pop(rule["service"], None)
    days = (date.fromisoformat(filing_date) - date.fromisoformat(chart["service_date"])).days
    if days > rules["filing_deadline_days"]:
        problems.append(f"Claims must be filed within {rules['filing_deadline_days']} days of the service. This one is {days} days late to file.")
    n_teeth = sum(len(covered.get(s, [])) for cap in rules["tooth_caps"] for s in cap["services"])
    code = next((c["code"] for c in rules["codes"] if c["visit"] == visit and c["teeth_min"] <= n_teeth <= c["teeth_max"]), None)
    blocking = bool(missing) or visit > max_visit or days > rules["filing_deadline_days"] or any(
        not chart.get(r["field"]) for r in rules["eligibility"])
    return {"code": None if blocking else code, "claimable": not blocking and code is not None, "visit": visit,
            "problems": problems, "covered_teeth": {s: v for s, v in covered.items() if v},
            "left": {"teeth": teeth_left, "visits": max(max_visit - visit, 0)}}
