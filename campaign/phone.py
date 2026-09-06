"""Indian phone number normalisation.

Voter lists are not clean. A real one arrives as an export from three different
systems and contains `+91 98765-43210`, `098765 43210`, `9876543210.0` (Excel ate it
as a float), `9999999999` (someone filled the field to get past a form), and landline
numbers with STD codes.

Every one of those has to resolve to the same canonical string or become a *reasoned*
rejection, because two things depend on it: the opt-out ledger only works if the same
person is the same key every time, and a wrongly-parsed number means calling a stranger
in an MLA's voice.

Canonical form is E.164: `+919876543210`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_NON_DIGIT = re.compile(r"[^\d+]")

# Indian mobile numbers are 10 digits beginning 6, 7, 8 or 9 (TRAI National Numbering
# Plan). 2-5 are landline trunk prefixes and are handled separately below.
_MOBILE_START = ("6", "7", "8", "9")


class Reject(str, Enum):
    EMPTY = "empty"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    NOT_MOBILE = "not_mobile"
    PLACEHOLDER = "placeholder"
    BAD_COUNTRY_CODE = "bad_country_code"


@dataclass(frozen=True)
class PhoneResult:
    ok: bool
    e164: str | None = None
    reason: Reject | None = None
    original: str = ""

    def __bool__(self) -> bool:
        return self.ok


def _is_placeholder(ten: str) -> bool:
    """Junk that is syntactically a valid mobile number but obviously is not one.

    Every large Indian contact list has these. Dialling them wastes telephony spend on
    numbers that either do not exist or belong to someone who never gave you anything.
    """
    if len(set(ten)) == 1:  # 9999999999
        return True
    if ten in {"9876543210", "1234567890", "0123456789"}:
        return True
    # Ascending or descending runs: 9876543210 caught above, but 6789012345 etc.
    deltas = {(int(b) - int(a)) % 10 for a, b in zip(ten, ten[1:])}
    return deltas in ({1}, {9})


def normalise(raw: str | int | float | None) -> PhoneResult:
    original = "" if raw is None else str(raw).strip()
    if not original:
        return PhoneResult(False, reason=Reject.EMPTY, original=original)

    text = original
    # Excel turns a phone column into floats: 9876543210.0
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    # Excel also produces 9.87654321e+09
    if "e+" in text.lower():
        try:
            text = str(int(float(text)))
        except ValueError:
            pass

    text = _NON_DIGIT.sub("", text)
    # A '+' anywhere but the front is noise, not a country code.
    text = "+" + text.replace("+", "") if text.startswith("+") else text.replace("+", "")

    digits = text.lstrip("+")

    # Strip the country code in any of the forms it arrives in.
    if digits.startswith("0091"):
        digits = digits[4:]
    elif digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif text.startswith("+") and not digits.startswith("91"):
        return PhoneResult(False, reason=Reject.BAD_COUNTRY_CODE, original=original)

    # Domestic trunk prefix.
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    if len(digits) < 10:
        return PhoneResult(False, reason=Reject.TOO_SHORT, original=original)
    if len(digits) > 10:
        return PhoneResult(False, reason=Reject.TOO_LONG, original=original)
    # Placeholder before series, so `1234567890` is reported as junk somebody typed
    # rather than as a landline. The office reads these reasons and acts on them; the
    # two call for different actions.
    if _is_placeholder(digits):
        return PhoneResult(False, reason=Reject.PLACEHOLDER, original=original)
    if digits[0] not in _MOBILE_START:
        # Landlines are legitimate constituents, but they need an STD code we do not
        # have and they behave differently on an autodialer. Rejected with a reason so
        # the office can decide, rather than silently dropped.
        return PhoneResult(False, reason=Reject.NOT_MOBILE, original=original)

    return PhoneResult(True, e164=f"+91{digits}", original=original)


def mask(e164: str) -> str:
    """`+919876543210` -> `+9198765•••10`.

    For logs and any screen someone might photograph. The full number belongs in the
    database and the grievance list the office works from, not in a terminal scrollback.
    """
    if not e164 or len(e164) < 8:
        return "•" * len(e164 or "")
    return f"{e164[:8]}{'•' * (len(e164) - 10)}{e164[-2:]}"
