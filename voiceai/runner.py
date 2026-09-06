"""CallRunner — the loop, with the audio transport left as a hole.

Everything above this line is transport-free on purpose. A Pipecat browser bot, a
Pipecat telephony bot and an offline dry run differ only in how bytes get to and from
a human, so they all implement the same tiny `Transport` protocol and share this loop
verbatim. That is what stops the Stage 1 demo and the Stage 2 phone call from drifting
into two different products.

The runner also owns the two things easiest to forget and most expensive to omit:
stamping `disclosure_played_at` the moment the disclosure turn actually plays, and
refusing to start a call whose fixed turns are not fully pre-rendered.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from .answer_bank import AnswerBank
from .guard import SpeechGuard
from .prerender import PrerenderCache
from .script import CallScript
from .session import CallSession
from .state_machine import Action, Conversation, Hangup, Silence, VoterSaid
from .stt.base import Transcript


class Transport(Protocol):
    """What a call surface has to provide. Three methods, no audio types leaked.

    `play` receives the text and its source alongside the bytes. A real transport does
    not need them to make sound, but every transport needs them for the per-turn call
    log, and passing them here means the log cannot drift from what was actually
    played.
    """

    def play(self, audio: bytes, text: str, source: str | None) -> None: ...
    def listen(self, timeout_s: float) -> Transcript | None: ...
    def hangup(self) -> None: ...


@dataclass
class RunStats:
    turns_spoken: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    listen_timeouts: int = 0
    speak_latencies_ms: list[float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.speak_latencies_ms is None:
            self.speak_latencies_ms = []

    def percentile(self, p: float) -> float:
        if not self.speak_latencies_ms:
            return 0.0
        ordered = sorted(self.speak_latencies_ms)
        idx = min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1))))
        return ordered[idx]

    def summary(self) -> str:
        return (
            f"{self.turns_spoken} agent turns · cache {self.cache_hits}/"
            f"{self.cache_hits + self.cache_misses} · "
            f"p50 {self.percentile(50):.0f} ms · p95 {self.percentile(95):.0f} ms"
        )


class NotPrerenderedError(RuntimeError):
    pass


class CallRunner:
    def __init__(
        self,
        script: CallScript,
        bank: AnswerBank,
        guard: SpeechGuard,
        classifier,
        cache: PrerenderCache,
        transport: Transport,
        session: CallSession,
        *,
        listen_timeout_s: float = 4.0,
        max_call_seconds: float = 180.0,
        require_full_cache: bool = True,
    ):
        self.script = script
        self.bank = bank
        self.guard = guard
        self.cache = cache
        self.transport = transport
        self.session = session
        self.listen_timeout_s = listen_timeout_s
        self.max_call_seconds = max_call_seconds
        self.stats = RunStats()

        if require_full_cache:
            cached, total = cache.coverage(guard)
            if cached < total:
                raise NotPrerenderedError(
                    f"{total - cached} of {total} approved turns are not in the cache for "
                    f"voice {cache.voice_id}. Warm it before dialling — a live TTS call on "
                    f"the disclosure turn is both slower and more expensive than the whole "
                    f"rest of the call. Run prerender.warm() first."
                )

        self.convo = Conversation(script=script, bank=bank, guard=guard, classifier=classifier)

    def run(self) -> Conversation:
        started = time.monotonic()
        actions = self.convo.start()

        while True:
            for action in actions:
                self._perform(action)

            if self.convo.finished:
                break
            if time.monotonic() - started > self.max_call_seconds:
                # Hard stop at 3 minutes (docs/03_CALL_SCRIPT.md). Cut politely, not mid-word.
                actions = self.convo.handle(Hangup())
                for action in actions:
                    self._perform(action)
                break

            transcript = self.transport.listen(self.listen_timeout_s)
            if transcript is None or not transcript.text.strip():
                self.stats.listen_timeouts += 1
                actions = self.convo.handle(Silence(self.listen_timeout_s))
            else:
                actions = self.convo.handle(
                    VoterSaid(text=transcript.text, confidence=transcript.confidence)
                )

        self.session.finish()
        return self.convo

    def _perform(self, action: Action) -> None:
        if action.kind == "hangup":
            self.transport.hangup()
            return
        if action.kind != "speak" or not action.text:
            return

        start = time.perf_counter()
        # Belt and braces: the state machine already asked the guard, ask again here.
        # This is the last line of code before a voter hears the MLA's voice.
        text = self.guard.assert_speakable(action.text)

        audio = self.cache.get(text)
        if audio is None:
            self.stats.cache_misses += 1
            raise NotPrerenderedError(
                f"no cached audio for {action.source}. Live synthesis is not permitted on "
                f"a call path — warm the cache."
            )
        self.stats.cache_hits += 1
        self.transport.play(audio, text, action.source)
        self.stats.turns_spoken += 1
        self.stats.speak_latencies_ms.append((time.perf_counter() - start) * 1000.0)

        if action.source == "script:OPEN" and self.session.disclosure_played_at is None:
            self.session.mark_disclosure_played()
