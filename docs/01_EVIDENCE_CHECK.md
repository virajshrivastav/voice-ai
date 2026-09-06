# Evidence Check — claim by claim

Re-verification run on **2026-09-06** against primary/official pages where possible. Status legend:
✅ verified against primary source · 🟡 verified against secondary source or partially · ✏️ corrected · ❌ unverified (do not rely on it)

| # | Claim in `00_CONTEXT.md` | Status | What the source actually says | Source |
|---|---|---|---|---|
| 1 | 50M+ AI voice-clone calls in the two months before 2024 LS polls; iToConnect 25M calls in 2 weeks (Telangana + AP) | ✅ | Exact figures in WIRED, 20 May 2024, quoting "one of the country's largest business messaging operators" and iToConnect | wired.com/story/indian-elections-ai-deepfakes |
| 2 | Josh Talks blind eval: 44k+ votes, 1,000+ native speakers, 11 languages; telephony (8 kHz, 11,902 votes) Bulbul v3 wins 60.1% vs ElevenLabs v3, 57.7% vs Sonic-3, >90% vs others; full-band (32k+ votes) ElevenLabs v3 59.2%; ElevenLabs degrades 19.3 pts at 8 kHz | ✅ | All numbers match the blog post. Note: Bulbul evaluated was **V3-beta** | evals.ai.joshtalks.com/blog/indic-tts-evaluation-bulbul-v3-vs-others |
| 3 | Caller Digital Marathi MOS: Bulbul 4.2 vs ElevenLabs 3.9 | 🟡 | Vendor-adjacent blog (Caller Digital sells voice AI); treat as indicative only | caller.digital/blog/indic-tts-benchmark-… |
| 4 | ElevenLabs PVC Indic languages = Hindi + Tamil only; no Marathi | ✅ | PVC language list = Flash v2.5 languages; Indic entries are Hindi and Tamil | help.elevenlabs.io …/19569659818129 |
| 5 | Cloning from a non-target-language sample carries an accent | ✅ | ElevenLabs PVC docs say so explicitly | elevenlabs.io/docs …/professional-voice-cloning |
| 6 | ElevenLabs blocks public-figure clones ("no-go voices"), bans accounts | ✅ | Help-center article + safety page | help.elevenlabs.io …/22584327690897 |
| 7 | Sarvam pricing: Bulbul v3 ₹30/10k chars, v2 ₹15; STT ₹30/hr; Sarvam-30B/105B "free per token" on summary list, ₹2.5/₹10 and ₹4/₹16 per 1M tokens in the table; ₹1,000 free credits on every plan; Pro ₹10,000 (+₹1,000 bonus); Starter 60 RPM, Pro 200 RPM | ✅ | Page shows both "free per token" and the per-token table — assume the table is billing truth, "free" is promotional | sarvam.ai/api-pricing |
| 8 | Sarvam voice cloning: consent-based, 30–60 s sample, enterprise ("reach out") | ✅ | Stated on TTS page + Bulbul v3 blog | sarvam.ai/text-to-speech; sarvam.ai/blogs/bulbul-v3 |
| 9 | Sarvam clone **price** | ❌ | Not published anywhere found | — |
| 10 | Smallest.ai Lightning v3.1: 12 languages, Marathi with 9 voices, instant clone 5–15 s via API and console (self-serve) | ✅ | Model card table lists `mr` 9 voices; cloning section confirms | docs.smallest.ai …/lightning-v-3-1.md |
| 11 | Smallest.ai price ~$14.5/1M chars ($19.5 Pro) | 🟡 | From pricing page read 2026-09-05; not re-opened today | smallest.ai/pricing/models |
| 12 | Smallest.ai free tier | ❌ | Not confirmed | — |
| 13 | Cartesia Instant Voice Clone needs **Pro plan or above**; Pro Voice Clone needs Startup plan, 30 min audio, 1M credits | ✅ | Docs table | docs.cartesia.ai …/clone-voices-pro |
| 14 | Cartesia supports Marathi | 🟡 | "44 languages" on product page; Marathi appeared in a 2026-09-05 search snippet; confirm on signup | cartesia.ai/sonic |
| 15 | Cartesia free tier 20k credits/month, no cloning | 🟡 | Pricing page, read 2026-09-06 | cartesia.ai/pricing |
| 16 | Speech-to-speech models (OpenAI Realtime, Gemini Live) don't support cloned/custom voices | ✅ | OpenAI docs list 10 built-in voices only; Gemini Live exposes only prebuilt voices (open feature request) | developers.openai.com …/realtime-conversations; github.com/google/adk-docs/issues/487 |
| 17 | Voice of India ASR benchmark: 536 h unscripted telephonic, 15 languages, 139 regions; Deepgram Nova-3 WER 29–68% on several Indic languages vs Sarvam ~5–21% | ✅ | arXiv 2604.19151 table; live leaderboard shows Hindi: Sarvam Omni 5.0%, Deepgram Nova-3 13.0% | ar5iv …/2604.19151; voiceofindia.ai |
| 18 | Cascaded pipeline realistic latency 600–1,000 ms in India; Twilio target 1,115 ms; semantic endpointing 150–250 ms vs 500–800 ms naive | ✅ | Softcery latency-budget article (Twilio/Telnyx targets) + Caller Digital India benchmarks | softcery.com/lab/…; caller.digital/blog/… |
| 19 | Plivo India outbound ₹0.38/min; Indian number ₹200/month; $10 trial credit; self-serve cap 50 concurrent | ✏️ | ₹0.38/min is the **Voice API domestic** rate with a **30-second pulse**; the SIP-trunking route is ₹0.60/min. Number ₹200/mo and $10 trial confirmed. 50 concurrency cap on standard tier confirmed | plivo.com/voice/pricing/in; …/sip-trunking/pricing/in; …/pricing |
| 20 | Exotel ~₹0.50/pulse; 7-day trial with ₹500 credit | 🟡 | Trial confirmed on Exotel pricing page; per-pulse rate is from developer docs read 2026-09-05, volume pricing is enterprise-negotiated | exotel.com/pricing/business-phone-system |
| 21 | Bolna is MIT-licensed; supports Exotel, Plivo, Twilio; Sarvam/Smallest STT; Sarvam/Cartesia/ElevenLabs/Azure TTS; Marathi `mr` | ✅ | GitHub API: license MIT, 749★, pushed 2026-09-05. Docs list providers and language codes. Bolna also publishes **Claude Code skills** (bolna-ai/skills, MIT) | api.github.com/repos/bolna-ai/bolna; bolna.ai/docs |
| 22 | Bolna cloud ≈ 6¢ (~₹5.5)/min | 🟡 | From pricing snippets 2026-09-05; not re-opened | bolna.ai |
| 23 | Pipecat is BSD-2; `SmallWebRTCTransport` gives a free browser demo without telephony | ✅ | GitHub API: BSD-2-Clause, 15,259★. Docs describe P2P WebRTC transport for local dev | api.github.com/repos/pipecat-ai/pipecat; docs.pipecat.ai |
| 24 | Vapi $0.05/min, Retell $0.055, Bland $0.11–0.14 platform fee; all-in $0.065–0.113/min | 🟡 | Third-party comparisons (StackBinary, SilverThread); vendor pages not re-opened | see 05_SOURCES.md |
| 25 | ECI advisory 24 Oct 2025: label AI/synthetic campaign content ("AI-Generated", "Digitally Enhanced", "Synthetic Content"); ≥10% display area; disclose creator; 3-hour takedown | ✏️ | Confirmed via ECI PDF + TOI 25 Oct 2025. **Correction:** the 10% rule is a *display-area* rule for visual content; for audio the requirement is a clear label/disclosure — there is no "10% of clip duration" rule | ECI press note PDF (Oct 2025); timesofindia …/124798284 |
| 26 | ECI: bulk voice messages need MCMC pre-certification; banned in 48-h silence period | ✅ | The Hindu 14 Oct 2025 (Bihar); Akashvani 3 Sept 2026 (order for Assam/Kerala/TN/WB/Puducherry + bye-polls) — the pre-cert order is re-issued per election | thehindu.com …/article70161947; newsonair.gov.in |
| 27 | TRAI TCCCPR Second Amendment notified 12 Feb 2025; in force 30 days (some clauses 60 days) after gazette | ✅ | TRAI gazette PDF | trai.gov.in …/Regulation_12022025.pdf |
| 28 | 140-series mandatory for promotional voice; DLT registration of sender; "Government Voice Call" category exists | 🟡 | 140-series and DLT confirmed (TRAI direction 4 May 2024 on Voice DLT; Airtel directive). "Government Voice Call" category appears in TRAI 2025 amendment summaries (Khaitan); confirm applicability with telco | trai.gov.in Direction_04052024; khaitanco.com |
| 29 | IT Rules Amendment 2026 on synthetically generated information: G.S.R. 120(E) dated 10 Feb 2026, in force 20 Feb 2026 | ✅ | MeitY FAQ states exactly this | meity.gov.in FAQ PDF |
| 30 | DPDP Rules 2025 notified 13/14 Nov 2025 (G.S.R. 846(E)) | ✅ | MeitY page dated 14.11.2025; gazette dated 13 Nov | meity.gov.in; cadp.in |
| 31 | Political parties are not "State" under DPDP → full obligations | 🟡 | Legal commentary (Mondaq, Aug 2026); no court ruling yet | mondaq.com …/1802076 |
| 32 | Aadhaar/welfare data for voter profiling unlawful (Puttaswamy) | 🟡 | Academic/legal commentary; principle is settled, application to a specific dataset needs counsel | repository.nls.ac.in; clt.nliu.ac.in |
| 33 | NH "Biden" robocall: $6M FCC forfeiture on Kramer, $1M on Lingo Telecom; criminal acquittal June 2025; civil default judgment | ✅ | FCC release; WBUR; LWV filing | fcc.gov; wbur.org; lwv.org |
| 34 | "Telcos will refuse unlabelled political AI traffic" | ✏️ | Overstated. Exotel's ToS makes the customer solely responsible for legal compliance and positions Exotel as an intermediary; no published policy on AI political calls found. Get written confirmation from the telco during onboarding | next.exotel.com/terms-of-service-exotel |
| 35 | Next Maharashtra assembly election ≈ Nov 2029 | ✅ | Wikipedia (June 2026) | en.wikipedia.org |
| 36 | Sarvam selected by IndiaAI Mission (Apr 2025) for sovereign LLM | ✅ | Indian Express, PIB | indianexpress.com; pib.gov.in |
| 37 | Two-way AI political survey vendors exist (Edesy, VoxBharat); ₹0.50/call one-way blast anchors | 🟡 | Vendor marketing pages; not independently validated | edesy.in; voxbharat.ai; digibrood.in |

## Net effect on conclusions
None of the seven TL;DR conclusions change. Two wording corrections were applied in `00_CONTEXT.md` (#25 label rule, #34 telco stance) and one billing nuance (#19 30-second pulse — slightly raises telephony cost on short calls). Items marked ❌ (Sarvam clone price, Smallest free tier) and 🟡 items with commercial impact (Exotel volume rate, Cartesia Marathi) must be confirmed during Stage 0 signups.
