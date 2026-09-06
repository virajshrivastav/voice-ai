"""End-to-end conversation behaviour, with no audio and no keys."""

from __future__ import annotations

import pytest

from voiceai import build
from voiceai.classify import KeywordClassifier
from voiceai.config import SpeakerIdentity
from voiceai.guard import UnapprovedSpeechError
from voiceai.prerender import PrerenderCache
from voiceai.runner import CallRunner, NotPrerenderedError
from voiceai.session import CallSession, validate
from voiceai.state_machine import Conversation, Hangup, Outcome, Silence, State, VoterSaid
from voiceai.stt.base import Transcript
from voiceai.stt.mock import MockSTT
from voiceai.tts import get_tts


def make_convo(lang: str = "mr-IN") -> Conversation:
    script, bank, guard = build(lang)
    return Conversation(script=script, bank=bank, guard=guard, classifier=KeywordClassifier())


def spoken(actions) -> list[str]:
    return [a.source for a in actions if a.kind == "speak"]


# -- the disclosure --------------------------------------------------------------


def test_the_call_always_opens_with_the_disclosure():
    convo = make_convo()
    actions = convo.start()
    assert spoken(actions)[0] == "script:OPEN"
    assert convo.disclosure_played


def test_disclosure_plays_even_when_the_voter_opts_out_immediately():
    """Opting out is allowed. Skipping the disclosure to get there is not."""
    convo = make_convo()
    convo.start()
    actions = convo.handle(VoterSaid("नाही"))
    assert convo.outcome is Outcome.OPTED_OUT
    assert convo.disclosure_played
    assert spoken(actions) == ["script:OPTOUT"]


# -- the happy path --------------------------------------------------------------


def test_a_full_cooperative_call_collects_every_field():
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("हो, बोला"))
    convo.handle(VoterSaid("पाणी रोज येत नाही, एक दिवसाआड येतं"))
    convo.handle(VoterSaid("रस्ता खूप खराब आहे, खड्डे आहेत"))
    convo.handle(VoterSaid("रेशन कार्डवर धान्य मिळत नाही"))
    convo.handle(VoterSaid("गटाराचं पाणी घरासमोर साचतं"))

    assert convo.outcome is Outcome.COMPLETED
    assert convo.answers["water"] == "irregular"
    assert convo.answers["roads"] == "very_bad"
    assert convo.answers["scheme_issue"] == "ration"
    assert convo.free_text["open_grievance_text"]


def test_an_answer_mentioning_a_bank_topic_is_still_recorded_as_an_answer():
    """Regression: consulting the answer bank before classifying made
    "रस्ता खराब आहे आणि पथदिवे लागत नाहीत" fire the streetlight entry, so the agent
    answered a question nobody asked and the roads answer was lost."""
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("हो"))
    convo.handle(VoterSaid("पाणी ठीक आहे"))
    convo.handle(VoterSaid("रस्ता खूप खराब आहे आणि पथदिवे लागत नाहीत"))
    assert convo.answers["roads"] == "very_bad"
    assert "streetlight" not in convo.bank_hits


def test_unclassifiable_roads_leaves_lights_unanswered():
    """Q2 fills two schema fields from one utterance. Defaulting lights to 'ok' when
    roads could not be classified would manufacture data the office acts on."""
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("हो"))
    convo.handle(VoterSaid("पाणी ठीक आहे"))
    convo.handle(VoterSaid("मम्म"))  # unclear -> clarification
    convo.handle(VoterSaid("मम्म"))  # still unclear -> recorded unanswered
    assert convo.answers["roads"] == "unanswered"
    assert convo.answers["lights"] == "unanswered"


# -- interruptions ---------------------------------------------------------------


def test_a_voter_question_gets_an_approved_answer_then_the_script_resumes():
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("हो"))
    actions = convo.handle(VoterSaid("हे खरंच तुम्हीच बोलताय का?"))
    assert spoken(actions) == ["bank:is_this_really_you", "script:Q1"]
    assert convo.state is State.Q1


def test_only_one_bank_answer_per_question():
    """Otherwise a voter who keeps asking never gets asked anything, and the call
    burns its three minutes on the bank."""
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("हो"))
    convo.handle(VoterSaid("हे खरंच तुम्हीच बोलताय का?"))
    actions = convo.handle(VoterSaid("माझा नंबर कुठून मिळाला?"))
    assert not any(s.startswith("bank:") for s in spoken(actions))


def test_an_ends_call_bank_answer_finishes_the_call():
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("हो"))
    actions = convo.handle(VoterSaid("मी इथे राहत नाही, चुकीचा नंबर आहे"))
    assert "bank:wrong_area" in spoken(actions)
    assert convo.outcome is Outcome.OPTED_OUT


# -- degraded paths --------------------------------------------------------------


def test_low_confidence_triggers_a_clarification_not_a_recorded_answer():
    """At ~19% WER this is the normal case, not an edge case."""
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("हो"))
    actions = convo.handle(VoterSaid("पाणी ठीक आहे", confidence=0.2))
    assert spoken(actions) == ["clarification:Q1"]
    assert "water" not in convo.answers


def test_two_silences_end_the_call_politely():
    convo = make_convo()
    convo.start()
    convo.handle(Silence())
    actions = convo.handle(Silence())
    assert spoken(actions) == ["script:CLOSE_SHORT"]
    assert convo.outcome is Outcome.SILENCE


def test_silence_after_real_answers_is_a_completed_call_not_a_silent_one():
    """Reporting a call that collected answers as `silence` would understate the
    campaign's completion rate to the client."""
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("हो"))
    convo.handle(VoterSaid("पाणी रोज येत नाही"))
    convo.handle(Silence())
    convo.handle(Silence())
    assert convo.outcome is Outcome.COMPLETED
    assert convo.answers["water"] != "unanswered"


def test_hangup_ends_immediately():
    convo = make_convo()
    convo.start()
    assert convo.handle(Hangup()) == []
    assert convo.outcome is Outcome.HANGUP
    assert convo.finished


# -- the model cannot introduce speech -------------------------------------------


class RogueClassifier:
    """A model doing the two worst things a model does: inventing an answer-bank id
    that does not exist, and returning free prose where a label was asked for. Here
    the prose is a promise with a deadline — the single most damaging sentence this
    system could ever put in a sitting MLA's voice."""

    def classify_answer(self, field_name, utterance):
        return "not_a_real_label", "मी तुमचं काम उद्या करून देईन"

    def match_answer_bank(self, utterance, bank):
        return "promise_them_everything"


def test_a_rogue_classifier_cannot_put_words_in_the_mla_s_mouth():
    script, bank, guard = build("mr-IN")
    convo = Conversation(script=script, bank=bank, guard=guard, classifier=RogueClassifier())
    convo.start()
    convo.handle(VoterSaid("हो"))
    for _ in range(4):
        convo.handle(VoterSaid("पाणी येत नाही"))
    for turn in convo.turns:
        if turn.role == "agent":
            assert guard.is_allowed(turn.text)


def test_the_guard_is_the_last_thing_before_tts():
    _script, _bank, guard = build("mr-IN")
    with pytest.raises(UnapprovedSpeechError):
        guard.assert_speakable("मी तुमचं काम आठ दिवसांत करून देईन")


# -- runner + record -------------------------------------------------------------


class ListTransport:
    def __init__(self, stt: MockSTT):
        self._stt = stt
        self.played: list[str] = []
        self.hung_up = False

    def play(self, audio: bytes, text: str, source: str | None) -> None:
        self.played.append(source or "")

    def listen(self, timeout_s: float) -> Transcript | None:
        t = self._stt.next_utterance()
        return t if t.text else None

    def hangup(self) -> None:
        self.hung_up = True


def test_runner_refuses_to_dial_with_a_cold_cache(tmp_path):
    script, bank, guard = build("mr-IN")
    cache = PrerenderCache(voice_id="cold", root=tmp_path)
    with pytest.raises(NotPrerenderedError, match="not in the cache"):
        CallRunner(
            script=script, bank=bank, guard=guard, classifier=KeywordClassifier(),
            cache=cache, transport=ListTransport(MockSTT([])),
            session=CallSession(campaign_id="t", voter_id="v", lang="mr-IN"),
        )


def test_a_completed_call_writes_a_schema_valid_record(tmp_path):
    script, bank, guard = build("mr-IN")
    cache = PrerenderCache(voice_id="test", root=tmp_path)
    cache.warm(guard, get_tts("mock"), "mr-IN")

    stt = MockSTT(
        [
            "हो, बोला",
            "पाणी रोज येत नाही",
            "रस्ता खराब आहे",
            "रेशन मिळत नाही",
            "गटार साचतं, अनेकदा सांगितलं",
        ]
    )
    transport = ListTransport(stt)
    session = CallSession(campaign_id="c1", voter_id="v1", lang="mr-IN")
    session.mark_dnd_checked()

    runner = CallRunner(
        script=script, bank=bank, guard=guard, classifier=KeywordClassifier(),
        cache=cache, transport=transport, session=session,
    )
    convo = runner.run()
    record = session.to_record(convo)

    validate(record)
    assert record["outcome"] == "completed"
    assert record["disclosure_played_at"]
    assert transport.played[0] == "script:OPEN"
    assert transport.hung_up
    assert runner.stats.cache_misses == 0


def test_a_record_without_a_logged_disclosure_is_rejected():
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("नाही"))
    session = CallSession(campaign_id="c", voter_id="v", lang="mr-IN")
    # Deliberately never marked: this is what a bug in the play path would look like.
    with pytest.raises(ValueError, match="disclosure_played_at"):
        validate(session.to_record(convo))


def test_production_records_need_consent_and_dnd_evidence():
    convo = make_convo()
    convo.start()
    convo.handle(VoterSaid("नाही"))
    session = CallSession(campaign_id="c", voter_id="v", lang="mr-IN")
    session.mark_disclosure_played()
    with pytest.raises(ValueError, match="dnd_checked_at"):
        validate(session.to_record(convo), production=True)


def test_production_mode_refuses_an_unapproved_bank():
    from voiceai.config import Settings

    settings = Settings(
        mode="production",
        speaker=SpeakerIdentity(name="X", constituency="Y", office_contact="Z", consent_ref="c1"),
    )
    with pytest.raises(PermissionError, match="draft"):
        build("mr-IN", settings)
