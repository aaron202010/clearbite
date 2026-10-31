# Clearbite: YouTube and submission text (drafted 2026-10-30)

Film: video/clearbite-v16.mp4 (1:58, 1920x1080)

## YouTube title
Clearbite: dental claims checked before they're filed

## YouTube description
Clearbite catches the rule a dental claim would fail on, before it is filed. It listens to the dentist, writes the dental chart and checks it against the payer's own cited rules: a missing required service blocks the claim, a tooth over the yearly limit comes off it. The dentist approves, then an agent files the claim, and the app reads every field back from the portal.

Built with Meta models:
1. Muse Voice Transcribe: the dentist's words to text.
2. Muse Spark: the text to a dental chart, with structured output.
3. Muse Spark computer use: fills the claim on a sample portal from screenshots; the app then reads each field back.

The decision is not made by a model. A rules engine reads one payer's rules from a file, and each rule cites its source. The film shows two payers: PhilHealth in the Philippines, and Washington Apple Health (Medicaid).

What is real and what is a demo:
1. The filing in the film is a replay of a recorded live run on a local sample portal, not PhilHealth's site. On the demo page, speech to text, the chart and the rules check run live on your own recording; the filing stays a replay.
2. The voice is Aaron, the founder, reading a dentist's dictation.
3. All patient data is sample data.
4. In five timed live runs, four filed every field right. Run 5 left a word out of the patient's name, and the read back caught it.
5. 173 tests pass (143 when the film was made). Before the first release, Codex reviewed the rules engine and Kimi K3 reviewed the filing agent.

Live demo: https://claim.aaroncabantugan.com (record your own visit, up to 5 an hour: live speech to text, chart and rules check; the filing replays a recorded live run; or play a saved visit)
Code (MIT): https://github.com/aaron202010/clearbite

Built during the Meta Global AI Developer Hackathon, October 26 to November 4, 2026.

## Submission form text (map to the form's fields)
Project name: Clearbite

Track: Startup

One line: Clearbite catches the rule a dental claim would fail on, before it is filed.

What it does:
Clearbite's job is to stop a claim that would fail, before it is filed. A dentist talks while working. Clearbite turns the words into a dental chart and checks it against the payer's own rules, each rule cited to its source (a PhilHealth circular, a Washington WAC section). If a required service is missing, like fluoride varnish at a PhilHealth visit, it blocks the claim and says why. A tooth over the yearly sealant limit comes off the claim. Only then, with the dentist's tap, an agent files it on the portal, and the app reads every field back from the portal to check the agent's work. The rules engine decides, not the model. Each payer's rules live in a file, not in the code; adding Washington took one rules file plus five generic rule kinds the engine now reads.

How it uses Meta's models:
1. Muse Voice Transcribe (muse-voice-transcribe-1.0): speech to text, in English or Tagalog, with dental terms biased.
2. Muse Spark (muse-spark-1.3) with structured output: the text becomes a fixed JSON chart (services, FDI tooth numbers).
3. Muse Spark computer use: it fills the claim on a sample portal from screenshots, and every field is read back.

Why it matters:
Claims fail on rules the dentist can't keep in their head. PhilHealth covers 113.86 million Filipinos, but only 1,482 dentists are accredited to claim its benefits, about 1 in 19 of the country's 28,154 dentists (our math across PhilHealth's Stats and Charts 2025 and WHO's 2020 count).

What is real:
The film's filing is a replay of a recorded live run on a local sample portal, not PhilHealth's site. The voice is the founder reading a dentist's dictation. Sample data only. Five timed live runs: four filed every field right, and the read back caught the fifth. 173 tests pass.

Links:
Demo: https://claim.aaroncabantugan.com (live recording, or a saved visit)
Code: https://github.com/aaron202010/clearbite
Video: <YouTube link after upload>
