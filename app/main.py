"""The dentist screen's server. GET / is the screen, POST /visit turns a visit (audio, text or a saved visit) into a chart and a
rule check, POST /file fills the approved claim on the sample portal and streams progress as Server-Sent Events.
Run: uvicorn app.main:app --port 8096    Replay (no network): CLAIM_REPLAY=1 uvicorn app.main:app --port 8096"""
import json, os, queue, tempfile, threading
from datetime import date
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from app import filer, meta, replay, rules

HERE = os.path.dirname(os.path.abspath(__file__))
PATIENTS = os.path.join(HERE, "..", "data", "patients.json")
R = rules.load()
MAX_AUDIO, MAX_TEXT = 10_000_000, 4000
FILING = threading.Lock()   # one filing at a time: it drives one browser
app = FastAPI(title="Chairside claim (demo)", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")), name="static")


def patient():
    return json.load(open(PATIENTS))[0]


def service_date():
    return os.environ.get("CLAIM_DATE") or (replay.DEMO_DATE if replay.on() else date.today().isoformat())


def bad(detail, status=400):
    raise HTTPException(status_code=status, detail=detail)


def valid_date(v):
    try:
        return date.fromisoformat(v).isoformat()
    except (TypeError, ValueError):
        bad("Dates must look like 2026-10-29.")


# ---------- chart: Meta's shape (service flags) <-> the checker's shape (service list) ----------

def normalize_chart(raw):
    """Trust boundary: the chart arrives from the model or from the browser. Keep only known keys with the right types."""
    if not isinstance(raw, dict) or not isinstance(raw.get("services"), dict) or not isinstance(raw.get("teeth"), dict):
        bad("The chart must have services and teeth.")
    teeth = {}
    for s in rules.TOOTH_SERVICES:
        vals = raw["teeth"].get(s, [])
        if not isinstance(vals, list) or not all(isinstance(n, int) and not isinstance(n, bool) and 10 < n < 90 for n in vals):
            bad(f"Teeth for {s} must be a list of two-digit tooth numbers.")
        teeth[s] = sorted(set(vals))
    return {"services": {s: raw["services"].get(s) is True for s in meta.SERVICES}, "teeth": teeth,
            "emergency_pain": raw.get("emergency_pain") is True}


def check_chart(chart, p, service_day):
    return {"service_date": service_day, "kpp_registered": p["kpp_registered"],
            "services": [s for s in meta.SERVICES if chart["services"][s]],
            "teeth": {s: v for s, v in chart["teeth"].items() if v}, "emergency_pain": chart["emergency_pain"]}


def build_claim(p, cc, res):
    """The claim as it goes on the portal: only what the checker covers."""
    covered = res["covered_teeth"]
    services = [s for s in meta.SERVICES if (s in cc["services"] and s not in rules.TOOTH_SERVICES)
                or (s in rules.TOOTH_SERVICES and covered.get(s))]
    teeth = sorted({n for v in covered.values() for n in v})
    return {"patient": p["name"], "pin": p["pin"], "kpp": p["kpp"], "date": cc["service_date"], "visit": str(res["visit"]),
            "code": res["code"], "services": services, "teeth": ", ".join(map(str, teeth)), "dentist": p["dentist_prc"]}


def file_blocked(claim):
    """Why this claim cannot be filed right now, or None."""
    if claim is None:
        return "The checker found no benefit code for this visit. Fix the problems listed, then file."
    if replay.on() and not filer.replay_matches(claim):
        return "Replay mode has one recorded filing: the claim from saved visit 2 or 4 (sealant on tooth 16, code OPH02A)."
    return None


def _list_of(ns):
    ns = [str(n) for n in ns]
    return ns[0] if len(ns) == 1 else ", ".join(ns[:-1]) + " and " + ns[-1]


def adjusted_summary(res):
    """One line for a claim the checker trimmed, built from the check data: how many teeth were asked, which are filed and
    which were left off by rule. None when no tooth was removed."""
    left_off = sorted({n for v in res["refused_teeth"].values() for n in v})
    if not left_off:
        return None
    filed = sorted({n for v in res["covered_teeth"].values() for n in v})
    asked = len(filed) + len(left_off)
    shown = f"{'tooth' if len(filed) == 1 else 'teeth'} {_list_of(filed)}" if filed else "none"
    return f"{asked} {'tooth' if asked == 1 else 'teeth'} asked: {shown} filed, {_list_of(left_off)} left off by rule"


def evaluate(chart, day, filing_day):
    p = patient(); cc = check_chart(chart, p, day)
    res = rules.check(cc, p["history"], R, filing_day)
    claim = build_claim(p, cc, res) if res["claimable"] else None
    return p, cc, res, claim


def visit_payload(heard, chart, source, day, filing_day):
    _, _, res, claim = evaluate(chart, day, filing_day)
    return {"source": source, "heard": heard, "chart": chart, "service_date": day, "filing_date": filing_day, "check": res,
            "inferred": [R[k].removeprefix("inferred: ") for k in ("year_note", "codes_note") if k in R],
            "summary": adjusted_summary(res) if res["claimable"] else None,
            "claim": claim, "file_blocked": file_blocked(claim), "replay": replay.on()}


# ---------- routes ----------

@app.get("/", response_class=HTMLResponse)
def screen():
    """The screen. In replay mode the page is served with the replay tag already showing."""
    html = open(os.path.join(HERE, "static", "index.html"), encoding="utf-8").read()
    if replay.on():
        html = html.replace('<body data-replay="0">', '<body data-replay="1">').replace('id="replay-tag" class="tag" hidden', 'id="replay-tag" class="tag"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/patient")
def get_patient():
    p = patient()
    return {"patient": {k: p[k] for k in ("name", "pin", "kpp", "kpp_registered", "dentist_name", "dentist_prc", "history")}, "replay": replay.on(),
            "service_date": service_date(), "benefit": R["benefit"], "payer": R["payer"], "source": R["source"],
            "saved_visits": list(replay.visits())}


def _meta_failed(e):
    print("meta call failed:", type(e).__name__, flush=True)   # the type only: never the request, the headers or the key
    bad("The speech or chart service did not answer. Try again in a moment.", 502)


def run_visit(kind, value):
    """Blocking part of POST /visit: one saved visit id, some text, or an audio file path -> (heard, chart, source)."""
    if kind == "saved":
        v = replay.visits().get(value) or bad("Unknown saved visit.", 404)
        if replay.on():
            return v["heard"], v["chart"], "saved"
        try:
            return v["heard"], meta.chart_from_text(v["heard"]), "saved"
        except Exception as e:
            _meta_failed(e)
    if replay.on():
        saved = replay.by_text(value) if kind == "text" else None
        if saved:
            return saved["heard"], saved["chart"], "text"
        bad("Replay mode answers only the five saved visits. Play one of them.", 409)
    try:
        heard = value if kind == "text" else meta.transcribe(value)
        if not heard.strip():
            bad("No speech was heard in that recording.", 422)
        return heard, meta.chart_from_text(heard), kind
    except HTTPException:
        raise
    except Exception as e:
        _meta_failed(e)


@app.post("/visit")
async def post_visit(request: Request):
    ctype = request.headers.get("content-type", "")
    tmp = None
    try:
        if ctype.startswith("multipart/form-data"):
            up = (await request.form()).get("audio")
            if up is None or not hasattr(up, "read"):
                bad("Send the recording in a form field named audio.")
            data = await up.read(MAX_AUDIO + 1)
            if not data:
                bad("The recording is empty.")
            if len(data) > MAX_AUDIO:
                bad("The recording is too large.", 413)
            if replay.on():
                bad("Replay mode has no live recording. Play one of the five saved visits.", 409)
            tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "visit.audio"); open(path, "wb").write(data)
            kind, value, body = "audio", path, {}
        else:
            try:
                body = await request.json()
            except ValueError:
                bad("Send JSON like {\"text\": \"...\"} or a recording.")
            if not isinstance(body, dict):
                bad("Send JSON like {\"text\": \"...\"} or a recording.")
            if body.get("visit_id") is not None:
                kind, value = "saved", str(body["visit_id"])
            elif isinstance(body.get("text"), str) and body["text"].strip():
                if len(body["text"]) > MAX_TEXT:
                    bad("That text is too long.", 413)
                kind, value = "text", body["text"].strip()
            else:
                bad("Send text, a visit_id or a recording.")
        day = valid_date(body.get("service_date") or service_date()); filing_day = valid_date(body.get("filing_date") or day)
        heard, chart, source = await run_in_threadpool(run_visit, kind, value)
        return visit_payload(heard, normalize_chart(chart), source, day, filing_day)
    finally:
        if tmp:
            for f in os.listdir(tmp): os.remove(os.path.join(tmp, f))
            os.rmdir(tmp)


def sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def stream_filing(claim):
    """Run the filing in its own thread (Playwright must stay on one thread) and return a generator that relays its events.
    The thread starts here, not on the first read, so the lock is always released even if the browser leaves at once."""
    q, stop = queue.Queue(), threading.Event()

    def work():
        try:
            q.put(("start", {"claim": claim, "replay": replay.on(), "model": filer.MODEL}))
            res = (filer.replay_claim if replay.on() else filer.file_claim)(claim, lambda k, d: q.put((k, d)), stop=stop)
            q.put(("done", {**{k: res[k] for k in ("model", "steps", "seconds", "final", "stopped", "readback", "all_ok", "right", "total", "image")},
                            "acknowledged": len(res["acknowledged"]), "replay": replay.on()}))
        except Exception as e:
            print("filing failed:", type(e).__name__, str(e)[:200], flush=True)
            why = str(e) if isinstance(e, filer.ModelError) else "The filing agent stopped before it finished."
            q.put(("error", {"message": why + " Nothing was sent anywhere. Try again."}))
        finally:
            q.put(None); FILING.release()

    def events():
        try:
            while True:
                try:
                    item = q.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"; continue
                if item is None:
                    break
                yield sse(*item)
        finally:
            stop.set()

    threading.Thread(target=work, daemon=True).start()
    return events()


@app.post("/file")
async def post_file(request: Request):
    """Starts the computer-use filing. Refused (400) unless the body carries approved=true, which the screen sends only after the
    dentist taps Approve. The claim is rebuilt here from the chart: the browser never supplies the benefit code."""
    try:
        body = await request.json()
    except ValueError:
        bad("Send JSON with approved and chart.")
    if not isinstance(body, dict) or body.get("approved") is not True:
        bad("The dentist must approve the claim before it is filed.")
    day = valid_date(body.get("service_date") or service_date()); filing_day = valid_date(body.get("filing_date") or day)
    _, _, _, claim = evaluate(normalize_chart(body.get("chart")), day, filing_day)
    blocked = file_blocked(claim)
    if blocked:
        bad(blocked, 409 if claim else 400)
    if not FILING.acquire(blocking=False):
        bad("A filing is already running.", 409)
    return StreamingResponse(stream_filing(claim), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
