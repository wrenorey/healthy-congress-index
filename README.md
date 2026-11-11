# Healthy Congress Index

Scripts that collect data for the Bipartisan Policy Center's Healthy Congress Index (HCI). Definitions follow the Internal HCI Methodology document (Archive/Congress/HCI on OneDrive).

| Folder | Metric | Source | Browser needed? |
|---|---|---|---|
| `senate_amendments/` | Senate amendments considered | Congress.gov API | No (needs a free API key) |
| `cloture/` | Filibuster and cloture on legislation | senate.gov cloture tables | No |
| `working_days/` | Working days in Washington | congress.gov Daily Digest | Yes (opens Chrome) |
| `deprecated/` | Old all-in-one notebooks, kept for reference | | |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the tests with `pytest tests`. They are offline and take under a second.

## Senate amendments considered

**Definition:** The number of amendments considered on the floor of the Senate that are subject to a recorded vote, voice vote, or unanimous consent agreement. This does not include amendments that fell on a point of order or that were withdrawn, tabled, rendered moot, or ruled out of order by the chair.

**How it's collected:** An amendment counts if any of its actions carries Library of Congress action code 94000 (Senate amendment agreed to) or 95000 (Senate amendment not agreed to). Amendments are dated by their latest action. This is the same selection the old congress.gov search used.

**Classification** (from the latest action's text):

- Outcome: `NA` (not agreed to) if the text contains "not agreed," otherwise `A` (agreed to)
- Action type: `UC` if it contains "unanimous," `RCV` if "Yea-Nay," and `VV` if "Voice Vote"
- Anything else is marked `INPUT BY HAND` for review. This is usually a vitiated adoption.

**Categories** are mutually exclusive and are checked in this order:

- Amendments amended: "Amends" contains S.Amdt.
- Budget resolutions: contains Con
- Resolutions amended: contains Res
- Bills amended: everything else, including treaties

**Majority and minority** follow the sponsor's party. Independents are counted with the party they caucus with (Democrats).

**To run:**

1. Get a free key at https://api.congress.gov/sign-up/.
2. Save it in a file named `.congress_api_key` at the top of this repo. The file is git-ignored. Alternatively, set the `CONGRESS_API_KEY` environment variable.
3. Open `senate_amendments/amendments.ipynb`, set `START`, `END`, and `MAJORITY`, and run all cells.
4. The first run for a Congress makes one request per Senate amendment, which takes about 45 minutes. Responses are cached in `senate_amendments/.api_cache/`, so later runs only fetch what changed.
5. `quarterly_summary` gives per-quarter counts for the "Senate Amendments Considered" sheet. The sheet is cumulative within a Congress, except for the budget resolution row.

`scrape_amendments` is the original congress.gov scraper and returns the same columns. It opens a visible Chrome window because congress.gov blocks headless browsers. It is kept only as a fallback.

**Reading the CSVs:** Use `pd.read_csv(path, keep_default_na=False)`. Otherwise, pandas reads the outcome code `NA` as a missing value.

## Filibuster and cloture on legislation

**Definition:** The HCI tracks (1) votes on legislative cloture motions, (2) votes to invoke cloture on legislation, and (3) failed votes on legislative cloture motions, according to the Senate's lists. Cloture on nominations is not included.

**Counting rules** (unchanged from the original scripts):

- **Groups.** A row whose subject mentions "motion to proceed" is a motion to proceed. Otherwise, a measure containing "PN" is a nomination, and everything else is legislation. The Legislation group includes motions to proceed and treaties.
- **Reconsidered motions** appear on one row of the Senate's table, with two vote dates, votes, and results. They are split into the original vote and a reconsideration vote.
- **Motions filed** is the number of rows minus the number of reconsiderations.
- **Votes** is votes invoked (result `I`) plus votes failed (result `F`), including reconsideration votes.
- **Reconsidered** is the number of reconsideration votes.
- **Quarters** are assigned by the date a motion was filed.

The methodology's worked example (S.1 in the 116th Congress: 5 motions filed, 6 votes, 3 invoked, 3 failed, and 1 reconsidered) is a test in `tests/test_hci.py`.

**To run:** Open `cloture/cloture.ipynb`, set `CONGRESSES`, and run all cells. It writes `cloture_results_{congress}.csv` (one row per vote) and `cloture_summary_{congress}.csv` (per-quarter counts for each group). It also displays the cumulative rows used in the "Cloture Motion Activity" sheet. The Senate's page can lag the floor by several days.

## Validation (November 2026)

**Cloture.** The new parser was rerun on the current Senate pages for the 116th and 117th Congresses and compared with the old internal summaries and the published tables.

- 183 of 186 values match, including every published legislative cloture number for the 116th Congress and the first session of the 117th Congress.
- The 3 differences come from 1 nomination filed on June 30, 2020. The old script's end-date filter dropped motions filed on the last day of the range, and the new filter includes them. Nominations are not published.

**Senate amendments.** The original scraper, rerun on November 11, 2026, returned the same 349 amendments for January 1, 2022, through September 30, 2024, as `senate_amendments/amendments.csv` (October 2024). The only differences were one row that previously failed to parse and minor text edits on congress.gov.

The published quarterly table (Q1 2022 through Q3 2024) can be reproduced from that file:

- Totals, majority, and minority match exactly.
- Every category matches once categories are treated as mutually exclusive.
- The old notebook's yearly summary let categories overlap (for example, it counted H.J.Res. and S.Con.Res. as bills too), so it did not match the published table. It has been replaced by `quarterly_summary`.

The API version maps amendments to the same fields, which is checked in the tests. One intended difference: amendments to treaties now say, for example, "Treaty Doc. 117-3" instead of "N/A," so they count as bills amended, as the published table did.
