# Checking This Work

In November 2026, the code that collects two of the Bipartisan Policy Center's Healthy Congress Index (HCI) metrics was rebuilt. Senate amendments considered now come from the Congress.gov API, and cloture on legislation comes from the Senate's cloture tables. The [README](README.md) explains the counting rules, and its Validation section lists the automated checks already run against the old code and the published numbers.

The checks below need only a web browser and a spreadsheet program, such as Excel or Google Sheets. You don't need Python, git, or a GitHub account. The checks compare the data files with Congress.gov and Senate.gov, so they don't rely on the code being right. Expect them to take about half a day. Record what you find in the [log](#log) at the end.

## Before You Start

1. Read this guide on GitHub, at https://github.com/wrenorey/healthy-congress-index/blob/main/CHECKING.md, where its tables display properly.
2. Download the files. On https://github.com/wrenorey/healthy-congress-index, click **Code**, then **Download ZIP**, and unzip the download.
3. Read the README sections "Senate Amendments Considered" and "Filibuster and Cloture on Legislation." The checks test those rules.
4. Open the CSV files in Excel or Google Sheets. Save your work as a new spreadsheet rather than over a CSV file, so the originals stay as they are.
5. Ask the person who asked you to check this work for the HCI full data tables, which check 3 compares against.

These are the files you'll use:

| File | What's in it |
|---|---|
| `senate_amendments/amendments_2025-01-01_to_2026-11-12.csv` | One row per amendment considered in the 119th Congress through November 12, 2026 |
| `senate_amendments/amendments_summary_2025-01-01_to_2026-11-12.csv` | The per-quarter counts made from that file |
| `senate_amendments/amendments_2022-01-01_to_2024-12-31.csv` and its summary file | The same for 2022 through 2024 |
| `cloture/cloture_results_119.csv` | One row per cloture motion in the 119th Congress, plus one row per reconsideration vote |
| `cloture/cloture_summary_119.csv` | The per-quarter cloture counts made from that file |
| `cloture/cloture_results_118.csv` | The same for the 118th Congress, used in the special cases |

## Amendments Spreadsheet Setup

Open `amendments_2025-01-01_to_2026-11-12.csv`. Its columns run from A (Congress) to J (Action Type), with Latest Action Date in column G. Add three columns. Type each header in row 1 and each formula in row 2, then fill the formula down to the last row.

| Column | Header | Formula in row 2 |
|---|---|---|
| K | Quarter | `=YEAR(G2)&" Q"&ROUNDUP(MONTH(G2)/3,0)` |
| L | Category | `=IF(ISNUMBER(SEARCH("amdt",C2)),"Amdts Amended",IF(ISNUMBER(SEARCH("con",C2)),"Budget Resolutions",IF(ISNUMBER(SEARCH("res",C2)),"Resolutions Amended","Bills Amended")))` |
| M | Side | `=IF(LEFT(A2,3)="119",IF(H2="R","Majority","Minority"),IF(H2="R","Minority","Majority"))` |

The formulas apply the README's rules:

- Quarter comes from the date of the amendment's latest action.
- Category looks at what the amendment amends and checks, in order, for an amendment, a concurrent ("Con") resolution, any other resolution, and anything else.
- Side comes from the sponsor's party. Democrats held the majority in the 117th and 118th Congresses, and Republicans hold it in the 119th. Independents, whose Sponsor Party is blank, count with the Democrats.

Check a few rows to make sure each Quarter matches its date. If the Quarter column shows errors, the spreadsheet didn't read column G as dates. In Google Sheets, import the file with **File > Import** and leave "Convert text to numbers, dates, and formulas" checked.

## 1. Amendments: Completeness

This checks that the CSV has every amendment that Congress.gov's own search finds. Check at least three quarters, including October through December 2025, the largest.

1. Go to https://www.congress.gov/advanced-search/command-line and search for the following, with the quarter's first and last days:

   ```text
   actionCode:(94000 OR 95000) latestActionDateStr:["2025-10-01" TO "2025-12-31"] billType:"SAmdt"
   ```

   Action code 94000 means the Senate agreed to an amendment, and 95000 means it did not. The search finds Senate amendments with either code whose latest action falls in the date range.
2. Write down how many results Congress.gov finds.
3. Count the spreadsheet's rows for the same quarter, for example with `=COUNTIF(K:K,"2025 Q4")`.
4. If the counts differ, filter the spreadsheet to that quarter, compare its amendment numbers with the search results, and look up each amendment that appears in only one place.

The CSV was made on November 12, 2026. Congress.gov keeps updating, so an amendment acted on after that date can move to a later quarter. Note those differences, but don't count them as errors.

## 2. Amendments: Row Spot Checks

This checks every field for a random sample of rows from the 2025 through 2026 spreadsheet.

1. Pick 15 rows at random. Add a column with `=RAND()` in every row, sort the sheet by that column, and take the first 15 rows. `RAND()` changes every time the sheet recalculates, so copy the 15 amendment numbers into your log right away.
2. Paste each row's url into your browser and check the following:
   - The sponsor, the sponsor's party, and what the amendment amends match the page. For an amendment to another amendment, Amends is that amendment's number, sometimes followed by the one it amends, as in `S.Amdt.2848 (which amends S.Amdt.2360)`. Check the first number against the page.
   - Latest Action and Latest Action Date match the latest action on the page.
   - The amendment's actions include one in which the Senate agreed to it or did not agree to it. That is why it counts.
   - Outcome is `A` if the Senate agreed to the amendment and `NA` if it did not.
   - Action Type is `UC` for unanimous consent, `VV` for a voice vote, and `RCV` for a recorded (yea-nay) vote.
   - Category fits what the amendment amends.
3. Rows with a blank Sponsor Party should be independents. In this file, they are Sens. Bernie Sanders (I-VT) and Angus King (I-ME).

## 3. Amendments: Quarterly Counts

This checks the per-quarter counts against the CSV and against what was published.

1. Make a pivot table from the spreadsheet: in Excel, **Insert > PivotTable**, and in Google Sheets, **Insert > Pivot table**. Put Quarter in rows and S.Amdt.No in values as a count (COUNTA in Google Sheets).
2. Compare the pivot table with `amendments_summary_2025-01-01_to_2026-11-12.csv` four times. Each time, use one column field from this table, or none, and remove the previous one:

   | Column field | Summary rows to compare |
   |---|---|
   | None | Total Amendments |
   | Side | Majority and Minority |
   | Category | Bills Amended, Resolutions Amended, Amdts Amended, and Budget Resolutions |
   | Action Type | UC, VV, and RCV |

   The summary file lists quarters across the top, so it's the pivot table turned on its side.
3. For each measure in the Budget Resolutions category, confirm on Congress.gov that it sets the congressional budget, and list any that don't.
4. Set up `amendments_2022-01-01_to_2024-12-31.csv` the same way and compare it with its summary file. Two things are different in this file:
   - Three rows have the Action Type `INPUT BY HAND`: S.Amdt.5027, S.Amdt.5193, and S.Amdt.3292. They count in Total Amendments but not in UC, VV, or RCV, so the Action Type pivot table shows them in a column of their own.
   - The rows with a blank Sponsor Party are Sanders and former Sen. Kyrsten Sinema, both independents.
5. Compare 2023 and 2024, which make up the 118th Congress, with the "Senate Amendments Considered" sheet in the HCI full data tables. The sheet shows running totals within each Congress, so add up the quarters in `amendments_summary_2022-01-01_to_2024-12-31.csv`, starting with 2023 Q1, and compare every row the sheet has. Budget Resolutions isn't a running total in the sheet, so compare it quarter by quarter. Skip 2022, because its running totals start in 2021, before this file begins.

## 4. Cloture: Recount One Quarter

This counts legislative cloture votes straight from the Senate's page.

1. Open https://www.senate.gov/legislative/cloture/119.htm. The page has a table for each year that motions were filed, newest first. Each table shows 100 rows at a time, so set the menu above it to All. The dates leave out the year, so take the year from the table's heading. Under "Action and Result" are the day of the vote, the tally and roll call vote number, and a result code: `I` (invoked), `F` (failed), `N` (no action), `V` (vitiated), or `W` (withdrawn).
2. Pick a quarter, such as January through March 2026. Go by the date in the first column, when the motion was filed, not the day of the vote. Among motions filed in that quarter, skip the nominations, which are rows whose Measure is "Various" or a PN number, even if the subject says "motion to proceed." Everything else counts as legislation, including motions to proceed and treaties.
3. Count each `I` and each `F` as one vote. A reconsidered motion shows two votes on one row. Count both.
4. Compare your counts with the `Legislation-Votes`, `Legislation-Voted Inv`, and `Legislation-Votes Failed` rows of `cloture/cloture_summary_119.csv`. Its columns are quarters by filing date, such as Q1-2026. The Motion to Proceed rows are part of Legislation, so you don't need them.

Count the executive resolutions (S.Res.) that authorize en bloc consideration of nominations as legislation, as the README explains. Their subject begins "Executive resolution authorizing the en bloc consideration."

## 5. Cloture: Special Cases

Check each case below against the Senate's cloture page and the roll call vote pages, comparing the dates, the tally, the vote number, and the result. Roll call vote N in session S of Congress C is at `https://www.senate.gov/legislative/LIS/roll_call_votes/vote{C}{S}/vote_{C}_{S}_{N}.htm`, with N padded to five digits. Session 1 is a Congress's first year, and session 2 is its second. For example, vote 219 in the second session of the 118th Congress, in 2024, is at https://www.senate.gov/legislative/LIS/roll_call_votes/vote1182/vote_118_2_00219.htm. On a roll call page, "Agreed to" means cloture was invoked (`I`), and "Rejected" means it failed (`F`).

- **Reconsidered motions.** A row whose Subject ends in "Vote No. N reconsidered" is the second vote on a motion. Pick two in `cloture/cloture_results_119.csv` and check both votes.
- **En bloc nominations.** Rows whose Measure is "Various" are nominations. Check two of them on the Senate's page.
- **A missing result.** The Senate's table shows no result for the July 25, 2024, cloture vote on S.2073 (vote 219). `cloture/cloture_results_118.csv` says `I`. Confirm on the roll call page that cloture was invoked 86-1.
- **A vote in the next year.** PN1020 was filed on December 19, 2023, and voted on January 8, 2024. Its Date of Motion in `cloture/cloture_results_118.csv` should be in 2024. Its Quarter and Year stay 4 and 2023, because quarters follow the date filed.

## What These Checks Don't Cover

- The automated tests and fresh runs of the code, which the README describes
- The `working_days/` folder, which wasn't part of this rebuild
- `scrape_amendments`, the old Congress.gov scraper kept as a fallback

## Log

Copy this table into a document or spreadsheet and fill it in.

| Check | What you compared | Result | Differences |
|---|---|---|---|
| 1. Amendments: completeness | Quarters: | | |
| 2. Amendments: row spot checks | Amendment numbers: | | |
| 3. Amendments: quarterly counts | | | |
| 4. Cloture: recount | Quarter: | | |
| 5. Cloture: special cases | | | |

For each difference, note the file and row (or the amendment or measure number), what the file says, what the source says, and a link to the source. Don't change the CSV files. Send the log to the person who asked you to check this work.
