# Cloned-Voice Constituent Calling — Project Context & Handoff

**Prepared by:** Viktor (AI) for Viraj Shrivastav · **Date:** 2026-09-06 · **Status:** pre-build, nothing confirmed, zero budget
**Purpose of this file:** single source of truth for continuing this work in Claude Code. It replaces the PRD as the working spec until the PRD is rewritten. Everything marked `[unverified]` must be checked before relying on it. Every fact with a price or benchmark was read from a live web page on 2026-09-05/06 and re-checked on 2026-09-06 — see `01_EVIDENCE_CHECK.md` for the claim-by-claim result; sources are in `05_SOURCES.md`. Script → `03_CALL_SCRIPT.md`; compliance → `02_COMPLIANCE.md`; build order → `04_BUILD_PLAN.md`.

---

## 0. TL;DR (read this if nothing else)

1. **The idea is viable, and it is not novel.** 50M+ AI voice-cloned political calls were made in India before the 2024 Lok Sabha polls. Two-way AI survey bots for elections already exist (Edesy, VoxBharat). The moat is *not* the voice — it is the two-way conversation, the structured answer data, and Viraj's access to MLAs/MPs in Chhatrapati Sambhajinagar.
2. **Use the Indian stack.** On 8 kHz telephony, Sarvam Bulbul v3 beats ElevenLabs in blind tests; ElevenLabs cannot clone into Marathi at all. Recommended: Sarvam (STT + LLM + TTS/clone) as primary, Smallest.ai and Cartesia as hedges; Exotel or Plivo for telephony; Bolna (MIT) or Pipecat (BSD) as orchestrator — do **not** write an orchestrator from scratch.
3. **₹5 per minute is achievable only if we self-host the orchestration.** Raw cost ≈ ₹2.5–3/min live, ~₹2/min with pre-rendered scripted turns. Every managed platform (Bolna cloud, Smallest Atoms, Vapi, Retell, ElevenLabs Agents) is at or above ₹5/min → no margin.
4. **"Exactly cloned" is the wrong target.** Target: *recognisably him, natural, in standard Marathi, on a phone line*. Marathwada dialect is not reproducible by any vendor today. Only a blind test with local listeners can tell us if standard Marathi is acceptable.
5. **The hidden technical risk is STT, not TTS.** Indic telephonic speech recognition has WER of 5–21% (Sarvam) to 29–68% (Deepgram). Bad STT → wrong "responses" in the politician's voice + garbage insights.
6. **Hard rules, non-negotiable:** verbal AI disclosure at the start of every call; consent recording from the politician before cloning; DLT-registered sender + 140-series number; DPDP notice; during any election period, ECI labelling + MCMC pre-certification of scripted content. No cloning of non-consenting or public figures (Modi test was declined — see §9).
7. **Plan:** four cheap stages. Stage 0–1 cost ≈ ₹0 (Cartesia cloning needs its Pro plan, ~$5/mo `[unverified]` — optional), Stage 2 < ₹1,000, Stage 3 only after an MLA approves and pays.

---

## 1. Requirement (as stated by Viraj, normalised)

- Build an **orchestrator** so politicians/government officials under Viraj's management can call voters **in their own cloned voice**, in a natural two-way phone conversation: greet, ask questions, record answers, respond contextually — "a simple real call".
- **Inputs:** voter list upload + per-voter specific information (used to personalise the call).
- **Outputs:** call recordings, transcripts, structured answers stored in a backend for later insights.
- **Priorities (his words):** (1) voice must be "exactly" cloned — the #1 thing; (2) latency minimal; (3) cost ≈ **₹5 per minute of conversation** (clarified from "per call").
- **Context:** claims the project would be "government approved" via his network. **Callout:** no such approval exists today, and no approval waives TRAI/ECI/DPDP obligations — treat this as a sales channel, not a compliance shortcut.
- **His answers to my clarifying questions (2026-09-05/06):**
  - Lane: **both** campaigning and governance outreach → *start with governance outreach* (lighter rulebook; next Maharashtra assembly election expected Nov 2029 — local-body election dates for Sambhajinagar to be checked).
  - Language: **Marathi** (Hindi for the first test).
  - Pricing unit: **₹5 per minute of conversation**.
  - Scale: one assembly constituency ≈ **3–4 lakh voters**; concurrency unknown.
  - DLT sender / number owner: **MLA's office, if and when approved by the MLA**.
  - Client: **ruling-party MPs/MLAs in Chhatrapati Sambhajinagar**. Commercial terms not decided; nothing confirmed; must be runnable cheaply/free for now.
  - Voice sample: offered Narendra Modi audio "for testing" → **declined** (§9). Asked Viraj to record his own voice instead.
  - PRD: exists, self-described as "poorly made"; never reached me (Teams channel attachments are invisible to bots). Do not treat it as authoritative.

---

## 2. What the market looks like (evidence)

| Fact | Source |
|---|---|
| 50M+ AI voice-clone calls made in India in the 2 months before 2024 LS polls; iToConnect alone ~25M calls in 2 weeks; audio clone of a politician priced ~₹60,000 | WIRED / Indian Express / Rest of World, 2024 |
| Two-way AI election survey bots exist: Edesy (edesy.in), VoxBharat (voxbharat.ai); Gnani.ai ran citizen surveys for Swachh Bharat | vendor sites |
| Indian AI-call agencies quote **₹0.50/call for one-way blasts** (DigiBrood, Campaign Mitra) — this is the price anchor MLAs already know. Two-way conversation must be sold as a different product | vendor sites |
| Voters: AI *audio* rated more trustworthy than AI video/images (AMCIS 2025); rural voters felt honoured receiving "personal" calls from leaders (WIRED 2024) → disclosure costs little | research |
| Sarvam selected by IndiaAI Mission (Apr 2025) to build the sovereign LLM — politically convenient vendor choice for a "government" project | Indian Express, PIB |

**Implication:** the clone + blast is a commodity. Sell the *conversation + data*, not the voice.

---

## 3. Voice quality & cloning — vendor comparison

| Vendor | Marathi TTS | Cloning | Cloning access | Telephony quality evidence | Price |
|---|---|---|---|---|---|
| **Sarvam Bulbul v3** | Yes (11 Indic langs, 35+ voices) | Yes, consent-based, 30–60 s sample | **Enterprise-gated** — must email Sarvam; price `[unverified]` | Josh Talks blind eval (44k votes, 11 langs): at 8 kHz Bulbul wins 60% vs ElevenLabs v3, 58% vs Cartesia Sonic-3, 90%+ vs others. Caller Digital Marathi MOS 4.2 vs ElevenLabs 3.9 | ₹30 / 10k chars (v2: ₹15). **₹1,000 free credits on signup** |
| **Smallest.ai Lightning v3.1** | Yes (12 Indian langs; 9 Marathi voices) | Instant, 5–15 s sample, **self-serve API** | Open (ToS: consent required) | Sub-100 ms TTFA; less independent Marathi data | ~$14.5 / 1M chars (Pro $19.5). Free tier `[unverified]` |
| **Cartesia Sonic-3** | Marathi listed in earlier search `[confirm on signup]` | Instant, 10 s sample | Instant Voice Clone requires **Pro plan or above** (docs, verified); Pro Voice Clone (30 min audio, 1M credits) needs Startup plan; free tier 20k credits/mo without cloning | Sub-90 ms; loses to Bulbul at 8 kHz in Josh Talks eval | ~1 credit/char; Agents $0.06/min |
| **ElevenLabs** | **No Marathi cloning** (PVC Indic = Hindi, Tamil only) | PVC needs 30 min–3 h clean audio, Creator+ plan, identity verification | "No-go voices" blocks public figures; account bans | Wins at full-band (59% vs Bulbul 41%) but **drops 19 pts at 8 kHz** | Agents ~$0.08/min + LLM + telephony ≈ ₹15+/call |
| Open source (Chatterbox etc.) | Hindi yes; Marathi `[unverified]` | Zero-shot | Free, self-hosted GPU | Unbenchmarked for Marathi telephony | GPU cost only |

**Key nuances:**
- Clone from **phone-quality recordings of the politician speaking Marathi**. A clone built from English/Hindi speech carries that accent into Marathi (ElevenLabs docs; same physics for all vendors).
- No vendor produces Marathwada dialect. Clone speaks standard Marathi. Accept or reject via local-listener test (Stage 0).
- **Speech-to-speech models (OpenAI Realtime, Gemini Live) do not support cloned voices** → cascaded STT → LLM → TTS is mandatory. That sets the latency floor (§5).

---

## 4. Cost model — ₹5/min

Assumptions: 2-min connected call, agent speaks ~55% of the time (~900–1,000 Devanagari chars/call), 1 USD = ₹84.

| Component | Vendor / rate | ₹ per minute |
|---|---|---|
| Telephony (outbound PSTN) | Plivo Voice API India ₹0.38/min, **30-second pulse** (SIP trunking route is ₹0.60/min); Exotel ~₹0.50/pulse `[volume rate unverified]` | 0.40–0.50 |
| STT | Sarvam Saarika ₹30/hour | 0.50 |
| TTS (live) | Sarvam Bulbul v3 ₹30/10k chars (~500 chars/min) | 1.50 |
| TTS (live, alt) | Smallest v3.1 ~$14.5/1M chars | 0.60 |
| LLM | Sarvam-30B ₹2.5 in / ₹10 out per 1M tokens (pricing page also says "free per token") — negligible; Gemini Flash-Lite ~₹0.05/min | ~0.05 |
| Orchestrator hosting | one small VM + Postgres, amortised | 0.10–0.20 |
| **Total (Sarvam live)** | | **≈ 2.5–3.0** |
| **Total with pre-rendered scripted turns** (greeting, 4 questions, close synthesised once per politician; only clarifications live) | TTS −70% | **≈ 2.0** |

**Managed platforms for comparison (all-in per minute):** Bolna cloud ~₹5.5 · Smallest Atoms ~₹8 · Vapi ~₹6–8 · Retell ~₹6–9 · Bland ~₹9–12 · ElevenLabs Agents ~₹7 + LLM + telephony. → all at/over the ₹5 sell price. **Owning the orchestration layer is the business.**

**Scale check (one seat):** 3.5 lakh voters × ~45% pickup × 2 min ≈ **3 lakh minutes ≈ ₹15 lakh billed, ~₹8 lakh cost per full sweep**. Over 10 days ≈ 30k min/day ≈ **~100 concurrent lines** at peak hours → needs Exotel/Plivo *enterprise* account (Plivo self-serve caps at 50 concurrent). Sarvam Starter rate limit is 60 req/min → Pro (₹10,000) or enterprise needed at that stage.

**Things the ₹5 number hides:** unanswered attempts (telephony cost on ringing/failed calls), GST, average duration creep (a 4-min chat = ₹10 to the client), and the fact MLAs already see "₹0.50/call" one-way blasts.

---

## 5. Latency — what is real

- Cascaded pipeline on Indian networks: **600–1,000 ms mouth-to-ear** is a realistic production number (Twilio's own target 1,115 ms; Caller Digital India benchmarks). Sub-500 ms needs co-located inference in India + semantic endpointing.
- Endpointing is the biggest single lever: naive silence VAD waits 500–800 ms; semantic/ML endpointing 150–250 ms.
- Sarvam Bulbul v3 streaming TTFB < 250 ms; Cartesia/Smallest < 100 ms.
- **Pre-rendered turns play in single-digit ms** — the scripted parts of the call (most of it) should never hit TTS live. Cache keyed on `(voice_id, text, format)`.
- "Minimum latency" and "exact clone" pull against each other (§3 last bullet). Pre-rendering resolves most of the tension.

---

## 6. Recommended architecture

```
Voter CSV + per-voter context ──► Campaign DB (Postgres)
                                        │
                                        ▼
        Exotel / Plivo (PSTN, 140-series, DLT) ◄──► Orchestrator (Bolna self-hosted, or Pipecat)
                                                        │   ├─ STT: Sarvam Saarika (streaming, mr-IN / hi-IN)
                                                        │   ├─ LLM: Sarvam-30B (or Gemini Flash-Lite) — constrained by script state machine
                                                        │   ├─ TTS: Sarvam Bulbul v3 clone (fallback Smallest / Cartesia)
                                                        │   └─ Audio cache: pre-rendered scripted turns per politician
                                                        ▼
                     Recordings + transcripts + structured answers + consent/disclosure log ──► Insights dashboard
```

**Orchestrator choice:**
- **Bolna** (github.com/bolna-ai/bolna, MIT — verified via GitHub API 2026-09-06; 749★): Exotel + Plivo + Twilio built in; Sarvam/Smallest/Cartesia/ElevenLabs TTS; Sarvam/Deepgram STT; per-language STT/TTS config; Marathi (`mr`) supported. Fastest path to a real phone call in India. Their cloud is ~₹5.5/min — self-host.
- **Pipecat** (BSD-2-Clause — verified; 15k★): more flexible, better for the ₹0 browser demo (SmallWebRTCTransport = no telephony needed), Sarvam plugin exists. Choose Pipecat if Bolna's state-machine control is too weak; otherwise Bolna first.
- **LiveKit Agents**: heavier; only if we outgrow both.

**Conversation design principle:** it is a **state machine with an LLM inside**, not a free-form agent. Scripted turns are fixed text (pre-certifiable, pre-renderable). The LLM only (a) classifies the voter's answer into the schema, (b) generates short clarifications/acknowledgements from a whitelist of patterns. Never let the LLM make promises or policy statements in the politician's voice.

**Data model (minimum):** `campaign`, `politician(voice_id, consent_recording_url, consent_date)`, `voter(phone, name, ward, tags, dnd_checked_at, source)`, `call(attempt, status, duration, recording_url, disclosure_played_at)`, `turn(role, text, audio_cached, latency_ms)`, `answer(question_id, raw_text, category, sentiment)`, `optout(phone, at)`.

**Our actual build scope (3–4 weeks MVP):** voter-list ingest + per-voter prompt injection; conversation state machine + answer schema; pre-render pipeline + cache; consent/disclosure logging; opt-out handling; dashboard (answers by ward/question, grievance list, export). Everything else is off-the-shelf.

---

## 7. Legal / compliance map (India, as of 2026-09-06)

| Regime | What it requires of us | Status |
|---|---|---|
| **ECI advisory 24 Oct 2025** (builds on May 2024 + Jan 2025) | All AI/synthetic campaign content labelled "AI-generated" / "Digitally Enhanced" / "Synthetic Content"; for visual media the label must cover ≥10% of display area — for audio the equivalent is a clear verbal label; creating entity disclosed; internal records; 3-hour takedown on notice | Applies in election periods; we bake the verbal label into every call anyway |
| **ECI order 9 Oct 2025 / Sept 2026** | Bulk voice messages need **MCMC pre-certification**; banned in 48-h silence period; expenditure reporting | Applies to campaigning lane. Live LLM output can't be pre-certified → keep persuasive content scripted, dynamic content limited to clarifications/answer capture |
| **TRAI TCCCPR 2018 + 2nd Amendment (12 Feb 2025)** | Sender registered as Principal Entity on DLT with an access provider (Airtel/Jio/Vi); promotional voice only from **140-series**; DND/preference honoured; consent records; autodialer rules | Sender = **MLA's office** (decided, pending his approval). Registration 1–3 weeks. Note the "Government Voice Call" carve-out for genuine government service communication — governance lane may qualify; confirm with the telco |
| **MeitY IT Rules amendment (G.S.R. 120(E), in force 20 Feb 2026)** | Synthetic audio must be labelled + carry metadata; platforms must flag | Verbal disclosure + metadata in stored recordings |
| **DPDP Act 2023 + Rules (14 Nov 2025)** | Political parties are **not** "State" → full obligations: itemised notice, purpose limitation ("insights" must be a stated purpose), consent withdrawal, breach notification | Voter phone + per-voter info + recorded answers = personal data. Ask where the voter list comes from. **Aadhaar / welfare-scheme databases for profiling are unlawful** (Puttaswamy) |
| **BNS / RP Act** | Impersonation, undue influence | Consent recording from politician before any cloning |
| **Vendor ToS** | ElevenLabs no-go voices + bans; Sarvam consent-gated; Cartesia/Smallest consent clauses | Only consented, first-party voices |
| **Precedent** | NH "Biden" robocall: $6M FCC fine on consultant + $1M on telco; civil default judgment despite criminal acquittal | Exotel's ToS puts full legal-compliance liability on the customer and Exotel is an intermediary; whether a telco carries AI political traffic is decided per account — confirm in writing during DLT onboarding |

**Position I hold and recommend Viraj holds:** build only with the AI disclosure line, consented voices, and DLT sender. This is also commercially smart — it is what makes an MLA's office able to say yes.

---

## 8. Staged plan (cheap → paid)

### Stage 0 — Voice bake-off (₹0, this week)
Goal: settle "is the clone good enough on a phone line in Marathi?" with data.
1. Viraj records **himself**: 3 min Hindi + 3 min Marathi, phone voice recorder, quiet room, natural pace (read a news article). Also 30 s recorded *through a phone call* (WhatsApp/normal call) for the phone-quality variant.
2. Accounts in Viraj's name: Sarvam (₹1,000 free credits), Smallest.ai, Cartesia (Pro if needed for cloning). Email Sarvam for clone access — script in §11.
3. Clone on each vendor; synthesise the same 6 Marathi + 6 Hindi sentences (from §10 script) per vendor.
4. Degrade all outputs to telephony: `ffmpeg -i in.wav -ar 8000 -ac 1 -acodec pcm_mulaw out.wav` (+ optionally G.711 → back to 16k to simulate the line).
5. Blind test: 5–10 people from Sambhajinagar rate 1–5 on "sounds like him", "natural", "understandable"; randomised order; include the real recording as control. Report mean scores per vendor.
6. Also measure TTFB per vendor from a Mumbai/Indian VM.

### Stage 1 — Browser demo (₹0)
Pipecat + `SmallWebRTCTransport` + Sarvam STT/LLM/TTS, running locally or on a free-tier VM. Full two-way conversation implementing the §10 state machine. This is the thing to show people.

### Stage 2 — One real phone number (~₹200–700)
Plivo ($10 trial credit; Indian number ₹200/month) or Exotel (7-day trial, ₹500 credit). Bolna self-hosted or Pipecat + telephony transport. 30–50 calls to friends/family who agreed in advance. Measure pickup, duration, latency, STT accuracy on real Marathi answers, cost per minute. **Only now quote anything to anyone.**

### Stage 3 — Pilot (after MLA approval; funded by the pilot)
DLT registration by MLA's office → 140-series number → enterprise Exotel/Plivo account → consented MLA clone (Sarvam enterprise) → 5,000-call governance-outreach pilot at ₹5/min + setup fee → dashboard delivered → decide on scale.

---

## 9. Decisions & callouts already made

- **Modi voice test — declined.** Non-consented public-figure clone; exactly the case ECI/IT Rules/vendor ToS target; risks account bans; and it proves nothing about an MLA with only phone recordings. Use Viraj's own voice, then the MLA's consented sample.
- **"Government approved" ≠ compliance.** No approval waives TRAI DLT, ECI labelling, or DPDP. Treat the network as distribution.
- **"Exact clone" → "recognisable + natural on a phone line".** Standard Marathi, not Marathwada dialect. Local-listener test decides.
- **Do not build an orchestrator.** Self-host Bolna/Pipecat. Our code is the campaign layer.
- **Governance lane first**, campaigning later (needs MCMC workflow).
- **Do not quote before Stage 2 exists.**
- **PRD is not authoritative** — rewrite it from this file after Stage 0 results.

---

## 10. Call script v0

Moved to `03_CALL_SCRIPT.md`.

---

## 11. Immediate to-dos

**Viraj**
- [ ] Record own voice: 3 min Hindi + 3 min Marathi (clean) + 30 s via phone call. Share via 1:1 or repo.
- [ ] Create Sarvam, Smallest.ai, Cartesia accounts in own name; put keys in `.env` (never commit).
- [ ] Email Sarvam (via sarvam.ai contact / API dashboard) for voice-clone access: *"Building a consent-based constituent-outreach voice agent in Marathi for an MLA's office in Maharashtra; need Bulbul v3 voice cloning API access for one consented speaker for a pilot; expected volume 3 lakh minutes/quarter. Please share clone pricing and onboarding."*
- [ ] Get a Marathi-speaking friend from Sambhajinagar to review §10 script.
- [ ] Decide: is the first deliverable a paid pilot (setup fee + ₹5/min) or a free demo to win the MLA? Recommend: free Stage 0–2 demo, paid from Stage 3.

**Claude Code (build order)**
- [ ] `stage0/bakeoff.py`: clone + synthesise sentence set on each vendor → 8 kHz degrade → randomised blind-test folder + scoring sheet (CSV) + TTFB log.
- [ ] `stage1/`: Pipecat SmallWebRTC bot with Sarvam STT/LLM/TTS, §10 state machine, answer schema JSON, pre-render cache.
- [ ] `stage2/`: Bolna self-host (docker-compose) + Plivo/Exotel outbound; or Pipecat telephony transport. Call log → Postgres.
- [ ] `docs/COMPLIANCE.md`: disclosure text, consent template for politician, DPDP notice text, DLT checklist, opt-out handling.
- [ ] Rewrite PRD from this file after Stage 0 numbers exist.

**Open questions**
- Source of the voter list + per-voter info (DPDP legality hinges on this).
- Exotel per-pulse rate at volume; Sarvam clone pricing; Smallest free tier; Cartesia cloning plan tier. `[all unverified]`
- Whether governance-lane calls from an MLA's office qualify for TRAI's "Government Voice Call" category (ask the telco during DLT onboarding).
- Concurrency target and dialing window (e.g. 10:00–19:00 only) — drives telco plan.

---

## 12. Sources

Moved to `05_SOURCES.md`.
