"""Phone normalisation.

Two things depend on getting this exactly right: the opt-out ledger only works if the
same person is the same key every time, and a mis-parsed number means calling a
stranger in an MLA's voice.
"""

from __future__ import annotations

import pytest

from campaign.phone import Reject, mask, normalise


@pytest.mark.parametrize(
    "raw",
    [
        "9876543211",
        "+919876543211",
        "+91 98765 43211",
        "+91-98765-43211",
        "09876543211",
        "919876543211",
        "00919876543211",
        "  9876543211  ",
        "98765 43211",
        "(987) 654-3211",
        "9876543211.0",       # Excel read the column as a float
    ],
)
def test_every_way_the_same_number_arrives(raw):
    """A real voter list is three systems' exports concatenated. All of these are one
    person, and the opt-out ledger has to agree."""
    result = normalise(raw)
    assert result.ok, f"{raw!r} -> {result.reason}"
    assert result.e164 == "+919876543211"


def test_excel_scientific_notation():
    assert normalise("9.876543211e+09").e164 == "+919876543211"


@pytest.mark.parametrize(
    "raw,reason",
    [
        ("", Reject.EMPTY),
        (None, Reject.EMPTY),
        ("98765", Reject.TOO_SHORT),
        ("98765432110000", Reject.TOO_LONG),
        ("2226543210", Reject.NOT_MOBILE),      # landline series
        ("0240234567", Reject.NOT_MOBILE),      # Sambhajinagar STD code + landline
        ("+14155550123", Reject.BAD_COUNTRY_CODE),
    ],
)
def test_rejections_carry_a_reason(raw, reason):
    """Rejections must say why. If 8% of a constituency silently vanishes at import,
    nobody notices until the MLA asks why his own neighbourhood was never called."""
    result = normalise(raw)
    assert not result.ok
    assert result.reason is reason


@pytest.mark.parametrize(
    "raw", ["9999999999", "8888888888", "9876543210", "1234567890", "6789012345"]
)
def test_placeholder_junk_is_rejected(raw):
    """Every large Indian contact list has these. Dialling them burns telephony spend
    on numbers that do not exist."""
    result = normalise(raw)
    assert not result.ok
    assert result.reason is Reject.PLACEHOLDER


def test_a_real_looking_number_with_repeats_is_kept():
    """Rejecting anything with repeated digits would throw away real numbers."""
    assert normalise("9822011220").ok


def test_mask_hides_the_middle():
    masked = mask("+919876543211")
    assert masked.startswith("+9198765")
    assert masked.endswith("11")
    assert "43" not in masked[8:-2]
