"""The guard is the whole safety argument. If these pass, no unapproved sentence can
reach the cloned voice, whatever the model does."""

from __future__ import annotations

import pytest

from voiceai import build
from voiceai.guard import SpeechGuard, UnapprovedSpeechError


@pytest.fixture(scope="module")
def bundle():
    return build("mr-IN")


def test_every_approved_sentence_passes(bundle):
    script, bank, guard = bundle
    for turn in script.turns.values():
        assert guard.is_allowed(turn.text)
    for ack in script.acknowledgements:
        assert guard.is_allowed(ack)
    for entry in bank.entries.values():
        assert guard.is_allowed(entry.text)
    assert guard.is_allowed(bank.fallback_text)


@pytest.mark.parametrize(
    "text",
    [
        # A promise with a deadline, in the MLA's voice. The exact thing that ends a
        # contract and starts a news cycle.
        "मी तुमचं काम आठ दिवसांत करून देईन",
        # A policy statement.
        "आमचं सरकार सगळ्यांना मोफत पाणी देणार आहे",
        # An attack on an opponent.
        "विरोधी पक्षाने काहीच केलं नाही",
        # A near-miss: real approved text with one word changed.
        "पाण्याची अडचण मी नोंदवून घेणार नाही.",
        "",
        "   ",
    ],
)
def test_unapproved_text_is_refused(bundle, text):
    _script, _bank, guard = bundle
    assert not guard.is_allowed(text)
    with pytest.raises(UnapprovedSpeechError):
        guard.assert_speakable(text)


def test_whitespace_is_normalised_not_a_bypass(bundle):
    script, _bank, guard = bundle
    original = script.turn("Q1").text
    assert guard.assert_speakable(f"  {original}\n\t ") == original


def test_manifest_is_the_certification_artefact(bundle):
    """The finite list of everything the voice can say, which is what makes an
    interactive script pre-certifiable at all (ECI / MCMC)."""
    _script, _bank, guard = bundle
    manifest = guard.manifest()
    assert manifest["count"] == len(guard.items)
    assert len(manifest["sha256"]) == 64
    assert all(e["text"] and e["source"] for e in manifest["entries"])


def test_manifest_hash_changes_when_a_sentence_changes(bundle):
    script, bank, guard = bundle
    before = guard.manifest()["sha256"]
    original = script.turns["Q1"]
    script.turns["Q1"] = type(original)(**{**original.__dict__, "text": original.text + " x"})
    try:
        after = SpeechGuard(script, bank).manifest()["sha256"]
    finally:
        script.turns["Q1"] = original
    assert before != after


def test_guard_refuses_mismatched_languages():
    mr_script, _mr_bank, _ = build("mr-IN")
    _hi_script, hi_bank, _ = build("hi-IN")
    with pytest.raises(ValueError, match="refusing to mix languages"):
        SpeechGuard(mr_script, hi_bank)
