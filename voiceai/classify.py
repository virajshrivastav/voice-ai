"""Answer classification.

Two implementations of the same narrow contract:

  * `KeywordClassifier` — no model, no key, no network. Runs the whole conversation
    offline, and is what the tests use.
  * `LLMClassifier` — a constrained call to an OpenAI-compatible chat endpoint
    (Sarvam's, or anything else). It may return one label from a fixed set, or one id
    from the answer bank, or NONE. It cannot return prose, and nothing it returns is
    ever spoken directly.

If the LLM errors, times out, or returns something unrecognised, we fall back to the
keyword classifier rather than failing the call. A degraded label is recoverable; a
dropped call to a voter is not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .answer_bank import AnswerBank
from .script import normalise

# Enum values from schema/answers.schema.json. Kept here so a schema change breaks a
# test rather than silently producing records that fail validation.
FIELD_ENUMS: dict[str, tuple[str, ...]] = {
    "water": ("ok", "irregular", "none", "other", "unanswered"),
    "roads": ("ok", "bad", "very_bad", "unanswered"),
    "lights": ("ok", "bad", "unanswered"),
    "scheme_issue": ("none", "ration", "pension", "ladki_bahin", "housing", "other", "unanswered"),
    "open_grievance_text": ("low", "medium", "high", "unanswered"),
}

# Marathi + Hindi surface forms per label. Both languages live in one table because a
# voter in Sambhajinagar routinely code-mixes inside a single sentence.
_CUES: dict[str, dict[str, tuple[str, ...]]] = {
    "water": {
        "ok": ("रोज येतं", "रोज येते", "व्यवस्थित", "ठीक आहे", "बरोबर आहे", "रोज आती", "ठीक है"),
        "irregular": ("कधी कधी", "अडचण", "अनियमित", "एक दिवसाआड", "कमी वेळ",
                      "कभी कभी", "दिक्कत", "अनियमित", "एक दिन छोड"),
        "none": ("येतच नाही", "पाणी नाही", "बंद आहे", "टँकर", "आतच नहीं", "पानी नहीं", "टैंकर"),
    },
    "roads": {
        "ok": ("चांगले", "ठीक आहे", "बरे आहेत", "अच्छी", "ठीक है"),
        "bad": ("खराब", "खड्डे", "तुटलेला", "गड्ढे", "टूटी"),
        "very_bad": ("खूप खराब", "फार खराब", "चालता येत नाही", "बहुत खराब", "चल नहीं"),
    },
    "lights": {
        "ok": ("लागतात", "चालू आहेत", "जलती", "ठीक"),
        "bad": ("लागत नाहीत", "बंद", "अंधार", "नहीं जलती", "अँधेरा"),
    },
    "scheme_issue": {
        "none": ("काही नाही", "अडचण नाही", "सगळं ठीक", "कोई नहीं", "दिक्कत नहीं"),
        "ration": ("रेशन", "धान्य", "राशन", "अनाज"),
        "pension": ("पेन्शन", "निवृत्ती", "पेंशन", "वृद्धावस्था"),
        "ladki_bahin": ("लाडकी बहीण", "लाडकी", "बहीण योजना", "बहन योजना"),
        "housing": ("घरकुल", "आवास", "घर मंजूर"),
    },
}

_HIGH_PRIORITY = ("तातडी", "जीव", "मृत्यू", "अपघात", "रुग्ण", "तुरंत", "जान", "हादसा", "मरीज")
_MEDIUM_PRIORITY = ("महिने", "वर्ष", "अनेकदा", "महीने", "साल", "कई बार")

_NEGATIVE = ("नाही", "नको", "नहीं", "no")


@dataclass
class KeywordClassifier:
    """Deterministic, offline, and honest about it: when it cannot tell, it says
    `unanswered`, which routes the conversation to a clarification rather than to a
    confidently wrong record."""

    def classify_answer(self, field_name: str, utterance: str) -> tuple[str, str]:
        text = normalise(utterance).lower()
        if not text:
            return "unanswered", ""

        if field_name == "open_grievance_text":
            return self._priority(text), text[:160]

        cues = _CUES.get(field_name, {})
        best: tuple[int, str] | None = None
        for label, phrases in cues.items():
            for phrase in phrases:
                if phrase in text:
                    score = len(phrase)
                    if best is None or score > best[0]:
                        best = (score, label)
        if best:
            return best[1], text[:160]

        # "no problem" style answers land here for scheme_issue and water.
        if field_name == "scheme_issue" and any(n in text for n in _NEGATIVE):
            return "none", text[:160]
        if field_name in FIELD_ENUMS and "other" in FIELD_ENUMS[field_name] and len(text) > 12:
            return "other", text[:160]
        return "unanswered", text[:160]

    def _priority(self, text: str) -> str:
        if any(k in text for k in _HIGH_PRIORITY):
            return "high"
        if any(k in text for k in _MEDIUM_PRIORITY):
            return "medium"
        return "low" if text else "unanswered"

    def match_answer_bank(self, utterance: str, bank: AnswerBank) -> str | None:
        candidates = bank.keyword_candidates(utterance)
        return candidates[0].id if candidates else None


_SYSTEM_CLASSIFY = (
    "You are labelling a Marathi or Hindi voter's spoken answer for a constituency "
    "survey. Return ONLY a JSON object of the form {{\"label\": \"<one of: {labels}>\", "
    "\"summary\": \"<one short line in the voter's own language>\"}}. Never add "
    "opinions, never invent facts, and use \"unanswered\" when the answer is unclear."
)

_SYSTEM_BANK = (
    "A voter asked something during an automated outreach call. Choose the single id "
    "below that best matches what they asked. Return ONLY a JSON object of the form "
    "{\"id\": \"<id or NONE>\"}. Prefer NONE over a weak match.\n\n{menu}"
)


class LLMClassifier:
    """Constrained classifier over an OpenAI-compatible /chat/completions endpoint."""

    def __init__(
        self,
        client,
        model: str,
        fallback: KeywordClassifier | None = None,
        temperature: float = 0.0,
    ):
        self._client = client  # httpx.Client with base_url and auth already set
        self._model = model
        self._fallback = fallback or KeywordClassifier()
        self._temperature = temperature

    def classify_answer(self, field_name: str, utterance: str) -> tuple[str, str]:
        labels = FIELD_ENUMS.get(field_name)
        if not labels or not normalise(utterance):
            return self._fallback.classify_answer(field_name, utterance)
        try:
            data = self._complete(
                _SYSTEM_CLASSIFY.format(labels=", ".join(labels)), normalise(utterance)
            )
            label = str(data.get("label", "")).strip()
            if label not in labels:
                return self._fallback.classify_answer(field_name, utterance)
            return label, str(data.get("summary", ""))[:200]
        except Exception:  # noqa: BLE001 - never let the model break the call
            return self._fallback.classify_answer(field_name, utterance)

    def match_answer_bank(self, utterance: str, bank: AnswerBank) -> str | None:
        # Cheap path first: an exact trigger hit is both faster and more predictable
        # than a model call, and it costs nothing.
        keyword_hit = self._fallback.match_answer_bank(utterance, bank)
        if keyword_hit:
            return keyword_hit
        try:
            data = self._complete(
                _SYSTEM_BANK.format(menu=bank.intent_menu()), normalise(utterance)
            )
            entry_id = str(data.get("id", "")).strip()
            # bank.resolve() is the real gate; an unknown id becomes None there.
            return None if entry_id in ("", "NONE") else entry_id
        except Exception:  # noqa: BLE001
            return None

    def _complete(self, system: str, user: str) -> dict:
        resp = self._client.post(
            "/chat/completions",
            json={
                "model": self._model,
                "temperature": self._temperature,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        return json.loads(match.group(0) if match else content)
