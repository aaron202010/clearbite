"""The screen in headless Chromium (Playwright) against this app on a local port: replay mode with live voice on, a fake microphone
fed by a generated tone, and every answer to a recording or a filing mocked in the browser, so Meta is never called. Covers what
the server tests cannot: where a message lands on a phone, what is locked while recording, keyboard focus in the tooth menu."""
import math, socket, struct, threading, time, wave
import pytest
import uvicorn

sync_api = pytest.importorskip("playwright.sync_api")
from app import main

PHONE = dict(viewport={"width": 360, "height": 800}, is_mobile=True, has_touch=True, permissions=["microphone"])
LAPTOP = dict(viewport={"width": 1366, "height": 768}, permissions=["microphone"])
IN_VIEW = "(s) => { const r = document.querySelector(s).getBoundingClientRect(); return r.height > 0 && r.top >= 0 && r.bottom <= innerHeight; }"
JSON = "application/json"


@pytest.fixture(scope="module")
def base():
    mp = pytest.MonkeyPatch()
    mp.setenv("CLAIM_REPLAY", "1"); mp.setenv("CLAIM_REPLAY_DELAY", "0"); mp.setenv("CLAIM_LIVE_VOICE", "1")
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True); t.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True; t.join(5); mp.undo()


@pytest.fixture(scope="module")
def browser(tmp_path_factory):
    wav = tmp_path_factory.mktemp("mic") / "tone.wav"   # a plain tone, never a person's voice
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / 16000))) for i in range(16000 * 3)))
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", f"--use-file-for-fake-audio-capture={wav}"])
        except Exception as e:   # no Chromium on this machine
            pytest.skip(f"Chromium cannot start: {type(e).__name__}")
        yield b
        b.close()


def open_page(browser, base, size, recording=None, filing=None):
    page = browser.new_context(**size).new_page()
    if recording:   # only a recording is answered by the mock; saved visits and checks reach the local app
        page.route("**/visit", lambda r: recording(r) if "multipart" in (r.request.headers.get("content-type") or "") else r.continue_())
    if filing:
        page.route("**/file", filing)
    page.goto(base, wait_until="networkidle")
    return page


def record_and_stop(page):
    page.click("#rec"); page.wait_for_function("() => document.querySelector('#rec').classList.contains('recording')")
    time.sleep(1.2); page.click("#rec")
    page.wait_for_function("() => !document.querySelector('#rec').disabled && !document.querySelector('#rec').classList.contains('recording')"
                           " && !/^Listening/.test(document.querySelector('#heard').textContent)")


def play_saved_visit_4(page):
    page.locator(".vbtn").nth(3).click()
    page.wait_for_function("() => !document.querySelector('#approve').disabled")


def test_a_failed_recording_says_why_next_to_the_record_button_on_a_phone(browser, base):
    page = open_page(browser, base, PHONE, recording=lambda r: r.fulfill(status=422, content_type=JSON, body='{"detail": "No speech was heard in that recording."}'))
    record_and_stop(page)
    assert "No speech was heard in that recording." in page.inner_text("#rec-hint")
    assert page.evaluate(IN_VIEW, "#rec-hint") and page.inner_text("#rec-label") == "Record your own visit"


def test_a_dropped_connection_is_said_in_plain_words(browser, base):
    page = open_page(browser, base, PHONE, recording=lambda r: r.abort("connectionreset"))
    record_and_stop(page)
    for where in ("#err", "#rec-hint"):
        text = page.inner_text(where)
        assert "Failed to fetch" not in text and "connection dropped" in text, (where, text)


def test_a_filing_that_cannot_start_says_why_under_the_approve_button(browser, base):
    page = open_page(browser, base, PHONE, filing=lambda r: r.fulfill(status=409, content_type=JSON, body='{"detail": "A filing is already running."}'))
    play_saved_visit_4(page)
    page.click("#approve"); page.wait_for_function("() => !document.querySelector('#approve').disabled")
    hint = page.locator("#approve-hint")
    assert "A filing is already running." in hint.inner_text() and "bad" in hint.get_attribute("class")


def test_approve_and_the_tooth_menu_are_locked_while_recording(browser, base):
    page = open_page(browser, base, LAPTOP, recording=lambda r: r.fulfill(status=422, content_type=JSON, body='{"detail": "No speech was heard in that recording."}'))
    play_saved_visit_4(page)
    page.click("#rec"); page.wait_for_function("() => document.querySelector('#rec').classList.contains('recording')")
    assert page.is_disabled("#approve")
    page.locator('#chart .tooth[data-n="21"]').dispatch_event("click")
    assert page.locator("#tmenu").count() == 0
    page.click("#rec")
    page.wait_for_function("() => !document.querySelector('#rec').disabled && !document.querySelector('#rec').classList.contains('recording')")


def test_escape_and_a_keyboard_pick_keep_focus_on_the_tooth(browser, base):
    page = open_page(browser, base, LAPTOP)
    play_saved_visit_4(page)
    focused = "() => document.activeElement && document.activeElement.getAttribute('data-n')"
    page.locator('#chart .tooth[data-n="21"]').focus(); page.keyboard.press("Enter")
    assert page.locator("#tmenu").count() == 1
    page.keyboard.press("Escape")
    assert page.locator("#tmenu").count() == 0 and page.evaluate(focused) == "21"
    page.keyboard.press("Enter"); page.keyboard.press("Tab"); page.keyboard.press("Enter")   # the second item: Class V
    page.wait_for_function("() => /21/.test(document.querySelector('#tlist').innerText) && !document.querySelector('.vbtn').disabled")
    assert page.evaluate(focused) == "21"


def test_the_record_button_is_on_the_first_screen_of_a_laptop(browser, base):
    """At 1366 x 768 the record card sat under the patient card, below the fold: a first-time visitor saw no way to start."""
    page = open_page(browser, base, LAPTOP)
    assert page.evaluate(IN_VIEW, "#rec") and page.evaluate(IN_VIEW, "#sample")


def test_a_visit_on_a_phone_brings_what_was_heard_into_view(browser, base):
    """On a phone the result cards sit a screen below the buttons; a visit now scrolls the transcript into view."""
    page = open_page(browser, base, PHONE)
    page.click("#sample")
    page.wait_for_function("() => !document.querySelector('.vbtn').disabled && document.querySelector('#ck-body .pill')")
    time.sleep(0.8)   # the smooth scroll settles
    assert page.evaluate(IN_VIEW, "#hd-title")
