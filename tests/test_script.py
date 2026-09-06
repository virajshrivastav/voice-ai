"""Opt-out and question detection.

The opt-out cases are regression tests for a live bug: `docs/02_COMPLIANCE.md §1.3`
specifies opt-out as the word "नाही/नहीं/no/stop", and implementing that as a substring
match ended the call on "पाणी रोज येत नाही" — a voter answering the water question.
Marathi and Hindi negate by appending that token to the verb, so the most common
answer shape and the opt-out keyword are the same word. If someone "simplifies"
IntentMatcher back to `in`, these fail.
"""

from __future__ import annotations

import pytest

from voiceai import build


@pytest.fixture(scope="module")
def mr():
    return build("mr-IN")[0]


@pytest.fixture(scope="module")
def hi():
    return build("hi-IN")[0]


@pytest.mark.parametrize(
    "utterance",
    [
        "नाही",
        "नको",
        "नाही नको",
        "नको मला",
        "मला बोलायचं नाही",
        "फोन ठेवा",
        "not interested",
        "नाही.",
    ],
)
def test_marathi_optout_detected(mr, utterance):
    assert mr.is_optout(utterance)


@pytest.mark.parametrize(
    "utterance",
    [
        "पाणी रोज येत नाही, एक दिवसाआड येतं",
        "रस्ता चांगला नाही",
        "रेशन मिळत नाही, दुकानदार टाळाटाळ करतो",
        "पथदिवे लागत नाहीत",
        "लाडकी बहीण योजनेचा हप्ता आलाच नाही",
        "हो, बोला",
        "काही अडचण नाही",
    ],
)
def test_marathi_answers_are_not_optouts(mr, utterance):
    """Every one of these is a voter answering a question. Hanging up on any of them
    loses the grievance and the call."""
    assert not mr.is_optout(utterance)


@pytest.mark.parametrize(
    "utterance,expected",
    [
        ("नहीं", True),
        ("नहीं चाहिए", True),
        ("बंद करो", True),
        ("पानी रोज़ नहीं आता", False),
        ("सड़क अच्छी नहीं है", False),
        ("राशन नहीं मिलता", False),
        ("हाँ, बोलिए", False),
    ],
)
def test_hindi_optout(hi, utterance, expected):
    assert hi.is_optout(utterance) is expected


@pytest.mark.parametrize(
    "utterance,expected",
    [
        ("हे खरंच तुम्हीच बोलताय का?", True),
        ("माझा नंबर कुठून मिळाला तुम्हाला?", True),
        ("तुम्ही कधी येणार", True),
        ("रस्ता खराब आहे", False),
        ("पाणी रोज येत नाही", False),
        ("काही नाही, एवढंच", False),
    ],
)
def test_marathi_question_detection(mr, utterance, expected):
    """Drives whether the answer bank is consulted. False positives make the agent
    answer questions nobody asked and drop the real answer."""
    assert mr.is_question(utterance) is expected


def test_kaay_inside_a_word_is_not_a_question(mr):
    """Token matching, not substring: 'काही' contains 'का' but is not interrogative."""
    assert not mr.is_question("काही अडचण नाही")


def test_every_script_has_a_disclosure_turn(mr, hi):
    for script in (mr, hi):
        assert script.disclosure_turn.id == "OPEN"
        assert script.disclosure_turn.text


def test_clarification_slot_comes_only_from_the_script(mr):
    """The one runtime-built string. Its slot must be filled from a `short:` field, so
    the set of possible clarifications is finite and known before the call."""
    for turn_id in mr.question_ids:
        text = mr.clarification_for(turn_id)
        assert mr.turn(turn_id).short in text
        assert "{" not in text
