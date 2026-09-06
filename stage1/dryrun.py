"""Walk a whole call with no keys, no GPU, no phone and no voice sample.

    python -m stage1.dryrun --lang mr-IN
    python -m stage1.dryrun --lang mr-IN --scenario asks_a_question
    python -m stage1.dryrun --lang hi-IN --scenario noisy --wer 0.4

This is the thing that is runnable today. It exercises the real script, the real
answer bank, the real guard, the real state machine and the real record writer; only
the microphone and the speaker are fake. When a voice sample and a key arrive, the
only line that changes is which TTS provider warms the cache.

The `noisy` scenario matters more than it looks. Indic telephony ASR runs ~19% WER at
best, so a run where every transcript is clean is not a test of this system — it is a
test of a system we will never operate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from voiceai import build
from voiceai.classify import KeywordClassifier
from voiceai.config import OUT_DIR, load_settings
from voiceai.console import setup
from voiceai.prerender import PrerenderCache
from voiceai.runner import CallRunner
from voiceai.session import CallSession, validate, write_record
from voiceai.stt.base import Transcript
from voiceai.stt.mock import MockSTT
from voiceai.tts import get_tts

SCENARIOS: dict[str, dict[str, list[str]]] = {
    "cooperative": {
        "mr-IN": [
            "हो, बोला",
            "पाणी रोज येत नाही, एक दिवसाआड येतं आणि कमी वेळ असतं",
            "रस्ता खूप खराब आहे, खड्डे आहेत आणि पथदिवे लागत नाहीत",
            "रेशन कार्डवर धान्य मिळत नाही, दुकानदार टाळाटाळ करतो",
            "गटाराचं पाणी घरासमोर साचतं, अनेकदा सांगितलं पण काही झालं नाही",
        ],
        "hi-IN": [
            "हाँ, बोलिए",
            "पानी रोज़ नहीं आता, एक दिन छोड़कर आता है",
            "सड़क बहुत खराब है, गड्ढे हैं और स्ट्रीट लाइट नहीं जलती",
            "राशन कार्ड पर अनाज नहीं मिलता",
            "नाली का पानी घर के सामने जमा होता है, कई बार बताया",
        ],
    },
    "asks_a_question": {
        "mr-IN": [
            "हो",
            "हे खरंच तुम्हीच बोलताय का? रेकॉर्डिंग आहे का?",
            "पाणी रोज येत नाही, टँकर मागवावा लागतो",
            "रस्ता खराब आहे",
            "माझा नंबर कुठून मिळाला तुम्हाला?",
            "लाडकी बहीण योजनेचा हप्ता आलाच नाही",
            "काही नाही, एवढंच",
        ],
        "hi-IN": [
            "हाँ",
            "यह सच में आप बोल रहे हैं क्या? रिकॉर्डिंग है क्या?",
            "पानी रोज़ नहीं आता, टैंकर मंगाना पड़ता है",
            "सड़क खराब है",
            "मेरा नंबर कहाँ से मिला आपको?",
            "लाडकी बहीण योजना की किस्त नहीं आई",
            "कुछ नहीं, बस इतना ही",
        ],
    },
    "optout": {
        "mr-IN": ["नाही, नको मला"],
        "hi-IN": ["नहीं, मुझे नहीं चाहिए"],
    },
    "silent": {"mr-IN": ["", ""], "hi-IN": ["", ""]},
    "noisy": {
        "mr-IN": [
            "हो",
            "पाणी",
            "रस्ता खूप खराब आहे खड्डे आहेत",
            "काय",
            "रेशन धान्य मिळत नाही",
            "गटार साचतं",
        ],
        "hi-IN": ["हाँ", "पानी", "सड़क बहुत खराब है", "क्या", "राशन नहीं मिलता", "नाली जमा"],
    },
}


class DryRunTransport:
    """Prints instead of playing, replays a list instead of listening."""

    def __init__(self, stt: MockSTT, verbose: bool = True):
        self._stt = stt
        self._verbose = verbose
        self.hung_up = False

    def play(self, audio: bytes, text: str, source: str | None) -> None:
        if self._verbose:
            print(f"  \033[36mAGENT\033[0m  \033[90m[{source}]\033[0m {text}")

    def listen(self, timeout_s: float) -> Transcript | None:
        t = self._stt.next_utterance()
        if self._verbose and t.text:
            flag = "  \033[33m(low conf)\033[0m" if t.is_low_confidence else ""
            print(f"  \033[32mVOTER\033[0m  {t.text}{flag}")
        elif self._verbose:
            print("  \033[90mVOTER  … silence\033[0m")
        return t if t.text else None

    def hangup(self) -> None:
        self.hung_up = True
        if self._verbose:
            print("  \033[90m— call ended —\033[0m")


def main() -> None:
    setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lang", default="mr-IN")
    p.add_argument("--scenario", default="cooperative", choices=sorted(SCENARIOS))
    p.add_argument("--wer", type=float, default=0.0, help="simulated transcript error rate 0-1")
    p.add_argument("--voice-id", default="dryrun")
    p.add_argument("--out", type=Path, default=OUT_DIR / "dryrun")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()

    settings = load_settings()
    script, bank, guard = build(args.lang, settings)

    # Warm the cache with the mock voice so the runner's "no live TTS on a call" rule
    # holds in the dry run exactly as it will on a real line.
    cache = PrerenderCache(voice_id=args.voice_id, root=args.out / "cache")
    stats = cache.warm(guard, get_tts("mock"), args.lang)
    if not args.quiet:
        print(f"\n  cache: {stats.summary()}")
        print(f"  guard: {len(guard)} approved sentences, bank status "
              f"'{bank.approval.get('status')}'\n")

    utterances = SCENARIOS[args.scenario].get(args.lang, [])
    stt = MockSTT(utterances=utterances, error_rate=args.wer, seed=7)
    transport = DryRunTransport(stt, verbose=not args.quiet)

    session = CallSession(
        campaign_id="dryrun",
        voter_id="voter-0001",
        lang=args.lang,
        politician_id=settings.speaker.name or "unset",
        voice_consent_ref=settings.speaker.consent_ref,
    )
    session.mark_dnd_checked()

    runner = CallRunner(
        script=script, bank=bank, guard=guard,
        classifier=KeywordClassifier(), cache=cache,
        transport=transport, session=session,
    )
    convo = runner.run()

    record = session.to_record(convo)
    validate(record, production=False)
    path = write_record(record, args.out / "records")

    print(f"\n  outcome        {record['outcome']}")
    print(f"  answers        {json.dumps(record['answers'], ensure_ascii=False)}")
    print(f"  answered back  {convo.bank_hits or '—'}")
    print(f"  latency        {runner.stats.summary()}")
    print(f"  record         {path}\n")


if __name__ == "__main__":
    main()
