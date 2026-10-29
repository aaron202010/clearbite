"""Screen recording of the replay demo at 1440x900: visit 4, the check, approve and file, then the payer and patient swap.
Needs the replay server on :8096. Writes video/raw/screen.webm and video/raw/marks.json (seconds of each step)."""
import json, os, time
from playwright.sync_api import sync_playwright
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw")
marks, t0 = {}, None
mark = lambda k: marks.__setitem__(k, round(time.time() - t0, 2))
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, record_video_dir=OUT, record_video_size={"width": 1440, "height": 900})
    pg = ctx.new_page(); t0 = time.time()
    pg.goto("http://127.0.0.1:8096/"); pg.wait_for_timeout(2500); mark("start")
    pg.locator("#saved .vbtn").nth(3).click(); mark("visit"); pg.wait_for_timeout(9000)
    mark("checked"); pg.wait_for_timeout(4000)
    pg.locator("#approve").click(); mark("approve"); pg.wait_for_timeout(1200)
    pg.evaluate("document.querySelector('.band') && document.querySelector('.band').scrollIntoView({behavior:'smooth'})")
    pg.locator("#band-status", has_text="Filed and read back").wait_for(timeout=120000); mark("filed"); pg.wait_for_timeout(3500)
    pg.evaluate("window.scrollTo({top:0,behavior:'smooth'})"); pg.wait_for_timeout(1500)
    pg.get_by_role("button", name="Washington Apple Health (Medicaid)").click(); mark("wa_adult"); pg.wait_for_timeout(6000)
    pg.get_by_role("button", name="Ana").click(); mark("wa_child"); pg.wait_for_timeout(6000); mark("end")
    vid = pg.video.path(); ctx.close(); b.close()
os.replace(vid, os.path.join(OUT, "screen.webm")); json.dump(marks, open(os.path.join(OUT, "marks.json"), "w"), indent=1); print(marks)
