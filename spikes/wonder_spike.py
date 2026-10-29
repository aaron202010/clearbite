"""Day 1 computer-use spike: Muse Wonder fills one claim on the sample portal through the observe-act loop
(dev.meta.ai/docs/computer-use, read 2026-10-29). Playwright is the driver: it runs each action and sends back a
viewport screenshot. Safety checks are never auto-acknowledged: the run stops and logs them. After the model says it is
done, the harness reads window.lastClaim and compares every field with the claim it was given.
Usage: python3 wonder_spike.py [model]   (default muse-wonder-1.0; muse-spark-1.3 runs the same loop cheaper)"""
import base64, json, os, sys, time
import httpx
from playwright.sync_api import sync_playwright
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from app import meta

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "out")
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
MODEL = ARGS[0] if ARGS else "muse-wonder-1.0"
ACK_LOCAL = "--ack-local" in sys.argv   # the developer reviewed the checks for the local sample portal; see review()
SAFE_ACTIONS = {"click", "double_click", "move", "type", "keypress", "scroll", "wait", "screenshot"}
W, H, MAX_STEPS = 1280, 800, 40
CLAIM = {"patient": "Juan Dela Cruz (sample)", "pin": "12-345678901-2", "kpp": "Sample Konsulta Clinic", "date": "2026-10-29",
         "visit": "2", "code": "OPH02A", "services": ["oral_exam", "prophylaxis", "fluoride_varnish", "sealant"], "teeth": "16",
         "dentist": "0123456"}
TASK = ("Fill in and submit the new claim on this page with exactly these values, then stop when the page shows 'Claim received'.\n"
        f"Patient name: {CLAIM['patient']}\nMember PIN: {CLAIM['pin']}\nKonsulta provider: {CLAIM['kpp']}\n"
        f"Date of service: {CLAIM['date']}\nVisit this year: 2nd visit\nBenefit code: {CLAIM['code']}\n"
        "Services done: Oral exam, Prophylaxis, Fluoride varnish, Pit and fissure sealant (leave the others unchecked)\n"
        f"Teeth: {CLAIM['teeth']}\nDentist PRC license no.: {CLAIM['dentist']}")
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


def review(page, c, acked):
    """A safety check is a decision point. Without --ack-local the run stops. With it, a check is acknowledged only on the
    local sample portal page and only for plain input actions; every acknowledged check is logged with its actions."""
    checks, acts = c["pending_safety_checks"], c.get("actions", [])
    for chk in checks: print(f"  safety check {chk.get('code')}: {chk.get('message')}")
    ok = ACK_LOCAL and page.url.startswith("file://" + HERE) and all(a.get("type") in SAFE_ACTIONS for a in acts)
    if ok: acked.append({"checks": checks, "actions": acts})
    return ok


def call(body):
    r = httpx.post(meta.BASE + "/responses", headers={"Authorization": "Bearer " + meta.key()}, json=body, timeout=180)
    if r.status_code >= 400: raise SystemExit(f"HTTP {r.status_code}: {r.text[:400]}")
    return r.json()


def main():
    log, acked, t0 = [], [], time.time()
    with sync_playwright() as p:
        b = p.chromium.launch(); page = b.new_page(viewport={"width": W, "height": H})
        page.goto("file://" + os.path.join(HERE, "portal", "index.html"))
        resp = call({"model": MODEL, "instructions": SYSTEM, "tools": [{"type": "computer"}],
                     "input": [{"role": "user", "content": [{"type": "input_text", "text": TASK}, {"type": "input_image", "image_url": shot(page)}]}]})
        final, steps = None, 0
        for steps in range(1, MAX_STEPS + 1):
            calls = [o for o in resp.get("output", []) if o.get("type") == "computer_call"]
            if not calls:
                final = " ".join(c.get("text", "") for o in resp.get("output", []) if o.get("type") == "message" for c in o.get("content", []))
                break
            c = calls[0]
            ack = []
            if c.get("pending_safety_checks"):
                if not review(page, c, acked):
                    final = "stopped: safety check " + json.dumps([k.get("code") for k in c["pending_safety_checks"]]); break
                ack = c["pending_safety_checks"]
            execute(page, c.get("actions", []), log)
            page.screenshot(path=os.path.join(OUT, f"wonder_step{steps:02d}.png"))
            resp = call({"model": MODEL, "previous_response_id": resp["id"], "tools": [{"type": "computer"}],
                         "input": [{"type": "computer_call_output", "call_id": c["call_id"], "acknowledged_safety_checks": ack,
                                    "output": {"type": "computer_screenshot", "image_url": shot(page)}}]})
        got = page.evaluate("window.lastClaim || null"); page.screenshot(path=os.path.join(OUT, "wonder_final.png")); b.close()
    fields = list(CLAIM)
    if got:
        got["services"] = sorted(got.get("services") or []); want = dict(CLAIM, services=sorted(CLAIM["services"]))
        bad = [f for f in fields if str(got.get(f, "")).strip() != str(want[f])]
    else:
        bad = fields
    json.dump({"model": MODEL, "steps": steps, "seconds": round(time.time() - t0), "final": final, "submitted": got,
               "wrong_fields": bad, "acknowledged": acked, "actions": log}, open(os.path.join(OUT, f"wonder_spike_{MODEL}.json"), "w"), indent=1)
    print(f"model {MODEL}: {steps} turns, {round(time.time() - t0)} s, {len(log)} actions, {len(acked)} safety checks acknowledged")
    print("model said:", (final or "")[:300])
    print(f"fields read back right: {len(fields) - len(bad)}/{len(fields)}", "wrong:", bad or "none", "=>", "PASS" if not bad else "FAIL")


main()
