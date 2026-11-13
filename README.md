# Healthy Congress Index

Scripts that collect data for the Bipartisan Policy Center's Healthy Congress Index (HCI). Definitions follow BPC's Internal HCI Methodology document (OneDrive, Archive/Congress/HCI).

| Folder | Metric | Source | Browser needed? |
|---|---|---|---|
| `senate_amendments/` | Senate Amendments Considered | Congress.gov API | No (needs a free API key) |
| `cloture/` | Filibuster and Cloture on Legislation | Senate.gov cloture tables | No |
| `working_days/` | Working Days in Washington | Congress.gov Daily Digest | Yes (opens Chrome) |
| `deprecated/` | Old all-in-one notebooks, kept for reference | | |

## Setup

Requires Python 3.9 or later.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows, activate with `.venv\Scripts\activate`. Run the tests with `pytest tests`; they are offline and take a few seconds.

## Senate Amendments Considered

**Definition:** The number of amendments considered on the floor of the Senate that are subject to a recorded vote, voice vote, or unanimous consent agreement. This does not include amendments that fell on a point of order or that were withdrawn, tabled, rendered moot, or ruled out of order by the chair.

**How it's collected:** An amendment counts if any of its actions carries Library of Congress action code 94000 (Senate amendment agreed to) or 95000 (Senate amendment not agreed to), and it is dated by its latest action. This is the same selection the old Congress.gov search used.

The Congress.gov API's list of a Congress's amendments shows each one's latest action. Most amendments are submitted but never reach the floor, so they have no latest action. Only the few hundred per Congress whose latest action falls in the date range are looked up in detail, so a run takes about 10 to 20 minutes.

**Classification** (from the text of the latest action):

- Outcome: `NA` (not agreed to) if the text contains "not agreed," otherwise `A` (agreed to)
- Action type: `UC` if it contains "unanimous," `RCV` if "Yea-Nay," and `VV` if "Voice Vote"
- Anything else, usually a vitiated adoption, is marked `INPUT BY HAND`

**Categories** are mutually exclusive and are checked in this order:

- Amendments amended: what it amends contains S.Amdt.
- Budget resolutions: a concurrent resolution (Con) whose title, in the Measure Title column, sets forth or establishes the congressional budget
- Resolutions amended: contains Res
- Bills amended: everything else, including treaties

Until November 2026, any concurrent resolution counted as a budget resolution. That put three 118th Congress amendments to other resolutions in the published budget resolution row: two to S.Con.Res.7, on the detention of Vladimir Kara-Murza, and one to S.Con.Res.43, on Veterans of Foreign Wars of the United States Day. They now count as resolutions amended, which corrects the published 118th numbers for Q4 2023 and Q4 2024.

**Majority and minority** come from the sponsor's party and the party that controlled the Senate, which is listed by Congress in `SENATE_MAJORITY` in `amendments_helper.py`. Independents count with the party they caucus with (Democrats).

**To run:**

1. Get a free key at https://api.congress.gov/sign-up/.
2. Save the key in a file named `.congress_api_key` at the top of this repo. The file is git-ignored. Alternatively, set the `CONGRESS_API_KEY` environment variable.
3. Open `senate_amendments/amendments.ipynb`, set `START` and `END`, and run all cells.
4. Check the rows marked `INPUT BY HAND` on Congress.gov and record any fixes in `OVERRIDES`, which saves the CSV again with the fixes. Until they are fixed, they count toward totals but not toward UC, VV, or RCV.
5. `quarterly_summary` gives per-quarter counts for the "Senate Amendments Considered" sheet, and the notebook saves them as `amendments_summary_{start}_to_{end}.csv`. The sheet is cumulative within each Congress, except for the budget resolution row.
6. At the start of each Congress, add it to `SENATE_MAJORITY`.

**Reading the CSVs:** Use `pd.read_csv(path, keep_default_na=False)`. Otherwise, pandas reads the outcome code `NA` as a missing value. `Sponsor Party` is R or D and is blank for independents, as in the original scraper. `quarterly_summary` handles independents. `Measure Title` is the title of the bill or resolution underneath, also for an amendment to an amendment, and is blank for treaties.

**Data files:**

- `amendments_2022-01-01_to_2024-12-31.csv` covers the 117th Congress's second session and the 118th Congress, and reproduces the published table, apart from the budget resolution correction.
- `amendments_2025-01-01_to_2026-11-12.csv` is the 119th Congress through November 12, 2026.
- Each has a matching `amendments_summary_...` file with its per-quarter counts.

`scrape_amendments` is the original Congress.gov scraper, kept as a fallback. It opens a visible Chrome window, because Congress.gov blocks headless browsers. Its output differs from the API's in three cosmetic ways:

- Latest Action text ends in "(All Actions)."
- URLs include search parameters.
- Amendments to treaties show "N/A" instead of, for example, "Treaty Doc. 117-3."

## Filibuster and Cloture on Legislation

**Definition:** The HCI tracks (1) votes on legislative cloture motions, (2) votes to invoke cloture on legislation, and (3) failed votes on legislative cloture motions, according to the Senate's lists. Cloture on nominations is not included.

**Counting rules:**

- **Groups.** A measure containing "PN" is a nomination, even when the subject says "motion to proceed," as in the original summaries. Otherwise, a row whose subject mentions "motion to proceed" is a motion to proceed, and everything else is legislation. The Legislation group includes motions to proceed and treaties.
- **En bloc nominations.** Since 2025, the Senate has listed cloture on these with Measure "Various" and the PN numbers in the subject, and they count as nominations. Since November 2026, so do the executive resolutions (S.Res.) that authorize en bloc consideration. S.Res.50 in 2019, a general change to nomination procedure, stays legislation, as in the published numbers for the 116th Congress.
- **Reconsidered motions** appear on one row of the Senate's table, with two vote dates, votes, and results. They are split into the original vote and a reconsideration vote.
- **Motions filed** is the number of rows minus the number of reconsiderations.
- **Votes** is votes invoked (result `I`) plus votes failed (result `F`), including reconsideration votes.
- **Reconsidered** is the number of reconsideration votes.
- **Quarters** are assigned by the date a motion was filed.

The methodology's worked example is a test in `tests/test_hci.py`: S.1 in the 116th Congress has five motions filed, six votes (three invoked and three failed), and one reconsidered.

**Changes from the original scripts:**

- **Line breaks, not commas.** Reconsidered rows are split on the table's line breaks. The original split on commas, which could type a reconsidered motion to proceed whose title contains a comma as legislation.
- **Inclusive date filters.** The original dropped motions filed on the last day of a range.
- **En bloc nominations** are counted as nominations, as described above.
- **Missing results are filled in.** When a recorded vote is listed without a result code, the result comes from the Senate's official roll call. One case so far: the July 25, 2024, cloture vote on S.2073, which was invoked 86-1.
- **Vote dates are year-aware.** A motion filed in December and voted on in January gets the right year.

**To run:** Open `cloture/cloture.ipynb`, set `CONGRESSES`, and run all cells. It prints a line for anything unusual on the Senate's page. It writes two files and displays the cumulative rows used in the "Cloture Motion Activity" sheet:

- `cloture_results_{congress}.csv` has one row per cloture motion, plus one row per reconsideration vote. Votes are the rows with Result `I` (invoked) or `F` (failed). `W` means withdrawn, `N` no vote, `V` vitiated, and blank pending.
- `cloture_summary_{congress}.csv` has per-quarter counts for each group.

The Senate's page can lag the floor by several days, so rerun after a quarter closes.

## Validation (November 2026)

To check this work by hand, without running any code, follow the steps in [CHECKING.md](CHECKING.md).

**Cloture.** Both checks below are pinned in the tests, using copies of the Senate's 116th and 117th Congress tables.

- Every published legislative cloture number for the 116th Congress and the first session of the 117th Congress is reproduced.
- 183 of 186 values match the old internal summaries (`cloture_summary2020-07-09.csv` and `cloture_summary2022-01-25.csv` in OneDrive, Archive/Congress/HCI). The three differences come from one nomination filed on June 30, 2020, which the old date filter dropped. Nominations are not published.

**Senate amendments.** The API results were compared with the original Congress.gov scraper, rerun on November 11, 2026, for latest actions from January 1, 2022, through September 30, 2024.

- For the 118th Congress, all 184 amendments match, and every field is identical.
- For 2022 (the 117th Congress), all 165 amendments match. Every field is identical except for the three amendments to treaties, which the old scraper labeled "N/A."
- Every published quarterly value for 2022 through 2024 is reproduced from `amendments_2022-01-01_to_2024-12-31.csv`, and this is pinned in the tests. The exception is the November 2026 correction to the budget resolution row for Q4 2023 and Q4 2024, described under Categories.

The October 2024 file (`amendments.csv`, now replaced) differed in only two places, both since corrected on Congress.gov or by the API: S.Amdt.1367 had a blank latest action, and S.Amdt.1841's action text was later edited.
