"""Fill a campaign database by running synthetic calls through the REAL system.

    python -m campaign.simulate --voters 2000 --db out/campaign.db

Nothing here fabricates a result. Each simulated voter is driven through the actual
`Conversation` state machine, the actual answer bank, the actual `SpeechGuard` and the
actual record writer — only the microphone is fake, and its transcripts come from pools
of plausible Marathi answers. So the report built on this data exercises the same code
path a real pilot would, and a bug in classification or routing shows up as a wrong
number in the report rather than staying hidden.

The outcome mix is modelled, and every rate is a guess until Stage 2 measures it:
pickup 45% (`docs/00_CONTEXT.md §4`), and of the calls that connect, a distribution
weighted toward cooperation because governance outreach from a named local MLA is not
a cold sales call.

**All data produced here is synthetic.** Names, numbers and grievances are generated.
The ward names are real areas of Chhatrapati Sambhajinagar so the output looks like
what a real report would look like; nothing in it describes a real person.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass
from pathlib import Path

from voiceai import build
from voiceai.classify import KeywordClassifier
from voiceai.config import load_settings
from voiceai.console import setup
from voiceai.costs import per_minute
from voiceai.session import CallSession
from voiceai.state_machine import Conversation, Hangup, Silence, VoterSaid

from .db import insert_voter, record_call, session, upsert_campaign, upsert_politician
from .optout import OptOutLedger

# Real areas of Chhatrapati Sambhajinagar, so the report reads like a real one.
WARDS = [
    "Cidco N-2", "Cidco N-5", "Cidco N-7", "Cidco N-11", "Garkheda", "Ulkanagari",
    "Jyoti Nagar", "Begumpura", "Harsul", "Padegaon", "Mukundwadi", "Chikalthana",
    "Naregaon", "Shahnoorwadi", "Samarth Nagar", "Nirala Bazar", "Kranti Chowk",
    "Osmanpura", "Bhavsinghpura", "Pundaliknagar",
]

FIRST = ["राहुल", "संदीप", "प्रकाश", "सुनीता", "मंगल", "विठ्ठल", "अनिल", "शीतल", "गणेश",
         "कविता", "बाळासाहेब", "रेखा", "नितीन", "आशा", "दत्ता", "स्वाती", "रमेश", "उज्ज्वला",
         "सागर", "पूजा", "माधुरी", "किशोर", "वैशाली", "अशोक"]
LAST = ["जाधव", "पवार", "शिंदे", "कुलकर्णी", "देशमुख", "गायकवाड", "पाटील", "सोनवणे",
        "मोरे", "काळे", "वाघमारे", "बनसोडे", "चव्हाण", "साळवे", "थोरात", "राऊत"]

ANSWERS: dict[str, dict[str, list[str]]] = {
    "water": {
        "ok": ["पाणी रोज येतं, काही अडचण नाही", "व्यवस्थित येतं", "पाणी ठीक आहे"],
        "irregular": [
            "पाणी रोज येत नाही, एक दिवसाआड येतं",
            "कधी कधी येतं, वेळ ठरलेली नाही",
            "पाणी येतं पण कमी वेळ असतं, अडचण होते",
            "आठवड्यातून तीनदाच येतं",
        ],
        "none": [
            "पाणी येतच नाही, टँकर मागवावा लागतो",
            "इथे नळाला पाणी नाही, टँकरवर आहोत",
            "दोन महिने झाले पाणी नाही",
        ],
    },
    "roads": {
        "ok": ["रस्ता चांगला आहे", "रस्ते ठीक आहेत, पथदिवेही लागतात"],
        "bad": [
            "रस्ता खराब आहे, खड्डे आहेत",
            "रस्त्यावर खड्डे पडले आहेत आणि पथदिवे लागत नाहीत",
            "डांबरीकरण होऊन बरीच वर्षं झाली",
        ],
        "very_bad": [
            "रस्ता खूप खराब आहे, चालता येत नाही",
            "फार खराब अवस्था आहे, पावसाळ्यात तर चिखलच होतो",
            "रस्ता खूप खराब आहे आणि अंधार असतो",
        ],
    },
    "scheme_issue": {
        "none": ["काही अडचण नाही", "सगळं ठीक आहे", "कोणतीही अडचण नाही"],
        "ration": [
            "रेशन कार्डवर धान्य मिळत नाही, दुकानदार टाळाटाळ करतो",
            "रेशन कार्ड अजून झालेलं नाही",
            "धान्य कमी देतात, विचारलं तर उत्तर मिळत नाही",
        ],
        "pension": [
            "पेन्शनचे पैसे तीन महिने आलेले नाहीत",
            "वृद्धापकाळ पेन्शनचा अर्ज केला पण काहीच झालं नाही",
        ],
        "ladki_bahin": [
            "लाडकी बहीण योजनेचा हप्ता आलाच नाही",
            "लाडकी बहीण योजनेत नाव आहे पण पैसे येत नाहीत",
        ],
        "housing": [
            "घरकुल मंजूर झालं पण अजून काम सुरू नाही",
            "घरकुलाच्या यादीत नाव नाही, अनेकदा अर्ज केला",
        ],
    },
}

# Grouped by the priority band `KeywordClassifier` will assign, and weighted so the
# mix is realistic: most grievances are chronic annoyances, a few are genuinely urgent.
# A flat list produced 120 identical "high" rows at the top of the report, which is
# both ugly and a lie about what a real constituency sounds like.
GRIEVANCES: dict[str, list[str]] = {
    "high": [
        "तातडीने रुग्णवाहिका मिळाली नाही, खूप त्रास झाला",
        "उघड्या गटारात मुलगा पडला, जीव वाचला पण धोका कायम आहे",
        "वळणावर दिवा नाही, तिथे वारंवार अपघात होतात",
        "विजेच्या तारा लोंबकळत आहेत, कधीही अपघात होईल",
        "पिण्याच्या पाण्यामुळे लहान मुलं आजारी पडली, रुग्णालयात न्यावं लागलं",
        "मोकाट कुत्र्याने मुलाला चावा घेतला, तातडीने काहीतरी करा",
        "रुग्णाला न्यायला वेळेत गाडी मिळत नाही, जीवावर बेतू शकतं",
    ],
    "medium": [
        "गटाराचं पाणी घरासमोर साचतं, अनेकदा सांगितलं पण काही झालं नाही",
        "दोन वर्षं झाली रस्त्याचं काम सुरूच झालेलं नाही",
        "अनेकदा अर्ज केला, दर महिन्याला हेलपाटे मारावे लागतात",
        "सहा महिने झाले पथदिवे बंद आहेत",
        "कचरा गाडी अनेकदा येतच नाही, दुर्गंधी वाढली आहे",
        "वर्षभरापासून नाल्याचं काम अर्धवट आहे",
        "शेतीच्या नुकसानभरपाईचे पैसे अनेक महिने झाले तरी मिळाले नाहीत",
        "वीज वारंवार जाते, अनेकदा तक्रार केली पण ट्रान्सफॉर्मर तसाच आहे",
    ],
    "low": [
        "मुलांच्या शाळेत शिक्षक कमी आहेत",
        "दवाखान्यात औषधं मिळत नाहीत, बाहेरून घ्यावी लागतात",
        "रात्री अंधार असतो, महिलांना बाहेर पडायला भीती वाटते",
        "पिण्याचं पाणी गढूळ येतं",
        "बसची सोय नाही, कामावर जायला अडचण होते",
        "घरपट्टी वाढवली पण सुविधा तशाच आहेत",
        "पाण्याची टाकी गळते, दुरुस्ती होत नाही",
        "उद्यानाची देखभाल होत नाही",
        "सार्वजनिक शौचालय बंद अवस्थेत आहे",
        "स्मशानभूमीकडे जाणारा रस्ता खराब आहे",
        "गल्लीत पाणी तुंबतं, उतार नीट नाही",
        "अंगणवाडीची इमारत जुनी झाली आहे",
        "काही नाही, एवढंच",
    ],
}
GRIEVANCE_WEIGHTS = {"high": 8, "medium": 30, "low": 62}

QUESTIONS_BACK = [
    "हे खरंच तुम्हीच बोलताय का?",
    "माझा नंबर कुठून मिळाला तुम्हाला?",
    "तुम्ही कधी आमच्या भागात येणार?",
    "याचं पुढे काय होणार?",
    "हे रेकॉर्ड कशाला करताय?",
]

OPTOUTS = ["नाही", "नको मला", "मला बोलायचं नाही", "बंद करा"]


@dataclass
class SimResult:
    voters: int = 0
    dialled: int = 0
    outcomes: dict[str, int] = None  # type: ignore[assignment]
    opted_out: int = 0

    def __post_init__(self) -> None:
        if self.outcomes is None:
            self.outcomes = {}

    def summary(self) -> str:
        lines = [f"  voters      {self.voters:,}", f"  dialled     {self.dialled:,}"]
        for k, v in sorted(self.outcomes.items(), key=lambda kv: -kv[1]):
            pct = 100 * v / self.dialled if self.dialled else 0
            lines.append(f"    {k:<12} {v:>6,}  {pct:>5.1f}%")
        lines.append(f"  opt-outs    {self.opted_out:,}")
        return "\n".join(lines)


# Devanagari speaking rate on a phone line, from docs/00_CONTEXT.md §4.
CHARS_PER_SECOND = 500 / 60
CPM = per_minute().total


def _duration_s(turns: list[dict], rng: random.Random) -> float:
    """Agent speech at the modelled rate, plus the voter's own turns and the pause
    before each answer."""
    seconds = 0.0
    for t in turns:
        seconds += len(t["text"]) / CHARS_PER_SECOND
        if t["role"] == "voter":
            seconds += rng.uniform(0.6, 2.2)  # thinking time before speaking
    return round(seconds, 1)


def _phone(rng: random.Random) -> str:
    """A syntactically valid Indian mobile that `phone.normalise` will accept."""
    while True:
        digits = rng.choice("6789") + "".join(rng.choice("0123456789") for _ in range(9))
        if len(set(digits)) > 3:
            return f"+91{digits}"


def _utterances(rng: random.Random, kind: str) -> list[str]:
    """The voter's side of one call."""
    if kind == "optout":
        return [rng.choice(OPTOUTS)]
    if kind == "hangup":
        return [rng.choice(ANSWERS["water"][rng.choice(["ok", "irregular"])])]

    turns = ["हो, बोला"]
    if kind == "asks":
        # Interjections cost a turn: the agent answers, then re-asks. Two spare copies
        # of each answer are appended below so the script still reaches the end.
        turns.append(rng.choice(QUESTIONS_BACK))
    for field, weights in (
        ("water", {"ok": 3, "irregular": 5, "none": 2}),
        ("roads", {"ok": 2, "bad": 5, "very_bad": 3}),
        ("scheme_issue", {"none": 3, "ration": 3, "pension": 2, "ladki_bahin": 3, "housing": 2}),
    ):
        label = rng.choices(list(weights), weights=list(weights.values()))[0]
        answer = rng.choice(ANSWERS[field][label])
        turns.append(answer)
        if kind == "asks":
            # A re-asked question needs answering a second time.
            turns.append(answer)
    band = rng.choices(list(GRIEVANCE_WEIGHTS), weights=list(GRIEVANCE_WEIGHTS.values()))[0]
    turns.append(rng.choice(GRIEVANCES[band]))

    if kind == "silence":
        # Drops out partway. The state machine closes on two silences, and the runner
        # below supplies them.
        return turns[: rng.randint(2, 4)]
    return turns


def simulate(
    db_path: Path,
    n_voters: int = 2000,
    *,
    campaign_id: str = "csn-central-2026q3",
    lang: str = "mr-IN",
    pickup_rate: float = 0.45,
    seed: int = 20260907,
) -> SimResult:
    rng = random.Random(seed)
    settings = load_settings()
    script, bank, guard = build(lang, settings)
    classifier = KeywordClassifier()
    result = SimResult(voters=n_voters)

    with session(db_path) as conn:
        upsert_politician(
            conn, id="mla-demo", name="[नाव]",
            constituency="Chhatrapati Sambhajinagar (Central)",
            office_contact="[कार्यालय क्रमांक]", voice_id="demo",
            consent_ref="SYNTHETIC-DEMO-NOT-A-REAL-CONSENT",
        )
        upsert_campaign(
            conn, id=campaign_id, name="Governance outreach — synthetic demo",
            politician_id="mla-demo", lang=lang,
            script_version=script.version, bank_version=bank.version,
            manifest_sha=guard.manifest()["sha256"], status="simulated",
        )
        ledger = OptOutLedger(conn)

        for i in range(n_voters):
            phone = _phone(rng)
            ward = rng.choice(WARDS)
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            voter_id = f"{campaign_id}:{phone}"
            if not insert_voter(
                conn, id=voter_id, campaign_id=campaign_id, phone=phone, name=name,
                ward=ward, source="simulate", dnd_checked_at="2026-09-07T04:00:00+00:00",
            ):
                continue

            if rng.random() > pickup_rate:
                result.outcomes["no_answer"] = result.outcomes.get("no_answer", 0) + 1
                result.dialled += 1
                conn.execute(
                    "INSERT INTO attempt_log (campaign_id, voter_id, at, outcome) "
                    "VALUES (?,?,?,?)",
                    (campaign_id, voter_id, "2026-09-07T05:00:00+00:00", "no_answer"),
                )
                continue

            kind = rng.choices(
                ["plain", "asks", "silence", "optout", "hangup"],
                weights=[55, 20, 12, 8, 5],
            )[0]

            convo = Conversation(script=script, bank=bank, guard=guard, classifier=classifier)
            call_session = CallSession(
                campaign_id=campaign_id, voter_id=voter_id, lang=lang,
                politician_id="mla-demo",
                voice_consent_ref="SYNTHETIC-DEMO-NOT-A-REAL-CONSENT",
            )
            call_session.mark_dnd_checked()
            convo.start()
            call_session.mark_disclosure_played()

            for utterance in _utterances(rng, kind):
                if convo.finished:
                    break
                convo.handle(VoterSaid(utterance, confidence=rng.uniform(0.55, 1.0)))

            if kind == "hangup" and not convo.finished:
                convo.handle(Hangup())

            # Every conversation must reach a terminal state. A voter who stops
            # responding goes quiet, and the state machine closes after two silences.
            # Without this the record comes out IN_PROGRESS, which `to_record` maps to
            # `error` — and a simulated 9% error rate is a lie about the system, not a
            # finding about it.
            for _ in range(6):
                if convo.finished:
                    break
                convo.handle(Silence())
            if not convo.finished:
                raise RuntimeError(
                    f"conversation stuck in {convo.state} after silences — the state "
                    "machine has a path with no exit, which would strand a real call"
                )

            record = call_session.to_record(convo)
            # Duration is not something the state machine decides — it depends on
            # speaking rate and how long the voter takes to think. Modelled here from
            # the turns that actually happened, then priced with the real cost model,
            # so the report's money column is derived rather than invented.
            record["duration_s"] = _duration_s(record["turns"], rng)
            record["cost_inr"] = round(CPM * record["duration_s"] / 60, 4)
            record_call(conn, record, voter_id)
            result.dialled += 1
            result.outcomes[record["outcome"]] = result.outcomes.get(record["outcome"], 0) + 1

            if record["outcome"] == "opted_out":
                if ledger.add(phone, source="call", campaign_id=campaign_id):
                    result.opted_out += 1

    return result


def main() -> None:
    setup()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", type=Path, default=Path("out/campaign.db"))
    p.add_argument("--voters", type=int, default=2000)
    p.add_argument("--campaign", default="csn-central-2026q3")
    p.add_argument("--lang", default="mr-IN")
    p.add_argument("--pickup", type=float, default=0.45)
    p.add_argument("--seed", type=int, default=20260907)
    args = p.parse_args()

    print(f"\n  Simulating {args.voters:,} calls through the real state machine …\n")
    result = simulate(
        args.db, args.voters, campaign_id=args.campaign, lang=args.lang,
        pickup_rate=args.pickup, seed=args.seed,
    )
    print(result.summary())
    print(f"\n  -> {args.db}")
    print(f"  next: python -m insights.report --db {args.db} --campaign {args.campaign}\n")


if __name__ == "__main__":
    main()
