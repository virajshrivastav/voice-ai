"""Answer bank: the approval gate, the tamper check, and the content rules.

The content tests are the ones worth keeping. They encode what an MLA's office is
actually buying — a voice that records grievances and never commits to anything — and
they will fail the moment someone writes a helpful-sounding sentence like "we will fix
it this week" into the bank.
"""

from __future__ import annotations

import re

import pytest

from voiceai import build
from voiceai.answer_bank import AnswerBank, BankNotApprovedError, load_answer_bank
from voiceai.config import SpeakerIdentity

LANGS = ["mr-IN", "hi-IN"]

# Deadline and promise language. These are heuristics over two languages, so they are
# deliberately narrow: a hit is a definite problem, a miss is not a clean bill.
FORBIDDEN = {
    "deadline": [
        r"दिवसांत", r"दिवसात", r"आठवड्यात", r"महिन्यात", r"लवकरच",
        r"दिनों में", r"हफ़्ते में", r"हफ्ते में", r"महीने में", r"जल्द",
    ],
    "promise": [
        r"करून देईन", r"करून देतो", r"मंजूर करतो", r"होईलच", r"नक्की होईल",
        r"करवा दूंगा", r"दिलवा दूंगा", r"हो जाएगा", r"ज़रूर होगा", r"जरूर होगा",
    ],
    "money": [r"₹", r"\bरुपये\b", r"\bरुपए\b"],
}

MAX_CHARS = 260
MAX_SENTENCES = 3  # two plus a trailing office contact


@pytest.fixture(params=LANGS)
def bank(request) -> AnswerBank:
    return load_answer_bank(request.param, SpeakerIdentity(name="", constituency="", office_contact=""))


def test_bank_starts_unapproved_and_says_so(bank):
    """Ships as a draft on purpose. Nobody should be able to run production against
    text no human has signed."""
    assert not bank.is_approved
    with pytest.raises(BankNotApprovedError, match="draft"):
        bank.require_approved()


def test_approval_is_invalidated_by_editing_an_answer(bank):
    bank.approval = {
        "status": "approved",
        "approved_by": "Test Officer",
        "approved_text_sha256": bank.content_hash(),
    }
    bank.require_approved()  # clean

    entry = next(iter(bank.entries.values()))
    bank.entries[entry.id] = type(entry)(**{**entry.__dict__, "text": entry.text + " आणि आणखी"})
    with pytest.raises(BankNotApprovedError, match="changed after approval"):
        bank.require_approved()


def test_approved_without_a_named_approver_is_refused(bank):
    bank.approval = {"status": "approved", "approved_by": None}
    with pytest.raises(BankNotApprovedError, match="approved_by"):
        bank.require_approved()


@pytest.mark.parametrize("rule", sorted(FORBIDDEN))
def test_no_answer_makes_a_promise_a_deadline_or_an_offer(bank, rule):
    offenders = [
        (e.id, pattern)
        for e in bank.entries.values()
        for pattern in FORBIDDEN[rule]
        if re.search(pattern, e.text)
    ]
    assert not offenders, f"{rule} language in answer bank: {offenders}"


def test_answers_are_short_enough_for_a_phone_line(bank):
    too_long = [(e.id, len(e.text)) for e in bank.entries.values() if len(e.text) > MAX_CHARS]
    assert not too_long, f"answers over {MAX_CHARS} chars: {too_long}"

    wordy = [
        (e.id, n)
        for e in bank.entries.values()
        if (n := len([s for s in re.split(r"[।.?!]", e.text) if s.strip()])) > MAX_SENTENCES
    ]
    assert not wordy, f"answers over {MAX_SENTENCES} sentences: {wordy}"


def test_the_mandatory_disclosure_answers_exist(bank):
    """Two questions every real caller asks, both with compliance weight: is this
    really you, and where did you get my number."""
    for required in ("is_this_really_you", "where_did_you_get_my_number"):
        assert required in bank.entries, f"missing required answer: {required}"
        assert "mandatory" in bank.entries[required].tags


def test_both_languages_carry_the_same_ids():
    mr = load_answer_bank("mr-IN", SpeakerIdentity(name="", constituency="", office_contact=""))
    hi = load_answer_bank("hi-IN", SpeakerIdentity(name="", constituency="", office_contact=""))
    assert set(mr.entries) == set(hi.entries), "Hindi and Marathi banks have drifted apart"


def test_a_hallucinated_id_resolves_to_nothing(bank):
    """The classifier can return any string. None of them can become speech."""
    for made_up in ("water_tanker_v2", "PROMISE_EVERYTHING", "", "NONE", "'; DROP TABLE"):
        assert bank.resolve(made_up) is None


def test_keyword_candidates_prefer_the_most_specific_match(bank):
    if bank.lang != "mr-IN":
        pytest.skip("marathi phrasing")
    hits = bank.keyword_candidates("लाडकी बहीण योजनेचा हप्ता आलाच नाही")
    assert hits and hits[0].id == "ladki_bahin"


def test_guard_covers_every_bank_answer():
    """Belt and braces: anything in the bank must also be speakable, or a matched
    answer would crash the call instead of playing."""
    for lang in LANGS:
        _script, bank, guard = build(lang)
        for entry in bank.entries.values():
            assert guard.is_allowed(entry.text), f"{lang}:{entry.id} not in guard"
