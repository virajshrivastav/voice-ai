# Corrections & additions to the handoff

Written 2026-09-06 by Claude Code, after building against `00_CONTEXT.md`–`05_SOURCES.md`.
This file does not replace them. It records where re-verification changed an answer,
where building found something the spec could not have known, and what is still open.

Legend: **C** correction · **N** new finding · **B** bug found by building it

---

## C1 — Sarvam voice cloning is not something we can use yet

`00_CONTEXT.md §3` makes Sarvam the primary clone vendor and `§8` puts a Sarvam clone
in Stage 0. As of today there is no self-serve Sarvam cloning:

- the public TTS request body takes `speaker`, an **enum of ~44 catalog voice names** —
  there is no voice-id, clone-id or reference-audio parameter at all
  (`docs.sarvam.ai/api-reference-docs/text-to-speech/convert`);
- voice cloning does not appear in the pricing page or the API changelog;
- the marketing pages describe it as consent-based and **enterprise**, price unpublished.

This is the same conclusion as `01_EVIDENCE_CHECK.md #8/#9`, but the consequence was
not carried through to the plan. **Stage 0 cannot depend on Sarvam.** Send the access
email in `00_CONTEXT.md §11` anyway; treat a reply as upside.

Sarvam remains the right choice for **STT** — see N4.

## C2 — Model versions and credits have moved

| In the docs | Actual, 2026-09-06 |
|---|---|
| Bulbul **v3** | **v4** shipped July 2026; v3 still current in the API enum |
| STT "Saarika" | **Saaras v3** is the current model, **v4** also selectable |
| "₹1,000 free credits on signup" | the docs pricing page says **₹100**. Confirm at signup — this is the whole Stage 0 budget |

## C3 — The cost model is roughly 2× conservative

`00_CONTEXT.md §4` gives ₹2.5–3.0/min. That assumes live TTS on every turn and STT
billed on the whole call. `voiceai/costs.py` models both, from the same rates:

```
no pre-render, STT on full call     ₹1.91/min     <- the §4 figure's shape
90% pre-rendered, STT voter-only    ₹0.89/min
```

Two caveats before anyone quotes ₹0.89. It assumes an exactly 2.00-minute call, which
lands evenly on Plivo's 30-second pulse; at 2.1 minutes telephony jumps from ₹0.38 to
₹0.45/min. And it excludes GST. **₹1.2–1.5/min is the honest planning number**, and
it is still far under the ₹5 sell price.

The line that actually matters: **telephony is the largest single cost, and the AI is
the minority of the bill.** Cheap-to-run is mostly a carrier-rate and pickup-rate
problem. Negotiating the Exotel/Plivo rate is worth more than any model choice.

## C4 — The commercial gap is bigger than the docs imply

`§2` notes MLAs already buy one-way blasts at ~₹0.50/call. A 3.5-lakh sweep at
₹5/min bills ~₹15.75 lakh against ~₹1.75 lakh for the blast they know. That is a **~9×
price step**, and no amount of voice quality closes it — only the answer data does.
Price the pilot on the grievance list, not on the minutes.

---

## N1 — Open-source Marathi voice cloning exists, and the docs miss it

`§3` lists open source as "Hindi yes; Marathi `[unverified]`". It is verified now:

**AI4Bharat IndicF5** — 0.4B params, 1,417 hours, 11 Indian languages **including
Marathi**, zero-shot cloning from a reference clip plus its transcript, **MIT** on the
model card. Free, self-hosted, and from IIT Madras, which is a better provenance story
for a Maharashtra government pitch than any US vendor.

Verified caveats, all of which matter:
- the HuggingFace repo is **access-gated** (a raw fetch returns "access restricted");
- the GitHub repo has not been pushed since **September 2025**;
- it is flow-matching, so **not streaming** — good for pre-rendered turns, poor for live ones;
- the MIT claim is on the model card; the GitHub repo carries no license file, and the
  training corpora have their own terms. Worth ten minutes of legal reading before
  production, not before a bake-off.

Since ~90% of a call is pre-rendered, non-streaming is a much smaller problem here than
it would be in a general voice agent. `voiceai/tts/__init__.py` has the adapter slot.

## N2 — NVIDIA's low-latency stack does not cover Marathi

**Magpie TTS Multilingual** is genuinely the low-latency open-weights option: 364M
params, TTFA 32 ms on B200 / 47 ms on H100 / 79 ms on A100 single-stream, NVIDIA Open
Model License. Its 12 languages are English, Spanish, French, German, Italian,
Vietnamese, Mandarin, **Hindi**, Japanese, Arabic, Korean, Brazilian Portuguese —
**no Marathi**. It cannot carry the production language. Keep it for a Hindi variant.

More to the point: the latency lever here is not the model. Pre-rendering makes the
scripted turns play in single-digit milliseconds from disk, which no streaming TTS can
beat, and that is most of the call.

## N3 — Two accessible Marathi cloning vendors, not one

**Smallest.ai Lightning v3.1.** Self-serve instant cloning from 5–15 s, 9 Marathi
voices, 200 ms TTFB in-region (500–800 ms from a distant client — RTT dominates),
HTTP/SSE/WebSocket. Consent required by their ToS, which we satisfy anyway.
*Unverified:* the documented `add_voice` endpoint sits on a **different host** and still
says `lightning-large`, not `v3.1`. `SMALLEST_CLONE_URL` overrides it.

**Gnani.ai Vachana TTS** (launched Feb 2026) — and `00_CONTEXT.md §2` already names
Gnani, but as a competitor running citizen surveys, not as a vendor we could buy from.
Zero-shot cloning from **under 10 seconds**, 12 Indic languages **including Marathi**,
real-time streaming, on-premises deployment offered for regulated sectors, and
optimised for low-bandwidth. Gnani is **one of four companies selected under the
IndiaAI Mission** to build sovereign foundational models — the same political
positioning that makes Sarvam convenient for a government buyer, except Gnani will
actually sell you a clone.

On paper this is the better fit: Indian, sovereign-programme, on-prem available,
low-bandwidth tuned, streaming. What is **not** verified: whether API access is
self-serve or sales-gated, the price, the latency, and — worth noting — the press
material states no consent or safety requirement for cloning, which is a gap in their
posture rather than a licence for us. We impose consent regardless
(`02_COMPLIANCE.md §1.2`).

**Both belong in the Stage 0 bake-off.** Neither should be assumed until a key exists.

## N4 — Sarvam for ears, someone else for the mouth

Saaras v3 reports **~19.31% WER on IndicVoices** and is explicitly tuned for 8 kHz
telephony; open-source Indic ASR is 22–30% on telephony audio. It also exposes a
**`codemix` mode**, which is worth trying first: voters in Marathwada switch between
Marathi, Hindi and English inside one sentence, and a monolingual decode of that
produces the exact failure this product cannot afford — a confident wrong transcript
that becomes a recorded grievance.

So the expected shape is **Sarvam STT + a non-Sarvam clone**, until Sarvam grants
clone access.

## N5 — Sarvam now offers self-hosted deployment

Saaras v3, Bulbul v3 and Sarvam Vision can run as SageMaker endpoints **inside your own
AWS VPC**, with audio never leaving it. For a project whose buyer is a government
office and whose data is voter grievances under DPDP, that is a procurement argument as
much as a technical one. Not needed before Stage 3.

---

## B1 — The opt-out rule in `02_COMPLIANCE.md §1.3` breaks calls as written

§1.3 defines opt-out as the word "नाही/नहीं/no/stop". Implemented literally — a
substring match — the first dry run hung up on:

> "पाणी रोज येत नाही, एक दिवसाआड येतं" — *water doesn't come daily, it comes every other day*

Marathi and Hindi negate by appending नाही/नहीं to the verb. **The most common answer
shape and the opt-out keyword are the same token.** A literal implementation hangs up
on the people with the most to say, and the campaign would look like it had a
catastrophic opt-out rate rather than a bug.

Fixed in `voiceai/script.py:IntentMatcher`: unambiguous multi-word phrases match
anywhere; bare negations only count when the utterance is essentially nothing else.
Locked down by `tests/test_script.py`. **§1.3 should be reworded.**

The bias is deliberate and worth stating in the compliance doc: a missed opt-out is
recoverable — the voter repeats it, more firmly — while a false opt-out is not.

## B2 — Answer-bank ordering is not obvious and both naive orders are wrong

Consulting the bank before classifying: "रस्ता खराब आहे आणि पथदिवे लागत नाहीत" fires
the streetlight entry, so the agent answers a question nobody asked and the roads
answer is lost.

Classifying before the bank: "मी इथे राहत नाही, चुकीचा नंबर आहे" — *wrong number* —
gets filed as an answer and the call continues, which is the one thing that person
definitely does not want.

The working order, in `state_machine.py`:
1. **call-control statements always** (wrong number, call me later, say that again) —
   keyword-only, never model-dependent;
2. **the bank** when the utterance is interrogative;
3. **classify** otherwise;
4. **the bank again** as a last resort when classification failed;
5. clarify once, then record `unanswered`.

## B3 — Turns referenced by the script but never written

`03_CALL_SCRIPT.md` routes to `CLOSE_SHORT` but gives no text, and gives no Hindi
opt-out line. Both are drafted in `data/script.*.yaml` and flagged `drafted_here: true`.
They need the same native review as everything else.

## B4 — Q2 fills two schema fields, and the naive default fabricates data

One utterance answers both `roads` and `lights`. Defaulting `lights` to `ok` when the
roads answer could not be classified would put invented data in a record an MLA's
office acts on. Unclassifiable now propagates as `unanswered`.

---

## Still open

- **Sarvam clone price and access.** Unknown. Email sent? No reply modelled.
- **Smallest.ai real pricing and free tier.** Docs say "contact sales".
- **Cartesia Marathi.** Still unconfirmed; cloning needs the Pro plan. Not worth the
  spend until Smallest and IndicF5 have been scored.
- **IndicF5 Marathi clone quality at 8 kHz.** Nobody has benchmarked it against Sarvam
  or Smallest. That is exactly what Stage 0 is for, and it needs a GPU.
- **Exotel volume rate**, and whether governance-lane calls from an MLA's office
  qualify for TRAI's "Government Voice Call" category.
- **Lawful source of the voter list.** Unchanged and still the largest legal risk.
- **Whether a native Sambhajinagar speaker accepts the script's register.**
