"""The report.

Built on a simulation that runs the real state machine, so these also serve as an
integration test: if classification or routing breaks, the numbers here move.
"""

from __future__ import annotations

import pytest

from campaign.db import connect
from campaign.simulate import simulate
from insights.report import (
    _is_no_issue,
    economics,
    grievances,
    nothing_further,
    render,
    ward_breakdown,
    write_grievance_csv,
)

CAMPAIGN = "sim-test"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("insights") / "campaign.db"
    simulate(path, n_voters=300, campaign_id=CAMPAIGN, seed=11)
    return path


@pytest.fixture(scope="module")
def conn(db):
    return connect(db)


def test_the_simulation_produced_real_conversations(conn):
    outcomes = {
        r["outcome"]: r["n"]
        for r in conn.execute(
            "SELECT outcome, COUNT(*) n FROM call WHERE campaign_id = ? GROUP BY outcome",
            (CAMPAIGN,),
        ).fetchall()
    }
    assert outcomes.get("completed", 0) > 0
    # A non-zero error rate means conversations are being stranded mid-call, which
    # would be a state machine with an unreachable exit — see simulate.py.
    assert outcomes.get("error", 0) == 0


def test_every_spoken_turn_came_from_the_approved_set(conn):
    """The whole safety argument, checked against data rather than in a unit test:
    nothing the agent said in 300 simulated calls was generated."""
    from voiceai import build

    _script, _bank, guard = build("mr-IN")
    rows = conn.execute(
        "SELECT DISTINCT t.text FROM turn t JOIN call c ON c.id = t.call_id "
        "WHERE c.campaign_id = ? AND t.role = 'agent'",
        (CAMPAIGN,),
    ).fetchall()
    assert rows
    unapproved = [r["text"] for r in rows if not guard.is_allowed(r["text"])]
    assert not unapproved, f"agent said {len(unapproved)} unapproved things"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("काही नाही, एवढंच", True),
        ("सगळं ठीक आहे", True),
        ("कोणतीही अडचण नाही", True),
        ("गटाराचं पाणी घरासमोर साचतं", False),
        ("रस्ता खूप खराब आहे", False),
        ("", False),
    ],
)
def test_no_issue_filter(text, expected):
    """Q4 is open-ended, so "nothing else" is a valid answer to it — but it is not a
    callback, and an office working list that opens with rows of "everything is fine"
    is a list nobody works from."""
    assert _is_no_issue(text) is expected


def test_the_callback_list_excludes_non_grievances_but_counts_them(conn):
    listed = grievances(conn, CAMPAIGN)
    assert listed
    assert not any(_is_no_issue(g["raw_text"]) for g in listed)
    # Filtered, not deleted: the count is reported so nothing is silently hidden.
    assert nothing_further(conn, CAMPAIGN) >= 0


def test_callback_list_is_urgent_first(conn):
    order = {"high": 0, "medium": 1, "low": 2}
    seen = [order.get(g["priority"] or "low", 2) for g in grievances(conn, CAMPAIGN)]
    assert seen == sorted(seen)


def test_wards_are_ranked_worst_first(conn):
    wards = ward_breakdown(conn, CAMPAIGN)
    assert len(wards) > 1
    rates = [w["problem_rate"] for w in wards]
    assert rates == sorted(rates, reverse=True)
    assert all(0.0 <= r <= 1.0 for r in rates)


def test_cost_matches_the_model(conn):
    """The report's money column is derived from voiceai.costs, not invented."""
    from voiceai.costs import per_minute

    econ = economics(conn, CAMPAIGN)
    assert econ["minutes"] > 0
    assert econ["cost_per_min"] == pytest.approx(per_minute().total, rel=0.01)


def test_report_renders_with_the_synthetic_warning(conn):
    html = render(conn, CAMPAIGN)
    assert "SYNTHETIC DEMO DATA" in html
    assert "Grievance list" in html
    assert "Compliance" in html
    # Self-contained: nothing to fetch, so it opens on a phone with no network.
    for forbidden in ("<script", "http://", "https://", "cdn"):
        assert forbidden not in html.lower(), f"report reaches out for {forbidden}"


def test_grievance_csv_round_trips(conn, tmp_path):
    import csv as csvmod

    path = tmp_path / "g.csv"
    n = write_grievance_csv(conn, CAMPAIGN, path)
    rows = list(csvmod.DictReader(path.open(encoding="utf-8-sig")))
    assert len(rows) == n
    assert {"priority", "name", "ward", "phone", "grievance"} <= set(rows[0])


def test_unknown_campaign_fails_loudly(conn):
    with pytest.raises(SystemExit, match="no campaign"):
        render(conn, "does-not-exist")
