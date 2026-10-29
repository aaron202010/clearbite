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
    -> {"code", "claimable", "visit", "problems": [str], "covered_teeth": {service: [...]}, "left": {"teeth", "visits"},
        "lines": [{"id", "title", "ok", "na", "detail"}] (one per rule, for the screen), "refused_teeth": {service: [...]}}"""
    problems, services, teeth = [], set(chart.get("services", [])), chart.get("teeth", {})
    label = lambda s: rules["labels"].get(s, s)
    lines = []

    def line(rule_id, title, start, ok_detail="", na=False, fail_detail=None):
        new = problems[start:]
        lines.append({"id": rule_id, "title": title, "ok": not new, "na": na and not new,
                      "detail": (fail_detail or " ".join(new)) if new else ok_detail})

    for rule in rules["eligibility"]:
        n0 = len(problems)
        if not chart.get(rule["field"]):
            problems.append(rule["reason"])
        line("eligibility:" + rule["field"], rule.get("title", rule["reason"]), n0)
    n0 = len(problems)
    missing = [s for s in rules["mandatory_services"] if s not in services]
    if missing:
        problems.append("Every visit needs " + ", ".join(label(s) for s in rules["mandatory_services"])
                        + ". Missing: " + ", ".join(label(s) for s in missing) + ".")
    line("mandatory", "Every visit: " + ", ".join(label(s) for s in rules["mandatory_services"]), n0,
         "All were done.", fail_detail="Missing: " + ", ".join(label(s) for s in missing) + ".")
    n0 = len(problems)
    for s in TOOTH_SERVICES:
        bad = [n for n in teeth.get(s, []) if not valid_tooth(n)]
        if bad:
            problems.append(f"Tooth number {', '.join(map(str, bad))} is not a real tooth (FDI numbering).")
    line("tooth_numbers", "Tooth numbers are real teeth (FDI)", n0)
    yr = _year(chart["service_date"])
    same_year = [h for h in history if _year(h["service_date"]) == yr]
    visit = len(same_year) + 1
    max_visit = max(c["visit"] for c in rules["codes"])
    n0 = len(problems)
    if visit > max_visit:
        problems.append(f"This is visit {visit} this year. The benefit codes cover {max_visit} visits a year.")
    line("visits", f"At most {max_visit} visits a year with a benefit code", n0, f"This is visit {visit} of {max_visit} this year.")
    covered = {s: [n for n in teeth.get(s, []) if valid_tooth(n)] for s in TOOTH_SERVICES if teeth.get(s)}
    teeth_left = None
    for cap in rules["tooth_caps"]:
        n0 = len(problems)
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
        line("cap:" + "+".join(cap["services"]), cap.get("title", cap["reason"]), n0,
             f"{used} of {cap['max_teeth_per_year']} used before this visit, {left} left.",
             fail_detail=f"{used} already used this year, {left} left. Not covered: tooth "
                         + ", ".join(str(n) for _, n in asked[left:]) + "." if len(asked) > left else None)
    for rule in rules["conditional_services"]:
        n0 = len(problems)
        if rule["service"] in services and not chart.get(rule["requires"]):
            problems.append(rule["reason"])
            covered.pop(rule["service"], None)
        line("conditional:" + rule["service"], rule.get("title", rule["reason"]), n0,
             "Pain emergency recorded." if rule["service"] in services else "Not used in this visit.",
             na=rule["service"] not in services)
    n0 = len(problems)
    days = (date.fromisoformat(filing_date) - date.fromisoformat(chart["service_date"])).days
    if days > rules["filing_deadline_days"]:
        problems.append(f"Claims must be filed within {rules['filing_deadline_days']} days of the service. This one is {days} days late to file.")
    line("deadline", f"Filed within {rules['filing_deadline_days']} days of the service", n0,
         "Filed on the day of the service." if days == 0 else f"{days} days after the service.",
         fail_detail=f"{days} days after the service.")
    n_teeth = sum(len(covered.get(s, [])) for cap in rules["tooth_caps"] for s in cap["services"])
    code = next((c["code"] for c in rules["codes"] if c["visit"] == visit and c["teeth_min"] <= n_teeth <= c["teeth_max"]), None)
    blocking = bool(missing) or visit > max_visit or days > rules["filing_deadline_days"] or any(
        not chart.get(r["field"]) for r in rules["eligibility"])
    return {"code": None if blocking else code, "claimable": not blocking and code is not None, "visit": visit,
            "problems": problems, "covered_teeth": {s: v for s, v in covered.items() if v},
            "left": {"teeth": teeth_left, "visits": max(max_visit - visit, 0)}, "lines": lines,
            "refused_teeth": {s: [n for n in teeth.get(s, []) if n not in covered.get(s, [])] for s in TOOTH_SERVICES
                              if any(n not in covered.get(s, []) for n in teeth.get(s, []))}}
