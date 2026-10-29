"""The filing agent: Muse Spark (computer use) fills one claim on the local sample portal through the observe-act loop
(dev.meta.ai/docs/computer-use, read 2026-10-29). Playwright is the driver: it runs each action and sends back a viewport
screenshot. After the model says it is done, the harness reads window.lastClaim and compares every field with the claim
it was given. Moved here from spikes/wonder_spike.py on day 2; the spike imports this module.

Safety-check policy (unchanged from the spike): a safety check is acknowledged only on the local sample portal page
(file:// URL of spikes/portal/index.html) and only when every action in the turn is a plain input action. Every
acknowledged check is logged with its actions. Anything else stops the run."""
import base64, io, json, os, re, time
import httpx
from PIL import Image
from app import meta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PORTAL = os.path.join(ROOT, "spikes", "portal", "index.html")
PORTAL_URL = "file://" + PORTAL
OUT = os.path.join(ROOT, "spikes", "out")
RECORDED = os.path.join(OUT, "wonder_spike_muse-spark-1.3.json")   # the saved computer-use run, replayed by replay_claim
MODEL = "muse-spark-1.3"   # muse-wonder-1.0 rejects the computer tool on this key
SAFE_ACTIONS = {"click", "double_click", "move", "type", "keypress", "scroll", "wait", "screenshot"}
W, H, MAX_STEPS = 1280, 800, 40
SYSTEM = """You are a computer-use agent operating a browser. You receive screenshots and choose the next action or actions.
Coordinates are pixels in the screenshot you were last shown: (0, 0) is the top-left. Click the center of the target element.
Return a short batch of actions only when they do not depend on intermediate visual feedback, such as click, type, and keypress.
Do not batch across page loads, modal transitions, or any step where the next action depends on a new screenshot.
Finish by replying with a normal message when the goal is visibly complete, or a short explanation when the task is infeasible.
Do not guess hidden UI state and do not claim completion unless the screenshot supports it."""
KEYS = {"ctrl": "Control", "control": "Control", "cmd": "Meta", "meta": "Meta", "super": "Meta", "alt": "Alt", "option": "Alt",
        "shift": "Shift", "enter": "Enter", "return": "Enter", "tab": "Tab", "esc": "Escape", "escape": "Escape",
        "backspace": "Backspace", "delete": "Delete", "del": "Delete", "space": "Space", "up": "ArrowUp", "down": "ArrowDown",
        "left": "ArrowLeft", "right": "ArrowRight", "arrowup": "ArrowUp", "arrowdown": "ArrowDown", "arrowleft": "ArrowLeft",
        "arrowright": "ArrowRight", "pageup": "PageUp", "pagedown": "PageDown", "home": "Home", "end": "End"}
# Portal wording for each service checkbox, in the order the portal lists them.
SERVICE_LABELS = {"oral_exam": "Oral exam", "prophylaxis": "Prophylaxis", "fluoride_varnish": "Fluoride varnish",
                  "sealant": "Pit and fissure sealant", "class_v": "Class V", "extraction": "Emergency extraction"}
FIELDS = [("patient", "Patient name"), ("pin", "Member PIN"), ("kpp", "Konsulta provider"), ("date", "Date of service"),
          ("visit", "Visit this year"), ("code", "Benefit code"), ("services", "Services done"), ("teeth", "Teeth"),
          ("dentist", "Dentist PRC license no.")]


def task_text(claim):
    """The instruction given to the agent. For the claim of the saved run it is word for word the day 1 task."""
    done = [SERVICE_LABELS[s] for s in SERVICE_LABELS if s in claim["services"]]
    teeth = claim.get("teeth") or "(none: leave empty)"
    return ("Fill in and submit the new claim on this page with exactly these values, then stop when the page shows 'Claim received'.\n"
            f"Patient name: {claim['patient']}\nMember PIN: {claim['pin']}\nKonsulta provider: {claim['kpp']}\n"
            f"Date of service: {claim['date']}\nVisit this year: {ordinal(claim['visit'])} visit\nBenefit code: {claim['code']}\n"
            f"Services done: {', '.join(done)} (leave the others unchecked)\n"
            f"Teeth: {teeth}\nDentist PRC license no.: {claim['dentist']}")


def ordinal(n):
    return {"1": "1st", "2": "2nd"}.get(str(n), f"{n}th")


# ---------- read-back ----------

def _norm(field, v):
    if field == "services":
        return sorted(v or [])
    if field == "teeth":
        return sorted(int(t) for t in re.findall(r"\d+", str(v or "")))
    return str(v or "").strip()


def _show(field, v):
    if field == "services":
        return ", ".join(SERVICE_LABELS.get(s, s) for s in SERVICE_LABELS if s in (v or []))
    if field == "visit":
        return (ordinal(v) + " visit") if str(v or "").strip() else ""
    return str(v or "").strip()


def readback(claim, got):
    """Compare every field the portal holds (window.lastClaim) with the claim that was given. got may be None."""
    rows = []
    for f, label in FIELDS:
        have = (got or {}).get(f)
        rows.append({"field": f, "label": label, "want": _show(f, claim.get(f)), "got": _show(f, have) if got else "",
                     "ok": got is not None and _norm(f, claim.get(f)) == _norm(f, have)})
    return rows


# ---------- helpers ----------

def small_jpeg(png_bytes, width=960, quality=70):
    """Step screenshots go to the screen as small base64 JPEGs."""
    im = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=quality, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def describe(a):
    t = a.get("type")
    if t == "type": return 'type "' + (a["text"] if len(a["text"]) <= 30 else a["text"][:29] + "…") + '"'
    if t == "keypress": return "press " + "+".join(a.get("keys", []))
    if t == "scroll": return "scroll"
    return {"click": "click", "double_click": "double-click", "move": "move", "wait": "wait", "screenshot": "look", "drag": "drag"}.get(t, str(t))


def summarize(actions):
    """One line for the screen: the first few actions in words, then how many more."""
    parts = [describe(a) for a in actions]
    if not parts:
        return "look at the page"
    line = ", ".join(parts[:3])
    return line + (f" and {len(parts) - 3} more" if len(parts) > 3 else "")


# ---------- the live loop ----------

def shot(page):
    return "data:image/png;base64," + base64.b64encode(page.screenshot()).decode()


def execute(page, actions, log):
    for a in actions:
        t = a.get("type"); log.append(a)
        if t == "click": page.mouse.click(a["x"], a["y"], button={"wheel": "middle"}.get(a.get("button", "left"), a.get("button", "left")) if a.get("button", "left") in ("left", "right", "wheel") else "left")
        elif t == "double_click": page.mouse.dblclick(a["x"], a["y"])
        elif t == "move": page.mouse.move(a["x"], a["y"])
        elif t == "type": page.keyboard.type(a["text"], delay=15)
        elif t == "keypress": page.keyboard.press("+".join(KEYS.get(k.lower(), k if len(k) > 1 else k.lower()) for k in a["keys"]))
        elif t == "scroll": page.mouse.move(a["x"], a["y"]); page.mouse.wheel(a.get("scroll_x", 0), a.get("scroll_y", 0))
        elif t == "drag":
            pts = a["path"]; page.mouse.move(pts[0]["x"], pts[0]["y"]); page.mouse.down()
            for p in pts[1:]: page.mouse.move(p["x"], p["y"])
            page.mouse.up()
        elif t in ("wait", "screenshot"): pass
        time.sleep(0.25 if t != "wait" else 1.0)


def review(page, c, acked, ack_local):
    """A safety check is a decision point. Without ack_local the run stops. With it, a check is acknowledged only on the
    local sample portal page and only for plain input actions; every acknowledged check is logged with its actions."""
    checks, acts = c["pending_safety_checks"], c.get("actions", [])
    for chk in checks: print(f"  safety check {chk.get('code')}: {chk.get('message')}")
    ok = ack_local and (page.url == PORTAL_URL or page.url.startswith(PORTAL_URL + "#") or page.url.startswith(PORTAL_URL + "?")) \
        and all(a.get("type") in SAFE_ACTIONS for a in acts)
    if ok: acked.append({"checks": checks, "actions": acts})
    return ok


class ModelError(RuntimeError):
    """A model-service failure. The text is safe to show: an HTTP status or an exception name, never a body or a header."""


def call(body, tries=3):
    """POST to the model service. A rate limit, a server error or a dropped connection is retried twice after a short wait:
    each request branches from the same previous_response_id, so a retry cannot repeat anything the browser already did."""
    last = "The model service did not answer."
    for i in range(tries):
        try:
            r = httpx.post(meta.BASE + "/responses", headers={"Authorization": "Bearer " + meta.key()}, json=body, timeout=180)
        except httpx.HTTPError as e:
            last = f"The model service did not answer ({type(e).__name__})."
        else:
            if r.status_code < 400:
                return r.json()
            last = f"The model service answered HTTP {r.status_code}."
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        if i < tries - 1:
            time.sleep(4 * (i + 1))
    raise ModelError(last)


def file_claim(claim, emit=None, model=MODEL, ack_local=True, stop=None, save_dir=None, max_steps=MAX_STEPS):
    """Fill `claim` on the sample portal. emit(kind, data) gets {"n", "action", "image", "acknowledged"} after every turn.
    ack_local=True means the caller reviewed the safety-check policy above for the local demo portal (the dentist's tap on
    Approve in the app, the --ack-local flag in the spike). save_dir: also write wonder_step*.png and wonder_final.png.
    Returns the full result (used by the spike's JSON file); the app sends a trimmed copy of it."""
    from playwright.sync_api import sync_playwright
    emit = emit or (lambda kind, data: None)
    log, acked, t0, final, stopped, steps = [], [], time.time(), None, None, 0
    with sync_playwright() as p:
        b = p.chromium.launch(); page = b.new_page(viewport={"width": W, "height": H})
        page.goto(PORTAL_URL)
        resp = call({"model": model, "instructions": SYSTEM, "tools": [{"type": "computer"}],
                     "input": [{"role": "user", "content": [{"type": "input_text", "text": task_text(claim)}, {"type": "input_image", "image_url": shot(page)}]}]})
        for steps in range(1, max_steps + 1):
            if stop is not None and stop.is_set():
                final = stopped = "stopped: the screen was closed"; break
            calls = [o for o in resp.get("output", []) if o.get("type") == "computer_call"]
            if not calls:
                final = " ".join(c.get("text", "") for o in resp.get("output", []) if o.get("type") == "message" for c in o.get("content", []))
                break
            c = calls[0]
            ack = []
            if c.get("pending_safety_checks"):
                if not review(page, c, acked, ack_local):
                    final = stopped = "stopped: safety check " + json.dumps([k.get("code") for k in c["pending_safety_checks"]]); break
                ack = c["pending_safety_checks"]
            execute(page, c.get("actions", []), log)
            png = page.screenshot()
            if save_dir: open(os.path.join(save_dir, f"wonder_step{steps:02d}.png"), "wb").write(png)
            emit("step", {"n": steps, "action": summarize(c.get("actions", [])), "image": small_jpeg(png), "acknowledged": bool(ack)})
            resp = call({"model": model, "previous_response_id": resp["id"], "tools": [{"type": "computer"}],
                         "input": [{"type": "computer_call_output", "call_id": c["call_id"], "acknowledged_safety_checks": ack,
                                    "output": {"type": "computer_screenshot", "image_url": shot(page)}}]})
        got = page.evaluate("window.lastClaim || null"); png = page.screenshot()
        if save_dir: open(os.path.join(save_dir, "wonder_final.png"), "wb").write(png)
        b.close()
    rows = readback(claim, got)
    return {"model": model, "steps": steps, "seconds": round(time.time() - t0), "final": final, "stopped": stopped, "submitted": got,
            "readback": rows, "all_ok": all(r["ok"] for r in rows), "right": sum(r["ok"] for r in rows), "total": len(rows),
            "acknowledged": acked, "actions": log, "image": small_jpeg(png)}


# ---------- replay ----------

def recorded():
    return json.load(open(RECORDED))


def replay_matches(claim):
    """The saved run filed one claim. Replay can show it only for that same claim."""
    return all(r["ok"] for r in readback(claim, recorded()["submitted"]))


def replay_claim(claim, emit=None, delay=None, stop=None):
    """No network, no browser: replay the saved computer-use run step by step from its saved screenshots."""
    emit = emit or (lambda kind, data: None)
    rec = recorded()
    delay = float(os.environ.get("CLAIM_REPLAY_DELAY", "0.8")) if delay is None else delay
    for n, turn in enumerate(rec["acknowledged"], 1):
        if stop is not None and stop.is_set():
            break
        time.sleep(delay)
        emit("step", {"n": n, "action": summarize(turn["actions"]), "acknowledged": True,
                      "image": small_jpeg(open(os.path.join(OUT, f"wonder_step{n:02d}.png"), "rb").read())})
    time.sleep(delay)
    rows = readback(claim, rec["submitted"])
    return {"model": rec["model"], "steps": rec["steps"], "seconds": rec["seconds"], "final": rec["final"], "stopped": None,
            "submitted": rec["submitted"], "readback": rows, "all_ok": all(r["ok"] for r in rows),
            "right": sum(r["ok"] for r in rows), "total": len(rows), "acknowledged": rec["acknowledged"],
            "actions": [], "image": small_jpeg(open(os.path.join(OUT, "wonder_final.png"), "rb").read())}
