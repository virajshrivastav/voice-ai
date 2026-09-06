# voice-ai

Cloned-voice, two-way constituent outreach calls for MLAs/MPs (Marathi/Hindi) — spec, evidence, compliance kit and staged build plan.

**Status:** pre-build (2026-09-06). Nothing confirmed with any client; target is a ₹0 demo path first.

| Doc | What it is |
|---|---|
| [docs/00_CONTEXT.md](docs/00_CONTEXT.md) | Requirement, market evidence, vendor comparison, ₹5/min cost model, latency, architecture, legal map, staged plan, decisions |
| [docs/01_EVIDENCE_CHECK.md](docs/01_EVIDENCE_CHECK.md) | 37 claims re-verified against primary sources; corrections applied |
| [docs/02_COMPLIANCE.md](docs/02_COMPLIANCE.md) | TRAI / ECI / IT Rules / DPDP checklist, consent template, retention defaults |
| [docs/03_CALL_SCRIPT.md](docs/03_CALL_SCRIPT.md) | Call script v0 — Marathi (production) + Hindi (test), state machine, answer schema |
| [docs/04_BUILD_PLAN.md](docs/04_BUILD_PLAN.md) | Stage 0 bake-off → Stage 1 browser demo → Stage 2 real number → Stage 3 pilot; repo layout; DoD |
| [docs/05_SOURCES.md](docs/05_SOURCES.md) | Every source URL |
| [CLAUDE.md](CLAUDE.md) | Rules for Claude Code working in this repo |
| [schema/answers.schema.json](schema/answers.schema.json) | Per-call structured output |

## TL;DR
1. Cloned political calls are a commodity in India (50M+ in 2024); the product is the two-way conversation + answer data.
2. Use the Indian stack: Sarvam (beats ElevenLabs at 8 kHz; ElevenLabs can't clone Marathi), Smallest/Cartesia as hedges, Exotel/Plivo, Bolna or Pipecat.
3. ₹5/min works only self-hosted (~₹2.5–3/min raw, ~₹2 with pre-rendered turns). Managed platforms are at/over ₹5.
4. Target "recognisable + natural on a phone line", not "exact"; Marathwada dialect is not reproducible today.
5. Indic telephony STT accuracy is the hidden risk.
6. Non-negotiable: verbal AI disclosure, consented voices only, DLT sender + 140-series, DPDP notice, ECI labelling/MCMC in election periods.
7. Four cheap stages; don't quote before Stage 2.

## Next actions
See `docs/04_BUILD_PLAN.md` → Stage 0. Needs: own-voice samples (Hindi + Marathi), Sarvam + Smallest (+ Cartesia) API keys in `.env`.
