# Clearbite

A dentist talks while working. The claim is checked against the insurer's rules and filed, after the dentist approves.

Live demo: https://claim.aaroncabantugan.com. Record your own visit and the speech to text, the chart and the rules check run live on Meta's models (5 recordings per visitor per hour). The saved visits and the filing are replays of recorded takes and a recorded live filing.

Built for the Meta model API hackathon (Startup track) on three Meta capabilities:

| Step | Meta model | What it does here |
|---|---|---|
| Speech to text | Muse Voice Transcribe (`muse-voice-transcribe-1.0`) | English or Tagalog dictation, with dental keywords biased |
| Text to chart | Muse Spark (`muse-spark-1.3`), structured output | Fills a fixed JSON chart: services done, FDI tooth numbers, emergency flag |
| Filing | Muse Spark computer use (the API's `computer` tool) | Fills the claim on a sample portal from screenshots, then every field is read back |

The decision is not made by a model. A rules engine (`app/rules.py`) reads one payer's rules from a file and returns the benefit code, each rule as pass or fail with its plain reason and its source, and what is left this year. No payer's rules live in the code: the engine reads rule kinds (required services, yearly tooth caps, visit codes, age limits, eligible teeth, frequency by age, filing deadline) and each payer is a rules file. Adding Washington took its rules file plus five new rule kinds in the engine; a payer whose rules fit these kinds needs only a file.

## Payers

- **PhilHealth** preventive oral health benefit, from PhilHealth's Tamang Sagot on Circular 2024-0034 (`rules/philhealth_oph.json`): exam, cleaning and fluoride every visit; sealant or Class V on at most two teeth a year; extraction only for severe pain; claims within 60 days; codes OPH01 to OPH02B.
- **Washington Apple Health (Medicaid)** dental rules from the Washington Administrative Code (`rules/wa_apple_health.json`): WAC 182-535-1082 (sealants for age 20 and younger, once per tooth in three years, listed molars only; cleaning and fluoride frequency by age), WAC 182-535-1080 (periodic exam), WAC 182-502-0150 (365-day filing).

The same dictated visit, sealants on teeth 16, 26 and 36, gives three answers: PhilHealth with one sealant already used this year covers tooth 16; Washington for a 40-year-old covers no sealants; Washington for a 12-year-old covers all three.

Where a rules file reads something the source does not say outright, the screen lists it under "Inferred by us".

## Run it

```
pip install -r requirements.txt
python3 -m playwright install chromium
CLAIM_REPLAY=1 python3 -m uvicorn app.main:app --port 8096    # replay: no network, recorded takes and a recorded live filing
MODEL_API_KEY=... python3 -m uvicorn app.main:app --port 8096  # live: real Meta calls
python3 -m pytest -q                                           # 173 tests
```

## How it was checked

- The founder's own recorded dictation: 50 of 50 chart fields right across five visits (`spikes/real_take.py`). Synthetic voices in English and Tagalog: 50 of 50 each (`spikes/voice_spike.py`).
- Live filing on the sample portal: five timed runs, four read back 9 of 9 fields; one typed the patient name without "(sample)" and the read-back caught it. Runs took 49 seconds to about 9 minutes.
- The screen never shows money; a test scans it, and a second test proves the scan fails on a sample with a peso amount.

## Safety and honesty

- Nothing is filed until the dentist taps Approve; the filing endpoint refuses a claim without that approval.
- The computer tool attaches a safety check to each action. The harness acknowledges it only on the local sample portal and only for plain clicks and typing, and logs every acknowledgement; anything else stops the run.
- The portal is a sample built for this demo. It is not PhilHealth's site and is not connected to PhilHealth or to Washington's Health Care Authority.
- The founder plays the dentist in the video and is not a dentist. Patients are samples.
- Muse Wonder answered "Unsupported tool type: 'computer'" on this API key, so Muse Spark runs the computer-use loop, as Meta's docs allow.

## Built during the hackathon

- All code, rules files, tests and the sample portal in this repo were written during the hackathon build window. The first commit is 2026-10-29 03:51 UTC; the git history shows the work day by day.
- Prior work, called out: the founder runs HeyDenta, a dental clinic system for the Philippines. No HeyDenta code, data, keys or prompts are in this repo. The tooth chart follows the same dental-chart conventions (FDI numbering, five-surface circles) but is written fresh here.
- The tooth pictures in `app/static/teeth/` are reused from the founder's HeyDenta app (prior work).
- The rules come from public sources, cited in each rules file: PhilHealth's Tamang Sagot on Circular 2024-0034 and the Washington Administrative Code.

## License

MIT for the code, see `LICENSE`. The tooth pictures in `app/static/teeth/` are not covered by it.

