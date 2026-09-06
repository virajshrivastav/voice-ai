# CLAUDE.md — working rules for this repo

This repo is the working spec + build for a cloned-voice, two-way constituent-calling
system (Marathi/Hindi) for MLAs/MPs in Chhatrapati Sambhajinagar. Read in this order:

1. `docs/00_CONTEXT.md` — requirement, evidence, cost model, architecture, decisions
2. `docs/06_CORRECTIONS.md` — **what changed after re-verification and after building it**
3. `docs/02_COMPLIANCE.md` — hard rules baked into the product
4. `docs/03_CALL_SCRIPT.md` — the call as a state machine, Marathi + Hindi
5. `docs/04_BUILD_PLAN.md` — stages 0–3
6. `docs/01_EVIDENCE_CHECK.md`, `docs/05_SOURCES.md`

## Non-negotiable rules (do not implement anything that violates these)
- Every call opens with the verbal AI disclosure. Never skippable, never shortened.
- Only voices with a signed + recorded consent (`02_COMPLIANCE.md §3`) are cloned.
  **No public figures, no third parties, no test exceptions.**
- **The agent may only ever say text a human approved.** Fixed turns come from
  `data/script.<lang>.yaml`; replies come from `data/answer_bank.<lang>.yaml`; the one
  runtime-built string is the clarification template, whose slot is filled from a
  `short:` field. `SpeechGuard.assert_speakable()` is the last call before TTS and must
  stay there.
- The LLM classifies and picks ids. It never generates speech. If it returns an id that
  is not in the bank, that resolves to `None` and the call falls back to approved text.
- Opt-out ends the call and persists the number. See the note below before touching it.
- Secrets live in `.env`; never commit them.

## Traps this codebase already fell into
- **Opt-out is not a substring match.** `नाही`/`नहीं` is how these languages negate a
  verb, so `"पाणी रोज येत नाही"` — a voter answering the water question — matches. Use
  `IntentMatcher`: phrases anywhere, bare negations only when the utterance is nothing
  else. `tests/test_script.py` locks this down. `02_COMPLIANCE.md §1.3` still has the
  wrong wording.
- **Answer-bank ordering.** Control statements ("wrong number") always, the bank on
  interrogatives, then classification, then the bank as a fallback. Both naive orders
  are broken — see `06_CORRECTIONS.md` B2.
- **Never infer an unasked field.** Q2 fills both `roads` and `lights`; if roads could
  not be classified, lights is `unanswered`, not `ok`.
- **Judge voices at 8 kHz only.** Rankings invert between full-band and telephony.
  `audio.degrade_to_telephony` exists for this; `--skip-degrade` warns for a reason.
- **Windows console is cp1252.** Call `voiceai.console.setup()` at the top of every
  entry point or the first Devanagari `print()` raises.
- **`uv pip install` needs `--native-tls`** on this machine (TLS interception).
- **The opt-out ledger is keyed on phone alone**, never (campaign, phone), and has no
  `remove()`. Both are deliberate — see `campaign/optout.py`.
- **`NullDNDProvider` raises in production.** Marking numbers "checked" without
  checking is a TRAI exposure that stays invisible until it is not.
- **Never redial a `hangup` or `silence`.** They are signals, not failures; see
  `campaign/dialer.py:RETRYABLE`.
- **`campaign.simulate` must never leave a conversation `IN_PROGRESS`** — `to_record`
  maps that to `error`, and a simulated error rate is a lie about the system.

## Engineering defaults
- Python 3.11+, `uv`. Orchestrator: Pipecat (Stage 1) → Bolna self-hosted or Pipecat
  telephony (Stage 2). Do not write a custom orchestrator; implement `runner.Transport`.
- **TTS/clone:** Smallest.ai (documented self-serve Marathi cloning) and Gnani.ai
  Vachana (Marathi zero-shot from <10s, Indian, on-prem available; access model
  unverified) — bake off both. Sarvam cloning is enterprise-gated and its public TTS
  API takes a fixed `speaker` enum. IndicF5 (MIT, Marathi, free) needs a GPU. NVIDIA
  Magpie has no Marathi.
- **STT:** Sarvam Saaras — best on 8 kHz Indic telephony. Try `mode="codemix"`.
- Pre-render every fixed turn per voice; cache key `(voice_id, sha1(text), format)`.
  Live synthesis on a call path is a bug, and `CallRunner` refuses to start without a
  warm cache.
- Every session writes a record matching `schema/answers.schema.json` plus the audit
  fields (disclosure timestamp, consent ref, DND check, opt-out).
- Log per-turn latency; report p50/p95.
- Campaign layer (`campaign/`, `insights/`) is ours and off-the-shelf orchestrators do
  not provide it. The constituency report is the commercial asset — see the README.
- Useful skill packs: `github.com/bolna-ai/skills` (MIT), `github.com/sarvamai/skills`
  (Apache-2.0).

## Status (2026-09-07)
Voice core + campaign layer + constituency report built and tested offline; 149 tests
pass with no keys. Blocked on: a voice sample (3 min Hindi + 3 min Marathi + 30 s
through a phone call) and one cloning-vendor key. Nothing confirmed with any client.
Next: Stage 0 bake-off with real audio.
