"""Campaign layer: opt-out ledger, DND gate, dialling policy, ingest.

Most of these encode a legal obligation rather than a preference. Where that is the
case the docstring says which one, so that anyone loosening a rule has to argue with
`docs/02_COMPLIANCE.md` rather than with a style choice.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta

import pytest

from campaign.db import connect, insert_voter, upsert_campaign, upsert_politician
from campaign.dialer import IST, Dialer, DialPlan, is_dialable_now
from campaign.dnd import DNDCheckUnavailableError, DNDGate, NullDNDProvider, StaticDNDProvider
from campaign.ingest import guess_columns, ingest
from campaign.optout import OptOutLedger

CAMPAIGN = "test-campaign"


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    upsert_politician(c, id="p1", name="Test", constituency="Test AC")
    upsert_campaign(c, id=CAMPAIGN, name="Test", politician_id="p1", lang="mr-IN")
    return c


def add_voter(conn, phone: str, **kw):
    return insert_voter(
        conn, id=f"{CAMPAIGN}:{phone}", campaign_id=CAMPAIGN, phone=phone, **kw
    )


# -- opt-out ledger --------------------------------------------------------------


def test_optout_is_global_not_per_campaign(conn):
    """§1.3: "stop calling me" is about being called, not about one campaign."""
    ledger = OptOutLedger(conn)
    ledger.add("+919876543211", campaign_id="campaign-a")
    upsert_campaign(conn, id="campaign-b", name="B", politician_id="p1", lang="mr-IN")
    assert ledger.contains("+919876543211")


def test_optout_normalises_before_storing(conn):
    """Someone opting out from a call must match the same person in a CSV import."""
    ledger = OptOutLedger(conn)
    ledger.add("098765 43211")
    assert ledger.contains("+91-98765-43211")


def test_optout_is_idempotent(conn):
    ledger = OptOutLedger(conn)
    assert ledger.add("+919876543211") is True
    assert ledger.add("+919876543211") is False
    assert ledger.count() == 1


def test_unparseable_numbers_fail_closed(conn):
    """`contains` is a gate before dialling. An unknown number must not be treated as
    permission to dial."""
    assert OptOutLedger(conn).contains("garbage") is True


def test_the_ledger_has_no_remove():
    """Removing someone from an opt-out list is the most damaging accidental operation
    available here, so the API does not offer it."""
    assert not hasattr(OptOutLedger, "remove")
    assert not hasattr(OptOutLedger, "delete")


def test_import_only_ever_adds(conn, tmp_path):
    ledger = OptOutLedger(conn)
    ledger.add("+919876543211")
    path = tmp_path / "office_dnc.csv"
    path.write_text("phone\n+919000000011\nnot-a-number\n", encoding="utf-8")

    result = ledger.import_csv(path)
    assert result.added == 1
    assert len(result.unparseable) == 1
    assert ledger.contains("+919876543211"), "an import must never remove an entry"


# -- DND gate --------------------------------------------------------------------


def test_null_dnd_provider_refuses_production():
    """Marking every number 'checked' without checking is how a real TRAI complaint
    lands on a sitting MLA's office (§1.4)."""
    with pytest.raises(DNDCheckUnavailableError, match="cannot be used in production"):
        NullDNDProvider(production=True).check(["+919876543211"])


def test_dnd_check_stamps_evidence(conn):
    add_voter(conn, "+919876543211")
    add_voter(conn, "+919876543212")
    gate = DNDGate(conn, StaticDNDProvider(blocked={"+919876543212"}))
    gate.check_pending(CAMPAIGN)

    rows = {r["phone"]: r for r in conn.execute("SELECT * FROM voter").fetchall()}
    assert rows["+919876543211"]["dnd_checked_at"]
    assert rows["+919876543211"]["dnd_blocked"] == 0
    assert rows["+919876543212"]["dnd_blocked"] == 1


# -- dialling window -------------------------------------------------------------


@pytest.mark.parametrize(
    "hour,allowed",
    [(9, False), (10, True), (14, True), (18, True), (19, False), (23, False), (3, False)],
)
def test_dialling_window(hour, allowed):
    """§1.7: 10:00-19:00 local. Calling a constituent at 07:00 is how outreach becomes
    a complaint."""
    now = datetime(2026, 9, 8, hour, 30, tzinfo=IST)
    assert bool(is_dialable_now(DialPlan(), now)) is allowed


def test_blackout_dates_block_everything():
    """Polling day and the 48-hour silence period."""
    plan = DialPlan().with_blackout(date(2026, 11, 20))
    decision = is_dialable_now(plan, datetime(2026, 11, 20, 12, 0, tzinfo=IST))
    assert not decision
    assert "blackout" in decision.reason


# -- who gets dialled ------------------------------------------------------------


def _ready_voter(conn, phone, **kw):
    add_voter(conn, phone, dnd_checked_at="2026-09-01T00:00:00+00:00", **kw)


def test_opted_out_numbers_are_never_offered(conn):
    _ready_voter(conn, "+919876543211")
    _ready_voter(conn, "+919876543212")
    OptOutLedger(conn).add("+919876543212")
    phones = {c.phone for c in Dialer(conn).next_batch(CAMPAIGN)}
    assert phones == {"+919876543211"}


def test_unchecked_and_blocked_numbers_are_never_offered(conn):
    add_voter(conn, "+919876543211")  # never DND-checked
    _ready_voter(conn, "+919876543212")
    conn.execute("UPDATE voter SET dnd_blocked = 1 WHERE phone = '+919876543212'")
    assert Dialer(conn).next_batch(CAMPAIGN) == []


def test_completed_and_opted_out_are_not_redialled(conn):
    for phone, outcome in (("+919876543211", "completed"), ("+919876543212", "opted_out")):
        _ready_voter(conn, phone)
        conn.execute(
            "INSERT INTO attempt_log (campaign_id, voter_id, at, outcome) VALUES (?,?,?,?)",
            (CAMPAIGN, f"{CAMPAIGN}:{phone}", "2026-09-01T00:00:00+00:00", outcome),
        )
    assert Dialer(conn).next_batch(CAMPAIGN) == []


def test_hangup_is_not_retried(conn):
    """Someone who picked up and ended the call has told us something. At 3.5 lakh
    numbers there is no shortage of people who have not been called at all."""
    _ready_voter(conn, "+919876543211")
    conn.execute(
        "INSERT INTO attempt_log (campaign_id, voter_id, at, outcome) VALUES (?,?,?,?)",
        (CAMPAIGN, f"{CAMPAIGN}:+919876543211", "2026-09-01T00:00:00+00:00", "hangup"),
    )
    assert Dialer(conn).next_batch(CAMPAIGN) == []


def test_no_answer_is_retried_but_only_after_the_backoff(conn):
    _ready_voter(conn, "+919876543211")
    now = datetime(2026, 9, 8, 12, 0, tzinfo=IST)
    conn.execute(
        "INSERT INTO attempt_log (campaign_id, voter_id, at, outcome) VALUES (?,?,?,?)",
        (CAMPAIGN, f"{CAMPAIGN}:+919876543211",
         (now - timedelta(hours=1)).isoformat(), "no_answer"),
    )
    dialer = Dialer(conn)
    assert dialer.next_batch(CAMPAIGN, now=now) == [], "too soon"
    assert dialer.next_batch(CAMPAIGN, now=now + timedelta(hours=6)), "backoff elapsed"


def test_max_attempts_is_respected(conn):
    _ready_voter(conn, "+919876543211")
    for i in range(3):
        conn.execute(
            "INSERT INTO attempt_log (campaign_id, voter_id, at, outcome) VALUES (?,?,?,?)",
            (CAMPAIGN, f"{CAMPAIGN}:+919876543211",
             f"2026-09-0{i + 1}T00:00:00+00:00", "no_answer"),
        )
    assert Dialer(conn, DialPlan(max_attempts=3)).next_batch(CAMPAIGN) == []


def test_least_called_first(conn):
    for phone in ("+919876543211", "+919876543212"):
        _ready_voter(conn, phone)
    conn.execute(
        "INSERT INTO attempt_log (campaign_id, voter_id, at, outcome) VALUES (?,?,?,?)",
        (CAMPAIGN, f"{CAMPAIGN}:+919876543211", "2026-01-01T00:00:00+00:00", "no_answer"),
    )
    batch = Dialer(conn).next_batch(CAMPAIGN)
    assert batch[0].phone == "+919876543212", "never-called voter should come first"


# -- ingest ----------------------------------------------------------------------


def test_header_guessing_handles_marathi_and_english():
    assert guess_columns(["Voter Name", "Mobile No", "Ward"]) == {
        "name": "Voter Name", "phone": "Mobile No", "ward": "Ward"
    }
    assert guess_columns(["नाव", "मोबाईल", "प्रभाग"])["phone"] == "मोबाईल"


def test_ingest_dedupes_rejects_and_explains(tmp_path):
    csv_path = tmp_path / "voters.csv"
    csv_path.write_text(
        "Name,Mobile,Ward\n"
        "A,9876543211,W1\n"
        "B,+91 98765 43211,W1\n"     # same person, different format
        "C,9999999999,W2\n"          # placeholder
        "D,12345,W2\n"               # too short
        "E,9822011220,W3\n",
        encoding="utf-8",
    )
    db = tmp_path / "t.db"
    c = connect(db)
    upsert_politician(c, id="p1", name="T", constituency="T")
    upsert_campaign(c, id=CAMPAIGN, name="T", politician_id="p1", lang="mr-IN")
    c.commit()
    c.close()

    rejects = tmp_path / "rejects.csv"
    report = ingest(csv_path, db, CAMPAIGN, rejects_path=rejects)

    assert report.rows_read == 5
    assert report.accepted == 2
    assert report.duplicate_in_file == 1
    assert report.rejected["placeholder"] == 1
    assert report.rejected["too_short"] == 1

    reasons = {r["_reason"] for r in csv.DictReader(rejects.open(encoding="utf-8"))}
    assert reasons == {"duplicate_in_file", "placeholder", "too_short"}


def test_ingest_will_not_load_an_opted_out_number(tmp_path):
    """A number on the opt-out list should not even be sitting in a campaign table."""
    db = tmp_path / "t.db"
    c = connect(db)
    upsert_politician(c, id="p1", name="T", constituency="T")
    upsert_campaign(c, id=CAMPAIGN, name="T", politician_id="p1", lang="mr-IN")
    OptOutLedger(c).add("+919822011220")
    c.commit()
    c.close()

    csv_path = tmp_path / "v.csv"
    csv_path.write_text("Name,Mobile\nA,9822011220\nB,9876543211\n", encoding="utf-8")
    report = ingest(csv_path, db, CAMPAIGN)
    assert report.opted_out == 1
    assert report.accepted == 1
