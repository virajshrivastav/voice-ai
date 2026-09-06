# Handoff to the author of `00_CONTEXT.md`

**From:** Claude Code · **Date:** 2026-09-06 · **Branch:** `build/core-offline`

Your handoff was good enough to build from directly, which is not the normal case. It
got the three things right that most specs get wrong: the moat is the conversation and
the answer data rather than the voice, STT is the real risk rather than TTS, and don't
write an orchestrator. This document covers what changed when it met an implementation,
and the six questions where your research would move things forward faster than mine.

Read `06_CORRECTIONS.md` for the itemised list. This is the summary and the asks.

---

## 1. What is now built

All of it runs with **no API keys, no GPU, no phone, no voice sample**. 82 tests pass
offline. `python -m stage1.dryrun --lang mr-IN --scenario asks_a_question` walks a whole
call using the real script, answer bank, guard, state machine and record writer.

- `voiceai/` — script loader, answer bank, **SpeechGuard**, state machine, constrained
  classifier, pre-render cache, call runner, session record, cost model, telephony
  degradation, swappable TTS/STT.
- `stage0/` — bake-off, blind-test pack builder, scoring report. Proven end to end on
  mock audio through real ffmpeg G.711 degradation.
- `data/` — `script.{mr,hi}.yaml` transcribed from your `03_CALL_SCRIPT.md`, plus
  `answer_bank.{mr,hi}.yaml`, which is new (see §2).

## 2. One product decision was made that your spec left open

Viraj's requirement says follow-up responses are delivered in the MLA's voice. Your
spec says the LLM may only classify answers and pick whitelisted acknowledgements.
Those are not the same product, and the gap is where the pilot gets won or lost — a bot
that ignores "when will the water tanker come?" and asks the next survey question is a
robot, and everyone on the call knows it.

The resolution is an **approved answer bank**: ~25 replies per language that a named
person in the MLA's office signs off on, pre-rendered in his voice, retrieved by id.
The LLM's entire authority becomes *"return one of these ids, or NONE"*. It never
writes a sentence.

`SpeechGuard` enforces this at the synthesis boundary rather than by convention. A
hallucinated id, a state-machine bug, or an injection carried in a voter's own words
all fail identically: refused, fall back to approved text. There is a test where a
deliberately rogue classifier tries to emit a promise with a deadline, and every agent
turn still comes from the approved set.

Two properties fall out that matter to you specifically:

- **`guard.manifest()` is the MCMC artefact.** It emits the complete, finite,
  hashed list of every sentence the voice can utter. Your compliance doc flags that
  live LLM output cannot be pre-certified; this design means there is no live LLM
  output to certify. An interactive script becomes submittable as a closed set.
- **The answer bank is tamper-evident.** Approval stores a hash of the approved text;
  editing any answer afterwards fails closed with "changed after approval".

The bank ships as `status: draft` and production refuses to run against it.

## 3. Three things in your docs are wrong in ways that would have shipped

**`02_COMPLIANCE.md §1.3` breaks the product as written.** It defines opt-out as the
word "नाही/नहीं/no/stop". Implemented literally, the first dry run hung up on
*"पाणी रोज येत नाही, एक दिवसाआड येतं"* — a voter answering the water question. Marathi
and Hindi negate by appending that token to the verb, so **the commonest answer shape
and the opt-out keyword are the same word**. A campaign built on the literal rule would
report a catastrophic opt-out rate and nobody would know it was a parser bug. Fixed in
`IntentMatcher`; §1.3 needs rewording, and the reworded version should state the bias
explicitly — a missed opt-out is recoverable, a false one is not.

**`00_CONTEXT.md §3` and `§8` depend on a vendor we cannot reach.** Sarvam's public TTS
body takes `speaker`, an enum of ~44 catalog voices — there is no clone parameter at
all, cloning is absent from the pricing page and the changelog, and the marketing pages
describe it as enterprise. `01_EVIDENCE_CHECK.md #8/#9` reached the same conclusion but
the plan did not act on it. Stage 0 must not block on a Sarvam reply.

**`§4`'s cost model is roughly 2× conservative** because it assumes live TTS on every
turn. With fixed turns pre-rendered, `voiceai/costs.py` gives ₹0.89/min from the same
rates against ₹1.91/min for the un-optimised shape. Call it ₹1.2–1.5 planning, with
GST and pulse rounding. The line worth putting in the rewrite: **telephony is the
largest single cost and the AI is the minority of the bill.**

Also: `03_CALL_SCRIPT.md` routes to `CLOSE_SHORT` without giving its text, and gives no
Hindi opt-out line. Both are drafted and flagged `drafted_here: true`.

## 4. Two vendors your survey missed

**AI4Bharat IndicF5** — MIT on the model card, 11 Indian languages **including
Marathi**, zero-shot cloning from a reference clip plus transcript, free and
self-hosted, from IIT Madras. Your table writes off open source as "Marathi
`[unverified]`". Caveats: HuggingFace repo is access-gated, GitHub dormant since Sept
2025, non-streaming — which matters far less here than usual, because ~90% of the call
is pre-rendered anyway.

**Gnani.ai Vachana TTS** (Feb 2026) — and `§2` already names Gnani, but as a competitor
running Swachh Bharat surveys, not as someone who would sell us a clone. Zero-shot from
under 10 seconds, 12 Indic languages including Marathi, real-time streaming, on-prem
for regulated sectors, low-bandwidth tuned. Gnani is **one of four IndiaAI Mission
sovereign-model companies** — the same political convenience you correctly identified in
Sarvam, except Gnani will actually sell you cloning. On paper this is the best fit in
the whole survey. Unverified: self-serve vs sales-gated, price, real latency.

For completeness on Viraj's NVIDIA suggestion: **Magpie TTS Multilingual has no
Marathi** (12 languages, Hindi yes). It is genuinely the low-latency open-weights
option — 47 ms TTFA on an H100 — but it cannot carry the production language. And the
latency lever here isn't the model anyway; a pre-rendered turn plays from disk faster
than any streaming TTS can start.

## 5. Six questions for you

1. **Sarvam clone access.** Has the email in `§11` gone out, and is there any signal on
   price or timeline? If a clone runs ₹2–3 lakh in setup, that changes the vendor
   ranking regardless of quality.
2. **Gnani Vachana access model and price.** Highest-leverage unknown in the project.
   If it is self-serve and Marathi-strong, it likely wins on quality *and* on the
   procurement story for a government buyer.
3. **The ~9× price step.** MLAs buy one-way blasts at ~₹0.50/call; a 3.5-lakh sweep at
   ₹5/min bills ~₹15.75 lakh against ~₹1.75 lakh for what they already know. Your
   `§2` names this but the plan still prices per minute. Should the pilot be priced on
   the grievance list — per resolved case, per ward report, a flat monthly retainer —
   rather than per minute? Per-minute pricing invites the comparison we lose.
4. **TRAI "Government Voice Call".** `§7` flags this as needing telco confirmation. If
   governance-lane calls from an MLA's office qualify, DND and time-band constraints
   change materially, and so does the addressable list. Worth a definitive answer
   before the DLT application, not during.
5. **Marathwada register.** No vendor produces the dialect, which you say. The open
   question is whether standard Marathi from an MLA is *normal* — politicians speak
   formally in public, so it may be a non-issue — or whether it reads as an outsider.
   Only local listeners can settle it, and it should be an explicit dimension in the
   Stage 0 blind test rather than a comment field.
6. **The voter list.** Still the largest legal risk and still unanswered. Electoral
   rolls with caveats, or something else? Everything in `02_COMPLIANCE.md` DPDP depends
   on the answer, and Stage 3 cannot be scoped without it.

## 6. What unblocks the next step

Two cheap things, in this order:

1. **A voice sample.** 3 min Hindi + 3 min Marathi, quiet room, phone recorder, plus
   30 s recorded through an actual phone call. Every measurement in `stage0/` waits on
   this and nothing else.
2. **One cloning key** — Smallest.ai or Gnani. Either produces a real answer to the
   only question that actually gates the product: does the clone survive an 8 kHz line
   to a listener from Sambhajinagar.

A methodological note for whoever runs the blind test. Include the speaker's real
recording as a control **and degrade it identically**, then read every clone against
the control rather than against 5.0. A human voice through G.711 does not score 5 on
"sounds like him"; a clone at 3.6 against a control at 4.1 has recovered ~88% of what a
real call sounds like, and scoring it against a studio reference no voter will ever hear
would reject a perfectly good vendor. `stage0/blindpack.py` and `report.py` do this;
the numbers just need to be read that way in the write-up.
