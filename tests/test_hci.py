"""Offline checks for the cloture and Senate amendments helpers (run with: pytest tests)."""
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
sys.path[:0] = [str(ROOT / "cloture"), str(ROOT / "senate_amendments")]

import amendments_helper as ah  # noqa: E402
import cloture_helper as ch  # noqa: E402


def amendment(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())["amendment"]


# --- Cloture -----------------------------------------------------------------------------------

def test_cloture_counts_match_methodology_example():
    """The Internal HCI Methodology's worked example: S.1 in the 116th Congress gives 5 motions
    filed, 6 votes (3 invoked, 3 failed), and 1 reconsidered under Legislation."""
    rows = ch.parse_cloture_page((FIXTURES / "cloture_116_S1.htm").read_bytes())
    summary = ch.summarize_cloture(rows)[["Q1-2019"]]
    assert summary.loc["Legislation-Motions Filed"].item() == 5
    assert summary.loc["Legislation-Votes"].item() == 6
    assert summary.loc["Legislation-Voted Inv"].item() == 3
    assert summary.loc["Legislation-Votes Failed"].item() == 3
    assert summary.loc["Legislation-Reconsidered"].item() == 1


def test_reconsidered_motion_is_split_into_two_votes():
    rows = ch.parse_cloture_page((FIXTURES / "cloture_116_S1.htm").read_bytes())
    mtp = rows[rows["Date Filed"].astype(str) == "2019-01-04"]  # filed Jan 4, failed, reconsidered
    assert list(mtp["Legislation Type"]) == ["Motion to Proceed", "Motion to Proceed"]
    assert list(mtp["Result"]) == ["F", "I"]
    assert list(mtp["Vote No."]) == ["No. 1", "No. 11"]
    assert [str(d) for d in mtp["Date of Motion"]] == ["2019-01-08", "2019-01-28"]
    assert mtp["Subject"].iloc[0] == "Strengthening America's Security in the Middle East Act, motion to proceed"
    assert mtp["Subject"].iloc[1] == ("Strengthening America's Security in the Middle East Act, "
                                      "motion to proceed, Vote No. 1 reconsidered")
    assert list(mtp["Vote"]) == ["56 - 44", "74 - 19"]


def test_legislation_type():
    assert ch.legislation_type("S.1", "Some Act, motion to proceed") == "Motion to Proceed"
    assert ch.legislation_type("PN78-12", "Nominee Eric S. Lander") == "Nomination"
    assert ch.legislation_type("H.R.4350", "National Defense Authorization Act") == "Legislation"


# --- Senate amendments -------------------------------------------------------------------------

def test_api_row_matches_congress_gov_display():
    row = ah.amendment_row(amendment("samdt_118_1841"), {})
    assert row == {
        "Congress": "118th Congress (2023-2024)",
        "S.Amdt.No": "S.Amdt.1841",
        "Amends": "H.R.7888",
        "Sponsor": "Durbin, Richard J. [Sen.-D-IL]",
        "Latest Action": "Amendment SA 1841 not agreed to in Senate by Yea-Nay Vote. 42 - 50. "
                         "Record Vote Number: 148.",
        "url": "congress.gov/amendment/118th-congress/senate-amendment/1841",
        "Latest Action Date": "04/19/24",
    }
    classified = ah._add_classification(pd.DataFrame([row])).iloc[0]
    assert (classified["Sponsor Party"], classified["Outcome"], classified["Action Type"]) == ("D", "NA", "RCV")


def test_second_degree_amendment_names_both_amendments():
    parents = {"6558": {"amendedAmendment": {"number": "6552"}}}
    row = ah.amendment_row(amendment("samdt_117_6569"), parents)
    assert row["Amends"] == "S.Amdt.6558 (which amends S.Amdt.6552)"
    assert row["Sponsor"] == "Braun, Mike [Sen.-R-IN]"


def test_treaty_amendment_is_labeled():
    assert ah.amendment_row(amendment("samdt_117_5191"), {})["Amends"] == "Treaty Doc. 117-3"


def test_considered_action_codes_are_in_actions():
    actions = json.loads((FIXTURES / "samdt_118_1841_actions.json").read_text())["actions"]
    assert any(a.get("actionCode") in ah.CONSIDERED_CODES for a in actions)


def test_amends_categories_are_mutually_exclusive():
    assert ah.amends_category("S.Amdt.6558 (which amends S.Amdt.6552)") == "Amdts Amended"
    assert ah.amends_category("S.Con.Res.14") == "Budget Resolutions"
    assert ah.amends_category("H.J.Res.100") == "Resolutions Amended"
    assert ah.amends_category("S.Res.805") == "Resolutions Amended"
    assert ah.amends_category("H.R.7888") == "Bills Amended"
    assert ah.amends_category("Treaty Doc. 117-3") == "Bills Amended"


def test_fetch_amendments_end_to_end_with_fake_api(monkeypatch, tmp_path):
    """Runs the whole fetch (listing, detail, actions, caching, filtering) against canned responses."""
    in_window = amendment("samdt_118_1841")                     # latest action 2024-04-19, code 95000
    outside = dict(in_window, number="1840", latestAction={"actionDate": "2024-03-01", "text": "x"})
    never_proposed = {k: v for k, v in in_window.items() if k != "proposedDate"}
    never_proposed.update(number="1839", latestAction={"actionDate": "2024-04-18", "text": "submitted"})
    actions = json.loads((FIXTURES / "samdt_118_1841_actions.json").read_text())["actions"]
    requests_made = []

    class FakeApi:
        def __init__(self, api_key):
            self.calls = 0

        def get(self, path, **params):
            requests_made.append(path)
            self.calls += 1
            if path == "amendment/118/samdt":
                assert params["fromDateTime"] == "2024-04-01T00:00:00Z"
                items = [{"number": n, "updateDate": "u1"} for n in ("1841", "1840", "1839")]
                return {"amendments": items, "pagination": {"count": 3}}
            if path == "amendment/118/samdt/1841":
                return {"amendment": in_window}
            if path == "amendment/118/samdt/1840":
                return {"amendment": outside}
            if path == "amendment/118/samdt/1839":
                return {"amendment": never_proposed}
            if path == "amendment/118/samdt/1841/actions":
                return {"actions": actions, "pagination": {"count": len(actions)}}
            raise AssertionError(f"unexpected request {path}")

    monkeypatch.setattr(ah, "_Api", FakeApi)
    monkeypatch.setattr(ah, "CACHE_DIR", tmp_path)

    df = ah.fetch_amendments("04/01/2024", "04/30/2024", api_key="test")
    assert list(df["S.Amdt.No"]) == ["S.Amdt.1841"]
    assert list(df.columns) == ah.COLUMNS
    assert "amendment/118/samdt/1840/actions" not in requests_made  # latest action outside the window
    assert "amendment/118/samdt/1839/actions" not in requests_made  # never proposed on the floor

    requests_made.clear()
    ah.fetch_amendments("04/01/2024", "04/30/2024", api_key="test")
    assert requests_made == ["amendment/118/samdt"]  # second run is served from the cache


def test_congress_of_date():
    from datetime import date
    assert ah._congress_of(date(2025, 1, 2)) == 118
    assert ah._congress_of(date(2025, 1, 3)) == 119
    assert ah._congress_of(date(2024, 12, 31)) == 118
