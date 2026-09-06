# Build Plan — stages, deliverables, order of work

Principle: **prove the voice on a phone line before writing product code**; keep every stage cheap; nothing is quoted to a client before Stage 2 exists.

## Stage 0 — Voice bake-off (≈ ₹0, 2–3 days)
**Question answered:** is a Marathi clone acceptable to local listeners at telephone quality, and which vendor is best?

Inputs
- `samples/viraj_hi_clean.wav`, `samples/viraj_mr_clean.wav` (3 min each, phone recorder, quiet room)
- `samples/viraj_mr_phone.wav` (30 s recorded through an actual phone call)
- API keys in `.env` (Sarvam, Smallest; Cartesia optional — Pro plan needed for cloning)
- Sentence set: the 6 Marathi + 6 Hindi fixed turns from `03_CALL_SCRIPT.md`

Steps (`stage0/bakeoff.py`)
1. Create clone per vendor (Sarvam: after enterprise access is granted; Smallest: `POST /waves/v1/lightning-v3.1/add_voice`; Cartesia: `POST /voices/clone`).
2. Synthesise the sentence set per vendor at native rate; measure TTFB and total latency from an Indian VM (Mumbai region).
3. Degrade to telephony: `ffmpeg -i in.wav -ar 8000 -ac 1 -c:a pcm_mulaw tmp.wav && ffmpeg -i tmp.wav -ar 16000 out.wav`.
4. Build blind-test pack: randomised file names, include the real recording as control, `scoring_sheet.csv` with columns `file,sounds_like_him(1-5),natural(1-5),understandable(1-5),comment`.
5. 5–10 raters from Chhatrapati Sambhajinagar rate on their own phones (WhatsApp delivery is realistic).
6. `stage0/report.py` → mean ± sd per vendor per language, latency table, cost per 1k chars. Decision rule: proceed with the vendor whose telephony "sounds_like_him" ≥ 3.5 and "understandable" ≥ 4; otherwise stop and rethink.

## Stage 1 — Browser demo (₹0, ~1 week)
**Question answered:** does the two-way conversation work end-to-end in Marathi/Hindi with acceptable latency?

- Pipecat + `SmallWebRTCTransport` (no telephony). Sarvam STT (streaming, `mr-IN`/`hi-IN`) → state machine + Sarvam-30B for classification → Bulbul v3 clone TTS; fallback TTS provider switch by config.
- Implement `03_CALL_SCRIPT.md` as a state machine (`OPEN → Q1 → Q2 → Q3 → Q4 → CLOSE`, `OPTOUT` reachable from every state, `SILENCE` handling).
- Pre-render cache: at startup, synthesise all fixed turns for the configured `voice_id`, store `cache/{voice_id}/{sha1(text)}.wav`; play from cache.
- Answer schema → `schema/answers.schema.json`; every completed session writes one JSON record.
- Measure per-turn latency (STT final → first audio byte) and log it.

## Stage 2 — Real phone number (≈ ₹200–700, ~1 week)
**Question answered:** does it survive real Indian mobile networks and real Marathi speakers?

- Option A: **Bolna self-hosted** (docker-compose) with Plivo or Exotel provider; import the agent config (per-language STT/TTS, Sarvam). Option B: Pipecat + Plivo/Exotel media-streams transport.
- Plivo: $10 trial credit, Indian number ₹200/month, ₹0.38/min with 30-s pulse. Exotel: 7-day trial, ₹500 credit.
- 30–50 calls to friends/family who pre-consented. Log pickup rate, duration, per-turn latency, STT WER on a hand-transcribed subset, cost per minute.
- Deliverable: a 90-second demo recording + a one-page metrics sheet. **This is the sales asset.**

## Stage 3 — Pilot with an MLA (paid; after approval)
- MLA signs `02_COMPLIANCE.md §3` consent → Sarvam enterprise clone.
- MLA office registers on DLT; 140-series number; telco written OK for AI outreach; enterprise Exotel/Plivo account (100+ concurrency).
- Governance-outreach campaign: 5,000 numbers from a lawful list; dialling window 10:00–19:00; dashboard.
- Pricing: setup fee + ₹5/min connected. Cost target ≤ ₹3/min.
- Exit criteria: pickup ≥ 40%, completion ≥ 60% of connected, grievance list delivered, no complaints escalated.

## Suggested repo layout
```
voice-ai/
  CLAUDE.md                 # rules for Claude Code
  docs/                     # this handoff
  schema/answers.schema.json
  stage0/  bakeoff.py  report.py  sentences.json
  stage1/  bot.py  state_machine.py  prerender.py  web/
  stage2/  bolna/docker-compose.yml  agent.json  | pipecat_telephony/
  campaign/ ingest.py (voter CSV → Postgres)  dnd_check.py  dialer.py  dashboard/
  .env.example  .gitignore
```

## Definition of done for the MVP (end of Stage 2)
- One command starts the bot; one command places a call to a number in a CSV with per-voter context.
- Disclosure turn plays from cache in < 50 ms after answer; median turn latency < 1.2 s on Jio/Airtel.
- Every call produces: recording, transcript, answers JSON matching schema, audit log row.
- Opt-out works mid-sentence (barge-in) and persists.
- Cost per connected minute computed automatically from vendor usage logs.

## Open decisions (owner: Viraj)
1. Lawful source of the voter list for the pilot.
2. Commercial model: free demo → paid pilot (recommended) vs paid from day one.
3. Whether the first pilot is governance outreach (recommended) or campaign.
4. Vendor for clone after Stage 0 results.
