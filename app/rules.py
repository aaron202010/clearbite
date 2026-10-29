"""The claim checker. It reads one payer's rules from a JSON file (rules/<payer>.json) and checks a chart against them.
No payer logic lives in this file: a second payer is a second rules file.
Rule kinds a file can carry: eligibility, mandatory_services, tooth_caps, conditional_services, codes, filing_deadline_days (the first
kinds of the checker) and age_limits, eligible_teeth, tooth_windows, frequency (by age band), not_in_this_file. A kind a file leaves out
is not checked, and a service no rule in the file governs is shown as "no rule in this file", never as covered or refused.
Every rule carries a short "source" string; the check passes it on, line by line, for the screen."""
import calendar, json, os
from datetime import date

RULES_DIR = os.path.join(os.path.dirname(__file__), "..", "rules")
TOOTH_SERVICES = ("sealant", "class_v", "extraction")
NEED_BIRTH_DATE = "The patient's date of birth is needed to check this rule."


def payers():
    """The id of every rules file in rules/ (the file name without .json)."""
    return sorted(f[:-5] for f in os.listdir(RULES_DIR) if f.endswith(".json"))


def default():
    """The payer whose file says "default": true. The screen starts on it."""
    return next(p for p in payers() if load(p).get("default"))


def load(payer=None):
    payer = payer or default()
    if os.path.basename(payer) != payer:
        raise ValueError("A payer id is a file name, not a path.")
    return json.load(open(os.path.join(RULES_DIR, payer + ".json")))


def valid_tooth(n):
    """FDI numbering: permanent 11-48, baby teeth 51-85."""
    q, t = divmod(int(n), 10)
    return (1 <= q <= 4 and 1 <= t <= 8) or (5 <= q <= 8 and 1 <= t <= 5)


def _year(d):
    return date.fromisoformat(d).year


def age_on(birth_date, day):
    """Whole years old on that day (both "YYYY-MM-DD")."""
    b, d = date.fromisoformat(birth_date), date.fromisoformat(day)
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def months_before(d, n):
    """The date n calendar months before d (the day is cut back to the month's last day when needed)."""
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    return date(y, m + 1, min(d.day, calendar.monthrange(y, m + 1)[1]))


def _nice(d):
    return f"{d.day} {d.strftime('%b %Y')}"


def _teeth(ns):
    return ("tooth " if len(ns) == 1 else "teeth ") + ", ".join(str(n) for n in ns)


def _ages(rule):
    lo, hi = rule.get("min_age"), rule.get("max_age")
    return f"ages {lo} to {hi}" if lo is not None and hi is not None else f"age {hi} and younger" if hi is not None else f"age {lo} and older"


def _band(bands, age):
    """The band that applies at this age; a band with no age limits applies to everyone."""
    for b in bands:
        if "min_age" not in b and "max_age" not in b:
            return b
        if age is not None and b.get("min_age", 0) <= age <= b.get("max_age", 200):
            return b
    return None


def check(chart, history, rules, filing_date):
    """chart: {"service_date", "birth_date", "services": [...], "teeth": {service: [FDI...]}, "emergency_pain",
    plus each field the rules file names under eligibility}
    history: earlier claims for this patient, same shape. filing_date: "YYYY-MM-DD".
    -> {"code", "claimable", "visit", "age", "problems": [str], "covered_teeth": {service: [...]}, "left": {"teeth", "visits"},
        "lines": [{"id", "title", "ok", "na", "detail", "note", "source"} (one per rule, for the screen)],
        "refused_teeth": {service: [...]}, "unruled_teeth": {service: [...]},
        "procedures": [{"service", "label", "state": covered | refused | no_rule, "tooth", "asked", "teeth"}]}"""
    problems, services, teeth = [], set(chart.get("services", [])), chart.get("teeth", {})
    label = lambda s: rules["labels"].get(s, s)
    lines = []
    day = date.fromisoformat(chart["service_date"])
    age = age_on(chart["birth_date"], chart["service_date"]) if chart.get("birth_date") else None
    refused_services = []
    governed = set(rules.get("mandatory_services", []))
    for cap in rules.get("tooth_caps", []):
        governed.update(cap["services"])
    for kind in ("conditional_services", "age_limits", "eligible_teeth", "tooth_windows", "frequency"):
        governed.update(r["service"] for r in rules.get(kind, []))
    unruled = {s for s in services | {s for s in TOOTH_SERVICES if teeth.get(s)} if s not in governed}

    def line(rule_id, title, start, ok_detail="", na=False, fail_detail=None, src=None, note=None):
        new = problems[start:]
        lines.append({"id": rule_id, "title": title, "ok": not new, "na": na and not new,
                      "detail": (fail_detail or " ".join(new)) if new else ok_detail, "note": note, "source": src})

    for rule in rules.get("eligibility", []):
        n0 = len(problems)
        if not chart.get(rule["field"]):
            problems.append(rule["reason"])
        line("eligibility:" + rule["field"], rule.get("title", rule["reason"]), n0, src=rule.get("source"))
    missing = []
    if "mandatory_services" in rules:
        n0 = len(problems)
        missing = [s for s in rules["mandatory_services"] if s not in services]
        if missing:
            problems.append("Every visit needs " + ", ".join(label(s) for s in rules["mandatory_services"])
                            + ". Missing: " + ", ".join(label(s) for s in missing) + ".")
        line("mandatory", "Every visit: " + ", ".join(label(s) for s in rules["mandatory_services"]), n0,
             "All were done.", fail_detail="Missing: " + ", ".join(label(s) for s in missing) + ".", src=rules.get("mandatory_source"))
    n0 = len(problems)
    for s in TOOTH_SERVICES:
        bad = [n for n in teeth.get(s, []) if not valid_tooth(n)]
        if bad:
            problems.append(f"Tooth number {', '.join(map(str, bad))} is not a real tooth (FDI numbering).")
    line("tooth_numbers", "Tooth numbers are real teeth (FDI)", n0)
    yr = _year(chart["service_date"])
    same_year = [h for h in history if _year(h["service_date"]) == yr]
    visit = len(same_year) + 1
    max_visit = max((c["visit"] for c in rules["codes"]), default=None) if rules.get("codes") else None
    if max_visit is not None:
        n0 = len(problems)
        if visit > max_visit:
            problems.append(f"This is visit {visit} this year. The benefit codes cover {max_visit} visits a year.")
        line("visits", f"At most {max_visit} visits a year with a benefit code", n0, f"This is visit {visit} of {max_visit} this year.",
             src=rules.get("codes_source"))
    covered = {s: [n for n in teeth.get(s, []) if valid_tooth(n)] for s in TOOTH_SERVICES if teeth.get(s)}
    asked = {s: list(v) for s, v in covered.items()}

    def drop(s, ns):
        for n in ns:
            if n in covered.get(s, []):
                covered[s].remove(n)

    for rule in rules.get("age_limits", []):
        s, n0 = rule["service"], len(problems)
        used = s in services or bool(asked.get(s))
        if used and (age is None or not rule.get("min_age", 0) <= age <= rule.get("max_age", 200)):
            problems.append(NEED_BIRTH_DATE if age is None else f"Age {age} on the service date. {label(s).capitalize()} is covered for {_ages(rule)} only."
                            + (f" Not covered: {_teeth(asked[s])}." if asked.get(s) else ""))
            refused_services.append(s); covered.pop(s, None)
        note = f"Age {age} on the service date." if used and age is not None else None
        line("age:" + s, rule["title"], n0, note or ("" if used else "Not used in this visit."), na=not used, src=rule.get("source"), note=note)
    for rule in rules.get("eligible_teeth", []):
        s, n0 = rule["service"], len(problems)
        off = [n for n in asked.get(s, []) if n not in rule["teeth"]]
        if off:
            problems.append(f"{_teeth(off).capitalize()} {'is' if len(off) == 1 else 'are'} not an eligible tooth for {label(s)}. Not covered: {_teeth(off)}.")
            drop(s, off)
        line("teeth:" + s, rule["title"], n0, "Every tooth is on the list." if asked.get(s) else "Not used in this visit.", na=not asked.get(s), src=rule.get("source"))
    for rule in rules.get("tooth_windows", []):
        s, n0 = rule["service"], len(problems)
        start, again = months_before(day, rule["window_months"]), {}
        for h in history:
            hd = date.fromisoformat(h["service_date"])
            if start < hd <= day:
                for n in h.get("teeth", {}).get(s, []):
                    if n in asked.get(s, []):
                        again[n] = max(again.get(n, hd), hd)
        for n, hd in sorted(again.items()):
            problems.append(f"Tooth {n} already had {label(s)} on {_nice(hd)}, within the last {rule['window_months']} months. Not covered: tooth {n}.")
        drop(s, again)
        line("window:" + s, rule["title"], n0, f"No earlier {label(s)} on these teeth in the last {rule['window_months']} months." if asked.get(s) else "Not used in this visit.",
             na=not asked.get(s), src=rule.get("source"))
    teeth_left = None
    for cap in rules.get("tooth_caps", []):
        n0 = len(problems)
        used = sum(len(h.get("teeth", {}).get(s, [])) for h in same_year for s in cap["services"])
        left = max(cap["max_teeth_per_year"] - used, 0)
        asked_caps = [(s, n) for s in cap["services"] for n in covered.get(s, [])]
        if len(asked_caps) > left:
            dropped = asked_caps[left:]
            problems.append(f"{cap['reason']} {used} already used this year, {left} left. "
                            f"Not covered: tooth {', '.join(str(n) for _, n in dropped)}.")
            for s, n in dropped:
                covered[s].remove(n)
        teeth_left = left - min(len(asked_caps), left)
        line("cap:" + "+".join(cap["services"]), cap.get("title", cap["reason"]), n0,
             f"{used} of {cap['max_teeth_per_year']} used before this visit, {left} left.",
             fail_detail=f"{used} already used this year, {left} left. Not covered: tooth "
                         + ", ".join(str(n) for _, n in asked_caps[left:]) + "." if len(asked_caps) > left else None, src=cap.get("source"))
    for rule in rules.get("conditional_services", []):
        n0 = len(problems)
        if rule["service"] in services and not chart.get(rule["requires"]):
            problems.append(rule["reason"])
            covered.pop(rule["service"], None)
        line("conditional:" + rule["service"], rule.get("title", rule["reason"]), n0,
             "Pain emergency recorded." if rule["service"] in services else "Not used in this visit.",
             na=rule["service"] not in services, src=rule.get("source"))
    for rule in rules.get("frequency", []):
        s, n0, note = rule["service"], len(problems), None
        used = s in services
        band = _band(rule["bands"], age) if used else None
        if used and band is None and age is None:
            problems.append(NEED_BIRTH_DATE)
            refused_services.append(s)
        elif band:
            prior = sorted(date.fromisoformat(h["service_date"]) for h in history if s in h.get("services", []) and date.fromisoformat(h["service_date"]) <= day)
            recent = [d for d in prior if d > months_before(day, band["window_months"])]
            gap, why = band.get("min_days_apart"), []
            if len(recent) >= band["count"]:
                why.append(f"{len(recent)} in the last {band['window_months']} months (latest {_nice(recent[-1])}); {band['count']} allowed.")
            if gap and prior and (day - prior[-1]).days < gap:
                why.append(f"The last one was {(day - prior[-1]).days} days ago ({_nice(prior[-1])}); {gap} days apart are needed.")
            if why:
                problems.append(f"{label(s).capitalize()} is not covered" + (f" at age {age}" if age is not None and ("min_age" in band or "max_age" in band) else "") + ". " + " ".join(why))
                refused_services.append(s)
            note = (f"Age {age}: up to" if age is not None and ("min_age" in band or "max_age" in band) else "Up to") \
                + f" {band['count']} in {band['window_months']} months" + (f", {gap} days apart" if gap else "") \
                + (f". Last one {_nice(prior[-1])}, {(day - prior[-1]).days} days ago." if prior else ". None earlier.")
        line("frequency:" + s, rule["title"], n0, note or ("" if used else "Not used in this visit."), na=not used, src=rule.get("source"), note=note)
    n0 = len(problems)
    days = (date.fromisoformat(filing_date) - day).days
    late = days > rules["filing_deadline_days"]
    if late:
        problems.append(f"Claims must be filed within {rules['filing_deadline_days']} days of the service. This one is {days} days late to file.")
    line("deadline", f"Filed within {rules['filing_deadline_days']} days of the service", n0,
         "Filed on the day of the service." if days == 0 else f"{days} days after the service.",
         fail_detail=f"{days} days after the service.", src=rules.get("filing_deadline_source"))
    for rule in rules.get("not_in_this_file", []):
        lines.append({"id": "none:" + rule["id"], "title": rule["title"], "ok": True, "na": True, "detail": "No rule in this file.",
                      "note": "No rule in this file.", "source": None})
    unruled_teeth = {s: covered.pop(s) for s in TOOTH_SERVICES if s in unruled and covered.get(s)}
    n_teeth = sum(len(covered.get(s, [])) for cap in rules.get("tooth_caps", []) for s in cap["services"])
    blocking = bool(missing) or (max_visit is not None and visit > max_visit) or late or any(
        not chart.get(r["field"]) for r in rules.get("eligibility", []))
    refused_teeth = {s: [n for n in teeth.get(s, []) if n not in covered.get(s, [])] for s in TOOTH_SERVICES
                     if s not in unruled and any(n not in covered.get(s, []) for n in teeth.get(s, []))}
    procedures = []
    for s in list(chart.get("services", [])) + [s for s in TOOTH_SERVICES if teeth.get(s) and s not in services]:
        tooth = s in TOOTH_SERVICES
        state = "no_rule" if s in unruled else "refused" if s in refused_services or (tooth and teeth.get(s) and not covered.get(s)) else "covered"
        procedures.append({"service": s, "label": label(s), "state": state, "tooth": tooth, "asked": list(teeth.get(s, [])), "teeth": list(covered.get(s, []))})
    if rules.get("codes"):
        code = next((c["code"] for c in rules["codes"] if c["visit"] == visit and c["teeth_min"] <= n_teeth <= c["teeth_max"]), None)
        claimable = not blocking and code is not None
    else:
        code, claimable = None, not blocking and any(p["state"] == "covered" for p in procedures)
    return {"code": None if blocking else code, "claimable": claimable, "visit": visit, "age": age,
            "problems": problems, "covered_teeth": {s: v for s, v in covered.items() if v},
            "left": {"teeth": teeth_left, "visits": max(max_visit - visit, 0) if max_visit is not None else None}, "lines": lines,
            "refused_teeth": refused_teeth, "unruled_teeth": unruled_teeth, "procedures": procedures}
