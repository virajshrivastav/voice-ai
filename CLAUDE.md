# CLAUDE.md — working rules for this repo

This repo is the working spec + build for a cloned-voice, two-way constituent-calling system
(Marathi/Hindi) for MLAs/MPs in Chhatrapati Sambhajinagar. Read in this order before doing anything:

1. `docs/00_CONTEXT.md` — requirement, evidence, cost model, architecture, decisions (start here)
2. `docs/01_EVIDENCE_CHECK.md` — which facts are verified, corrected, or unverified
3. `docs/02_COMPLIANCE.md` — hard rules baked into the product
4. `docs/03_CALL_SCRIPT.md` — the call as a state machine, Marathi + Hindi
5. `docs/04_BUILD_PLAN.md` — stages 0–3 and the build order
6. `docs/05_SOURCES.md`

## Non-negotiable rules (do not implement anything that violates these)
- Every call opens with the verbal AI disclosure from `03_CALL_SCRIPT.md`. It is never skippable or shortened.
- Only voices with a signed + recorded consent (`02_COMPLIANCE.md §3`) are cloned. **No public figures, no third parties, no test exceptions.**
- Opt-out ("नाही/नहीं/no/stop") ends the call and persists the number to the opt-out list.
- The LLM only classifies answers and picks whitelisted acknowledgements. It never generates promises, policy statements, or attacks.
- Secrets live in `.env` (see `.env.example`); never commit them.

## Engineering defaults
- Python 3.11+, `uv` for deps. Orchestrator: Pipecat (Stage 1) → Bolna self-hosted or Pipecat telephony (Stage 2). Do not write a custom orchestrator.
- Primary vendors: Sarvam (STT/LLM/TTS clone), Smallest.ai and Cartesia as TTS fallbacks, Plivo or Exotel for PSTN.
- Pre-render all fixed turns per voice; cache key = `(voice_id, sha1(text), format)`.
- Every session writes an answers record matching `schema/answers.schema.json` plus an audit row (disclosure timestamp, consent ref, DND check, opt-out).
- Measure and log per-turn latency; report p50/p95.
- Useful agent skills: `github.com/bolna-ai/skills` (MIT) and `github.com/sarvamai/skills` (Apache-2.0) are Claude-Code-compatible skill packs for Bolna and Sarvam APIs.

## Status (2026-09-06)
Pre-build. Nothing confirmed with any client. Pending: Viraj's own voice sample (Hindi + Marathi), Sarvam/Smallest/Cartesia API keys, the original PRD (not authoritative). Next: Stage 0 bake-off.
