"""Offline checks for the cloture and Senate amendments helpers (run with: pytest tests)."""
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
sys.path[:0] = [str(ROOT / "cloture"), str(ROOT / "senate_amendments")]

import amendments_helper as ah  # noqa: E402
import cloture_helper as ch  # noqa: E402


def page(name):
    return (FIXTURES / name).read_bytes()


def amendment(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())["amendment"]


# --- Cloture: published numbers ----------------------------------------------------------------

PUBLISHED_CLOTURE = {  # HCI full data tables, cumulative by quarter of the Congress
    "cloture_116_tables.htm": {
        "Votes on Cloture - Legislation": [19, 22, 26, 34, 41, 46, 51, 54],
        "Cloture Votes Invoked - Legislation": [7, 9, 12, 19, 20, 24, 27, 29],
        "Cloture Votes Failed - Legislation": [12, 13, 14, 15, 21, 22, 24, 25],
    },
    "cloture_117_tables.htm": {  # published through the first session only
        "Votes on Cloture - Legislation": [2, 8, 13, 20],
        "Cloture Votes Invoked - Legislation": [2, 5, 8, 12],
        "Cloture Votes Failed - Legislation": [0, 3, 5, 8],
    },
}


@pytest.mark.parametrize("fixture", PUBLISHED_CLOTURE)
def test_cloture_reproduces_published_hci_numbers(fixture):
    published = ch.published_rows(ch.summarize_cloture(ch.parse_cloture_page(page(fixture))))
    for label, expected in PUBLISHED_CLOTURE[fixture].items():
        assert list(published.loc[label])[:len(expected)] == expected, label


def test_cloture_counts_match_methodology_example():
    """The Internal HCI Methodology's worked example: S.1 in the 116th Congress gives 5 motions
    filed, 6 votes (3 invoked, 3 failed), and 1 reconsidered under Legislation."""
    rows = ch.parse_cloture_page(page("cloture_116_tables.htm"))
    summary = ch.summarize_cloture(rows[rows["Measure"] == "S.1"])[["Q1-2019"]]
    assert summary.loc["Legislation-Motions Filed"].item() == 5
    assert summary.loc["Legislation-Votes"].item() == 6
    assert summary.loc["Legislation-Voted Inv"].item() == 3
    assert summary.loc["Legislation-Votes Failed"].item() == 3
    assert summary.loc["Legislation-Reconsidered"].item() == 1


def test_reconsidered_motion_is_split_into_two_votes():
    rows = ch.parse_cloture_page(page("cloture_116_tables.htm"))
    mtp = rows[(rows["Measure"] == "S.1") & (rows["Date Filed"] == date(2019, 1, 4))]
    assert list(mtp["Legislation Type"]) == ["Motion to Proceed", "Motion to Proceed"]
    assert list(mtp["Result"]) == ["F", "I"]
    assert list(mtp["Vote"]) == ["56 - 44", "74 - 19"]
    assert list(mtp["Vote No."]) == ["No. 1", "No. 11"]
    assert list(mtp["Date of Motion"]) == [date(2019, 1, 8), date(2019, 1, 28)]
    assert mtp["Subject"].iloc[0] == "Strengthening America's Security in the Middle East Act, motion to proceed"
    assert mtp["Subject"].iloc[1].endswith("motion to proceed, Vote No. 1 reconsidered")


# --- Cloture: edge cases from the 118th and 119th Congresses -----------------------------------

def test_en_bloc_nominations_are_not_legislation():
    rows = ch.parse_cloture_page(page("cloture_119_en_bloc_rows.htm"))
    various = rows[rows["Measure"] == "Various"]
    assert len(various) == 6
    assert set(various["Legislation Type"]) == {"Nomination"}
    # The executive resolutions that authorize en bloc consideration stay Legislation (like S.Res.50
    # in the published 116th Congress numbers).
    assert set(rows.loc[rows["Measure"] == "S.Res.377", "Legislation Type"]) == {"Legislation"}


def test_december_filing_voted_in_january():
    row = ch.parse_cloture_page(page("cloture_118_edge_rows.htm")).set_index("Measure").loc["PN1020"]
    assert row["Date Filed"] == date(2023, 12, 19)
    assert row["Date of Motion"] == date(2024, 1, 8)


def test_malformed_sort_key_and_missing_result_are_flagged(capsys):
    rows = ch.parse_cloture_page(page("cloture_118_edge_rows.htm"))
    assert rows.set_index("Measure").loc["PN2", "Date Filed"] == date(2023, 3, 9)  # sort key "039"
    printed = capsys.readouterr().out
    assert "sort key '039'" in printed
    assert "S.2073: 1 vote date(s), 1 vote(s), and 0 result(s)" in printed


def test_missing_result_is_filled_from_roll_call(monkeypatch):
    rows = ch.parse_cloture_page(page("cloture_118_edge_rows.htm"))
    kosa = rows["Measure"] == "S.2073"
    assert list(rows.loc[kosa, "Result"]) == [""]
    lookups = []

    def fake_roll_call(congress, vote_day, vote_no):
        lookups.append((congress, vote_day, vote_no))
        return "I"  # roll call vote 219 (118th Congress, 2nd session): Cloture Motion Agreed to, 86-1

    monkeypatch.setattr(ch, "roll_call_result", fake_roll_call)
    filled = ch.fill_missing_results(rows, 118)
    assert list(filled.loc[kosa, "Result"]) == ["I"]
    assert lookups == [(118, date(2024, 7, 25), "No. 219")]


def test_vote_and_filing_date_formats():
    assert ch._parse_day("September 17", 2025) == date(2025, 9, 17)
    assert ch._parse_day("Sept 3", 2025) == date(2025, 9, 3)
    assert ch._parse_day("July 21", 2021) == date(2021, 7, 21)
    assert ch._parse_day("Feb 29", 2024) == date(2024, 2, 29)
    assert ch._parse_day("Mar 21, 2024", 2023) == date(2024, 3, 21)
    assert ch._vote_date("Jan 1", date(2020, 12, 30)) == date(2021, 1, 1)
    assert ch._vote_date("Feb 29", date(2024, 2, 27)) == date(2024, 2, 29)


def test_legislation_type():
    assert ch.legislation_type("S.1", "Some Act, motion to proceed") == "Motion to Proceed"
    assert ch.legislation_type("PN78-12", "Nominee Eric S. Lander") == "Nomination"
    assert ch.legislation_type("Various", "En bloc consideration of certain nominations: A (PN25-28)") == "Nomination"
    assert ch.legislation_type("H.R.4350", "National Defense Authorization Act") == "Legislation"
    assert ch.legislation_type("Treaty Doc. 117-3", "NATO accession") == "Legislation"


# --- Senate amendments: published numbers ------------------------------------------------------

AMENDMENTS_2022_2024 = ROOT / "senate_amendments" / "amendments_2022-01-01_to_2024-12-31.csv"
PUBLISHED_AMENDMENTS = {  # HCI full data tables; cumulative within a Congress except budget resolutions
    "quarters": ["2022 Q1", "2022 Q2", "2022 Q3", "2022 Q4",              # 117th, second session
                 "2023 Q1", "2023 Q2", "2023 Q3", "2023 Q4",              # 118th
                 "2024 Q1", "2024 Q2", "2024 Q3", "2024 Q4"],
    # 117th first-session totals (through Q4 2021) that the second session adds to
    "base_117": {"Total Amendments": 211, "Majority": 65, "Minority": 146, "Bills Amended": 38, "Amdts Amended": 79},
    "Total Amendments": [239, 266, 309, 376, 11, 32, 76, 135, 152, 165, 184, 223],
    "Majority": [82, 97, 115, 147, 0, 5, 23, 54, 59, 66, 79, 102],
    "Minority": [157, 169, 194, 229, 11, 27, 53, 81, 93, 99, 105, 121],
    "Bills Amended": [59, 79, 100, 145, 11, 31, 38, 52, 68, 80, 97, 133],
    "Amdts Amended": [79, 79, 99, 117, 0, 0, 33, 72, 73, 73, 73, 73],
    "Budget Resolutions": [0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 1],
}


def test_amendments_reproduce_published_hci_numbers():
    df = pd.read_csv(AMENDMENTS_2022_2024, keep_default_na=False, dtype=str)
    summary = ah.quarterly_summary(df).reindex(columns=PUBLISHED_AMENDMENTS["quarters"], fill_value=0)
    for row in ("Total Amendments", "Majority", "Minority", "Bills Amended", "Amdts Amended", "Budget Resolutions"):
        per_quarter = [int(v) for v in summary.loc[row]]
        if row == "Budget Resolutions":
            values = per_quarter
        else:  # cumulative within each Congress
            s117 = pd.Series(per_quarter[:4]).cumsum() + PUBLISHED_AMENDMENTS["base_117"][row]
            s118 = pd.Series(per_quarter[4:]).cumsum()
            values = list(s117) + list(s118)
        assert values == PUBLISHED_AMENDMENTS[row], row


def test_quarterly_summary_uses_each_congress_majority():
    df = pd.DataFrame({
        "Congress": ["118th Congress (2023-2024)", "119th Congress (2025-2026)", "119th Congress (2025-2026)"],
        "Sponsor": ["Paul, Rand [Sen.-R-KY]", "Paul, Rand [Sen.-R-KY]", "King, Angus S., Jr. [Sen.-I-ME]"],
        "Amends": ["H.R.1", "H.R.1", "H.R.1"],
        "Latest Action Date": ["12/01/24", "03/01/25", "03/02/25"],
        "Action Type": ["RCV", "RCV", "VV"],
    })
    summary = ah.quarterly_summary(df)
    assert summary.loc["Majority"].to_dict() == {"2024 Q4": 0, "2025 Q1": 1}   # R led the 119th
    assert summary.loc["Minority"].to_dict() == {"2024 Q4": 1, "2025 Q1": 1}   # independent counted with D


def test_quarterly_summary_refuses_undated_rows():
    df = pd.DataFrame({"Congress": ["118th Congress (2023-2024)"], "S.Amdt.No": ["S.Amdt.1367"],
                       "Sponsor": ["X [Sen.-D-MI]"], "Amends": ["H.R.1"], "Latest Action Date": [""],
                       "Action Type": ["INPUT BY HAND"]})
    with pytest.raises(ValueError, match="S.Amdt.1367"):
        ah.quarterly_summary(df)


# --- Senate amendments: fields ---------------------------------------------------------------

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


def test_amends_categories_are_mutually_exclusive():
    assert ah.amends_category("S.Amdt.6558 (which amends S.Amdt.6552)") == "Amdts Amended"
    assert ah.amends_category("S.Con.Res.14") == "Budget Resolutions"
    assert ah.amends_category("H.J.Res.100") == "Resolutions Amended"
    assert ah.amends_category("S.Res.805") == "Resolutions Amended"
    assert ah.amends_category("H.R.7888") == "Bills Amended"
    assert ah.amends_category("Treaty Doc. 117-3") == "Bills Amended"


def test_congress_of_date():
    assert ah._congress_of(date(2025, 1, 2)) == 118
    assert ah._congress_of(date(2025, 1, 3)) == 119
    assert ah._congress_of(date(2024, 12, 31)) == 118


# --- Senate amendments: API client -------------------------------------------------------------

def test_fetch_amendments_end_to_end_with_fake_api(monkeypatch):
    """Only amendments whose latest action is in range are looked up, only ones with code
    94000/95000 are kept, and only kept ones get a detail request."""
    actions = json.loads((FIXTURES / "samdt_118_1841_actions.json").read_text())["actions"]
    uncoded = [a for a in actions if a.get("actionCode") not in ah.CONSIDERED_CODES]
    listing = [
        {"number": "1841", "latestAction": {"actionDate": "2024-04-19", "text": "not agreed to"}},
        {"number": "1842", "latestAction": {"actionDate": "2024-04-20", "text": "withdrawn"}},  # no 94000/95000
        {"number": "1840", "latestAction": {"actionDate": "2024-03-01", "text": "agreed to"}},   # out of range
        {"number": "1839"},                                                                      # never on the floor
    ]
    responses = {
        "amendment/118/samdt": {"amendments": listing, "pagination": {"count": 4}},
        "amendment/118/samdt/1841/actions": {"actions": actions, "pagination": {"count": len(actions)}},
        "amendment/118/samdt/1842/actions": {"actions": uncoded, "pagination": {"count": len(uncoded)}},
        "amendment/118/samdt/1841": {"amendment": amendment("samdt_118_1841")},
    }
    requested = []

    class FakeApi:
        def __init__(self, api_key):
            self.calls = 0

        def get(self, path, **params):
            requested.append(path)
            return responses[path]

    monkeypatch.setattr(ah, "_Api", FakeApi)
    df = ah.fetch_amendments("04/01/2024", "04/30/2024", api_key="test")
    assert list(df["S.Amdt.No"]) == ["S.Amdt.1841"]
    assert list(df.columns) == ah.COLUMNS
    assert requested == ["amendment/118/samdt", "amendment/118/samdt/1841/actions",
                         "amendment/118/samdt/1841", "amendment/118/samdt/1842/actions"]


def test_listing_is_read_again_if_it_changes_while_paging():
    class ShiftingApi:  # the first read misses one amendment; the second read is complete
        def __init__(self):
            self.reads = 0

        def get(self, path, limit, offset):
            if offset == 0:
                self.reads += 1
            numbers = ["1", "2"] if self.reads == 1 else ["1", "2", "3"]
            return {"amendments": [{"number": n} for n in numbers][offset:offset + limit],
                    "pagination": {"count": 3}}

    api = ShiftingApi()
    assert set(ah._list_amendments(api, 118)) == {"1", "2", "3"}
    assert api.reads == 2


class _Response:
    def __init__(self, status=200, headers=None, body=None):
        self.status_code, self.headers, self.body = status, headers or {}, body or {"ok": True}

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_api_key_is_sent_in_a_header_not_the_url(monkeypatch):
    api = ah._Api("secret-key")
    seen = []
    monkeypatch.setattr(api.session, "get", lambda url, params, timeout: seen.append((url, params)) or _Response())
    api.get("amendment/118/samdt", limit=1)
    assert api.session.headers["X-Api-Key"] == "secret-key"
    assert "secret-key" not in repr(seen)


def test_network_errors_and_throttling_are_retried(monkeypatch):
    api = ah._Api("k")
    replies = [requests.exceptions.ReadTimeout("slow"), _Response(429, {"Retry-After": "Wed, 21 Oct 2026"}),
               _Response(200, {"X-RateLimit-Limit": "20000"}, {"amendments": []})]

    def fake_get(url, params, timeout):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(api.session, "get", fake_get)
    monkeypatch.setattr(ah.time, "sleep", lambda seconds: None)
    assert api.get("amendment/118/samdt") == {"amendments": []}
    assert api.min_interval == pytest.approx(3600 / (0.98 * 20000))


def test_api_key_is_found_from_a_worktree(monkeypatch, tmp_path):
    (tmp_path / ".congress_api_key").write_text("abc123\n")
    helper = tmp_path / ".claude" / "worktrees" / "branch" / "senate_amendments" / "amendments_helper.py"
    helper.parent.mkdir(parents=True)
    monkeypatch.delenv("CONGRESS_API_KEY", raising=False)
    monkeypatch.setattr(ah, "__file__", str(helper))
    assert ah._find_api_key() == "abc123"
    monkeypatch.setenv("CONGRESS_API_KEY", "from-env")
    assert ah._find_api_key() == "from-env"
