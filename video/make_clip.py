"""The ~80 s demo clip: hook cards with the Ava narrator (the Front Desk video's voice), the founder's own dictation take,
the replay screen recording cut at its step marks, captions burned in, end card. Output video/clip.mp4 (1280x720)."""
import json, os, subprocess, textwrap
from PIL import Image, ImageDraw, ImageFont
V = os.path.dirname(os.path.abspath(__file__)); B = f"{V}/build"; R = f"{V}/raw"
FONTS = "/root/hackathon-frontdesk-meta/video/fonts"; BOLD, REG = f"{FONTS}/Inter-Bold.ttf", f"{FONTS}/Inter-Regular.ttf"
TAKE = "/root/.claude/jobs/af61474e/tmp/dentist-take/take1.mp4"   # the founder's own recording, visit 4 is 42.0 to 54.0 s
TEAL, INK, MUTED, BG = "#0e6a75", "#17242b", "#5c6e77", "#f4f6f7"
LINES = {
  "n1": "Oral disease affects nearly 3.7 billion people.",
  "n2": "The Philippines has 2.6 dentists for every 10,000 people.",
  "n3": "PhilHealth now covers dental checkups. But every claim has rules: three services each visit, two sealed teeth a year, filed within sixty days. Miss one, and the claim doesn't qualify.",
  "n4": "Muse Voice turns the dentist's words into text. Muse Spark turns the text into a dental chart.",
  "n5": "The rules engine checks the claim. One sealant is already used this year, so teeth 26 and 36 come off before anything is filed.",
  "n6": "The dentist approves. A Muse Spark computer-use agent fills the claim on a sample portal, then every field is read back.",
  "n7": "The rules live in a file. Switch to Washington State Medicaid, and this adult gets no sealants.",
  "n8": "A twelve-year-old gets all three.",
  "n9": "Chairside Claim. Claims checked before they're filed.",
}
SAY = dict(LINES, n1="Oral disease affects nearly three point seven billion people.", n2="The Philippines has two point six dentists for every ten thousand people.",
           n5="The rules engine checks the claim. One sealant is already used this year, so teeth twenty-six and thirty-six come off before anything is filed.")
run = lambda *a: subprocess.run(list(a), check=True, capture_output=True)
dur = lambda f: float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", f], capture_output=True, text=True).stdout)
os.makedirs(B, exist_ok=True)
for k, t in SAY.items():
    if not os.path.exists(f"{B}/{k}.mp3"):
        run("uvx", "edge-tts", "--voice", "en-US-AvaNeural", "--text", t, "--write-media", f"{B}/{k}.mp3")

def card(name, title, sub=None, source=None):
    im = Image.new("RGB", (1280, 720), BG); d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 1280, 8), fill=TEAL)
    y = 250 if sub else 300
    for ln in textwrap.wrap(title, 30):
        f = ImageFont.truetype(BOLD, 58); d.text((110, y), ln, font=f, fill=INK); y += 74
    if sub:
        y += 14
        for ln in textwrap.wrap(sub, 52):
            d.text((110, y), ln, font=ImageFont.truetype(REG, 32), fill=MUTED); y += 44
    if source:
        d.text((110, 640), source, font=ImageFont.truetype(REG, 22), fill=MUTED)
    im.save(f"{B}/{name}.png")

card("c1", "Oral disease affects nearly 3.7 billion people.", source="WHO oral health fact sheet, 17 March 2025")
card("c2", "2.6 dentists for every 10,000 people in the Philippines.", source="WHO oral health country profile, Philippines, 2020 data")
card("c3", "PhilHealth covers dental checkups. Every claim has rules.", "Exam, cleaning and fluoride every visit. Sealants: two teeth a year. File within 60 days.",
     source="PhilHealth Circular 2024-0034")
card("c9", "Chairside Claim", "Dental claims checked before they're filed. Built on Meta's Muse Voice and Muse Spark.")

def caption_file(k, text):
    p = f"{B}/{k}.txt"; open(p, "w").write("\n".join(textwrap.wrap(text, 62))); return p
CAP = lambda k, text: (f"drawtext=fontfile={REG}:textfile={caption_file(k, text)}:fontsize=27:fontcolor=white:line_spacing=8:"
                       f"box=1:boxcolor=black@0.62:boxborderw=14:x=(w-text_w)/2:y=h-text_h-46")
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "aac", "-ar", "48000", "-ac", "2"]
segs = []

def still(k, img, audio, pad=0.7):
    out = f"{B}/s_{k}.mp4"; d = dur(audio) + pad
    run("ffmpeg", "-y", "-loop", "1", "-t", f"{d}", "-i", img, "-i", audio, "-filter_complex",
        f"[0:v]scale=1280:720,format=yuv420p[v];[1:a]apad=whole_dur={d}[a]", "-map", "[v]", "-map", "[a]", "-t", f"{d}", *ENC, out); segs.append(out)

def screen(k, start, end, audio, text, crop=None):
    out = f"{B}/s_{k}.mp4"; clip = end - start; need = dur(audio) + 0.5; d = max(clip, need)
    run("ffmpeg", "-y", "-ss", f"{start}", "-t", f"{clip}", "-i", f"{R}/screen.webm", "-i", audio, "-filter_complex",
        f"[0:v]{(f'crop={crop[2]}:{crop[3]}:{crop[0]}:{crop[1]},scale=1280:720,') if crop else 'scale=1152:720,pad=1280:720:64:0:color=0xf4f6f7,'}tpad=stop_mode=clone:stop_duration={max(0, d - clip) + 0.1},{CAP(k, text)},format=yuv420p[v];"
        f"[1:a]apad=whole_dur={d}[a]", "-map", "[v]", "-map", "[a]", "-t", f"{d}", *ENC, out); segs.append(out)

still("1", f"{B}/c1.png", f"{B}/n1.mp3"); still("2", f"{B}/c2.png", f"{B}/n2.mp3"); still("3", f"{B}/c3.png", f"{B}/n3.mp3", 0.9)
# the founder's own take, visit 4, his voice, labelled
tk = f"{B}/s_take.mp4"
open(f"{B}/take_label.txt", "w").write("Founder playing the dentist")
open(f"{B}/take_cap.txt", "w").write("\"Exam, prophy, fluoride varnish. Sealant on 16, 26 and 36.\"")
run("ffmpeg", "-y", "-ss", "42.0", "-t", "11.2", "-i", TAKE, "-filter_complex",
    f"[0:v]scale=1280:720,drawtext=fontfile={BOLD}:textfile={B}/take_label.txt:fontsize=26:fontcolor=white:box=1:boxcolor=0x0e6a75@0.92:boxborderw=12:x=40:y=36,"
    f"drawtext=fontfile={REG}:textfile={B}/take_cap.txt:fontsize=27:fontcolor=white:box=1:boxcolor=black@0.62:boxborderw=14:x=(w-text_w)/2:y=h-text_h-46,format=yuv420p[v];"
    f"[0:a]aresample=48000,loudnorm=I=-16:TP=-1.5[a]", "-map", "[v]", "-map", "[a]", *ENC, tk); segs.append(tk)
m = json.load(open(f"{R}/marks.json"))
screen("4", m["visit"], m["checked"], f"{B}/n4.mp3", LINES["n4"], (170, 135, 960, 540))
screen("5", m["checked"], m["approve"], f"{B}/n5.mp3", LINES["n5"], (330, 135, 1104, 621))
screen("6", m["approve"], m["filed"] + 3.0, f"{B}/n6.mp3", LINES["n6"] + " (Replayed from a recorded live run.)")
screen("7", m["wa_adult"] + 1.4, m["wa_child"], f"{B}/n7.mp3", LINES["n7"], (330, 135, 1104, 621))
screen("8", m["wa_child"] + 1.2, m["end"], f"{B}/n8.mp3", LINES["n8"], (330, 135, 1104, 621))
still("9", f"{B}/c9.png", f"{B}/n9.mp3", 1.6)
lst = f"{B}/list.txt"; open(lst, "w").write("".join(f"file '{s}'\n" for s in segs))
run("ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
    "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", f"{V}/clip.mp4")
print("clip", round(dur(f"{V}/clip.mp4"), 1), "s")
