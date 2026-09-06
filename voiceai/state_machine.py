"""Conversation state machine.

A state machine with an LLM inside it, not an agent. The machine decides what happens
next; the model only labels what the voter said. Every string this produces comes out
of the script or the approved answer bank, and `SpeechGuard` re-checks that at the
synthesis boundary.

Shape (docs/03_CALL_SCRIPT.md):

    OPEN -> Q1 -> Q2 -> Q3 -> Q4 -> CLOSE -> END
    OPTOUT reachable from every state
    silence twice -> CLOSE_SHORT -> END
    at any question, the voter may ask something instead of answering: the answer bank
    replies, then the question is re-asked once

Deliberately transport-free. Feed it events, get actions back. That is what lets the
same conversation run in a browser (Stage 1) and on a phone (Stage 2), and be tested
with no audio at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol

from .answer_bank import AnswerBank
from .guard import SpeechGuard
from .script import CallScript, normalise

MAX_CLARIFICATIONS_PER_QUESTION = 1
MAX_BANK_ANSWERS_PER_QUESTION = 1
SILENCE_LIMIT = 2


class State(str, Enum):
    OPEN = "OPEN"
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    CLOSE = "CLOSE"
    CLOSE_SHORT = "CLOSE_SHORT"
    OPTOUT = "OPTOUT"
    END = "END"


class Outcome(str, Enum):
    COMPLETED = "completed"
    OPTED_OUT = "opted_out"
    SILENCE = "silence"
    HANGUP = "hangup"
    ERROR = "error"
    IN_PROGRESS = "in_progress"


@dataclass(frozen=True)
class Action:
    kind: str  # "speak" | "listen" | "hangup"
    text: str | None = None
    source: str | None = None
    from_cache: bool = True


@dataclass(frozen=True)
class VoterSaid:
    text: str
    confidence: float = 1.0


@dataclass(frozen=True)
class Silence:
    seconds: float = 4.0


@dataclass(frozen=True)
class Hangup:
    pass


Event = VoterSaid | Silence | Hangup


class Classifier(Protocol):
    """Everything the model is allowed to do, and nothing else.

    Both methods return a label, never prose. `match_answer_bank` returning an id that
    is not in the bank resolves to None, so a hallucination degrades to the fallback.
    """

    def classify_answer(self, field_name: str, utterance: str) -> tuple[str, str]:
        """-> (enum value from schema/answers.schema.json, one-line summary)"""

    def match_answer_bank(self, utterance: str, bank: AnswerBank) -> str | None:
        """-> an entry id from the bank, or None"""


@dataclass
class TurnLog:
    role: str
    text: str
    source: str | None = None
    from_cache: bool = False
    latency_ms: float | None = None
    stt_confidence: float | None = None


@dataclass
class Conversation:
    script: CallScript
    bank: AnswerBank
    guard: SpeechGuard
    classifier: Classifier

    state: State = State.OPEN
    outcome: Outcome = Outcome.IN_PROGRESS
    answers: dict[str, str] = field(default_factory=dict)
    free_text: dict[str, str] = field(default_factory=dict)
    turns: list[TurnLog] = field(default_factory=list)
    bank_hits: list[str] = field(default_factory=list)

    _silences: int = 0
    _clarifications: dict[str, int] = field(default_factory=dict)
    _bank_answers: dict[str, int] = field(default_factory=dict)
    _pending_reask: bool = False
    _opened: bool = False

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> list[Action]:
        """First actions of the call. The disclosure turn always comes first and is
        never conditional — docs/02_COMPLIANCE.md §1.1."""
        self._opened = True
        return [self._speak("OPEN"), Action(kind="listen")]

    @property
    def finished(self) -> bool:
        return self.state is State.END

    @property
    def disclosure_played(self) -> bool:
        return any(t.source == "script:OPEN" for t in self.turns if t.role == "agent")

    # -- event handling ------------------------------------------------------

    def handle(self, event: Event) -> list[Action]:
        if self.state is State.END:
            return []
        if isinstance(event, Hangup):
            self.outcome = Outcome.HANGUP
            self.state = State.END
            return []
        if isinstance(event, Silence):
            return self._on_silence()
        return self._on_utterance(event)

    def _on_silence(self) -> list[Action]:
        self._silences += 1
        if self._silences >= SILENCE_LIMIT:
            return self._finish(State.CLOSE_SHORT, self._partial_outcome())
        if self.state is State.OPEN:
            return [self._speak_current_question_or_advance()]
        return [self._reask_current(), Action(kind="listen")]

    def _on_utterance(self, event: VoterSaid) -> list[Action]:
        text = normalise(event.text)
        self.turns.append(TurnLog(role="voter", text=text, stt_confidence=event.confidence))
        self._silences = 0

        if self.script.is_optout(text):
            return self._finish(State.OPTOUT, Outcome.OPTED_OUT)

        if self.state is State.OPEN:
            return self._advance_from_open(text)

        return self._answer_question(text, event.confidence)

    # -- OPEN ----------------------------------------------------------------

    def _advance_from_open(self, text: str) -> list[Action]:
        # An explicit yes is not required. Anything that is not an opt-out is treated
        # as consent to continue, because rural respondents often answer the question
        # rather than the permission request.
        first = self.script.question_ids[0]
        self.state = State(first)
        return [self._speak(first), Action(kind="listen")]

    # -- questions -----------------------------------------------------------

    def _answer_question(self, text: str, confidence: float) -> list[Action]:
        qid = self.state.value
        turn = self.script.turn(qid)
        field_name = turn.field or qid.lower()

        # Ordering, and why it is this ordering.
        #
        # Consulting the whole answer bank first looks friendlier but breaks the common
        # case: "रस्ता खराब आहे आणि पथदिवे लागत नाहीत" trips the streetlight entry, the
        # agent answers a question nobody asked, and the roads answer is lost.
        #
        # Classifying first breaks a different case: "मी इथे राहत नाही, चुकीचा नंबर
        # आहे" is neither a question nor an answer, and gets filed as an answer while
        # the call ploughs on — the one thing a person who says it definitely does not
        # want.
        #
        # So: call-control statements always, questions when they look like questions,
        # everything else classified, and the bank as a last resort when the classifier
        # could not make sense of it.
        control = self._try_answer_bank(qid, text, control_only=True)
        if control is not None:
            return control

        asking = self.script.is_question(text)

        if asking:
            actions = self._try_answer_bank(qid, text)
            if actions is not None:
                return actions

        label, summary = self.classifier.classify_answer(field_name, text)
        unclear = label in ("unanswered", "", None) or confidence < 0.4

        if unclear and not asking:
            # Could not classify and it did not look like a question — maybe it was one
            # anyway, phrased flatly. Worth one bank lookup before giving up.
            actions = self._try_answer_bank(qid, text)
            if actions is not None:
                return actions

        if unclear and self._clarifications.get(qid, 0) < MAX_CLARIFICATIONS_PER_QUESTION:
            self._clarifications[qid] = self._clarifications.get(qid, 0) + 1
            return [self._reask_current(), Action(kind="listen")]

        self._record(qid, field_name, label or "unanswered", summary, text)
        actions = [self._ack()]
        return actions + self._advance_question(qid)

    def _try_answer_bank(
        self, qid: str, text: str, *, control_only: bool = False
    ) -> list[Action] | None:
        """-> actions if the bank handled it, None to fall through to classification."""
        if control_only:
            candidates = self.bank.control_candidates(text)
            entry = candidates[0] if candidates else None
        else:
            # The per-question cap stops a voter who keeps asking from consuming the
            # whole call. It does not apply to control statements — "wrong number"
            # must work however many times it is said.
            if self._bank_answers.get(qid, 0) >= MAX_BANK_ANSWERS_PER_QUESTION:
                return None
            entry = self.bank.resolve(self.classifier.match_answer_bank(text, self.bank))

        if entry is None:
            return None

        self._bank_answers[qid] = self._bank_answers.get(qid, 0) + 1
        self.bank_hits.append(entry.id)
        actions = [self._speak_text(entry.text, f"bank:{entry.id}")]

        if entry.is_optout:
            self.state = State.END
            self.outcome = Outcome.OPTED_OUT
            return actions + [Action(kind="hangup")]
        if entry.ends_call:
            return actions + self._finish(State.CLOSE_SHORT, self._partial_outcome())
        # Answered their question; now ask ours again.
        return actions + [self._speak(qid), Action(kind="listen")]

    def _partial_outcome(self) -> Outcome:
        """A call that collected answers and then went quiet is a completed call with
        gaps, not a silent call. Reporting it as `silence` would understate the
        campaign's real completion rate."""
        return Outcome.COMPLETED if self.answers or self.free_text else Outcome.SILENCE

    def _record(self, qid: str, field_name: str, label: str, summary: str, raw: str) -> None:
        if field_name == "open_grievance_text":
            self.free_text["open_grievance_text"] = raw
            self.free_text["open_grievance_category"] = label
            return
        self.answers[field_name] = label
        # Q2 asks about roads and streetlights together, so one utterance fills two
        # schema fields. An unclassifiable roads answer must leave lights unanswered —
        # inferring "ok" there would manufacture data, and this record is what an MLA's
        # office acts on.
        if field_name == "roads" and "lights" not in self.answers:
            if label == "unanswered":
                self.answers["lights"] = "unanswered"
            else:
                self.answers["lights"] = "bad" if label in ("bad", "very_bad") else "ok"
        if field_name == "scheme_issue" and label not in ("none", "unanswered"):
            self.free_text["scheme_issue_text"] = raw
        if summary:
            self.free_text.setdefault(f"{field_name}_summary", summary)

    def _advance_question(self, qid: str) -> list[Action]:
        ids = self.script.question_ids
        idx = ids.index(qid)
        if idx + 1 < len(ids):
            nxt = ids[idx + 1]
            self.state = State(nxt)
            return [self._speak(nxt), Action(kind="listen")]
        return self._finish(State.CLOSE, Outcome.COMPLETED)

    def _speak_current_question_or_advance(self) -> Action:
        first = self.script.question_ids[0]
        self.state = State(first)
        return self._speak(first)

    def _reask_current(self) -> Action:
        qid = self.state.value
        if qid in self.script.turns and self.script.turns[qid].short:
            return self._speak_text(self.script.clarification_for(qid), f"clarification:{qid}")
        return self._speak(qid)

    # -- terminal ------------------------------------------------------------

    def _finish(self, closing: State, outcome: Outcome) -> list[Action]:
        self.state = State.END
        self.outcome = outcome
        return [self._speak(closing.value), Action(kind="hangup")]

    # -- speech --------------------------------------------------------------

    def _ack(self) -> Action:
        variants = self.script.acknowledgements
        if not variants:
            return Action(kind="speak", text=None)
        idx = len([t for t in self.turns if t.source and t.source.startswith("ack:")])
        pick = variants[idx % len(variants)]
        return self._speak_text(pick, f"ack:{idx % len(variants)}")

    def _speak(self, turn_id: str) -> Action:
        turn = self.script.turn(turn_id)
        return self._speak_text(turn.text, f"script:{turn_id}")

    def _speak_text(self, text: str, source: str) -> Action:
        # Every outbound string passes the guard here, before it can reach TTS.
        safe = self.guard.assert_speakable(text)
        self.turns.append(TurnLog(role="agent", text=safe, source=source, from_cache=True))
        return Action(kind="speak", text=safe, source=source, from_cache=True)
