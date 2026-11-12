# Checking This Work

In November 2026, the code that collects two Healthy Congress Index (HCI) metrics was rebuilt. Senate amendments considered now come from the Congress.gov API, and cloture on legislation comes from the Senate's cloture tables. The [README](README.md) explains the counting rules, and its Validation section lists the comparisons already run against the old code.

The checks below test the work independently. Most compare the data files with Congress.gov and Senate.gov by hand, so they don't rely on the code being right. Expect them to take about half a day. Record what you find in the [log](#log) at the end.

## Before You Start

1. Set up the repo:

   ```bash
   git clone https://github.com/wrenorey/healthy-congress-index.git
   cd healthy-congress-index
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

   On Windows, activate with `.venv\Scripts\activate`.

2. Read the README sections "Senate Amendments Considered" and "Filibuster and Cloture on Legislation." The checks test those rules.
3. Run the Python snippets below from the top of the repo, in `python` or a notebook.
4. You can browse a CSV in Excel or Google Sheets, but don't save it from there, because Excel changes the date formats. In Python, load it with `pd.read_csv(path, keep_default_na=False)`. Otherwise, pandas reads the outcome code `NA` as a missing value.

## 1. Automated Tests

```bash
pytest tests
```

Expect `23 passed`. The tests confirm that the code reproduces the published legislative cloture numbers for the 116th Congress and the first session of the 117th Congress, and the published amendment numbers for 2022 through 2024. They also cover several special cases. If any test fails, stop and send the output.

## 2. Amendments: Completeness

This checks that the CSV has every amendment that Congress.gov's own search finds. Check at least three quarters, including October through December 2025, the largest.

1. Go to https://www.congress.gov/advanced-search/command-line and search for the following, with the quarter's first and last days:

   ```text
   actionCode:(94000 OR 95000) latestActionDateStr:["2025-10-01" TO "2025-12-31"] billType:"SAmdt"
   ```

   Action code 94000 means the Senate agreed to an amendment, and 95000 means it did not. The search finds Senate amendments with either code whose latest action falls in the date range.
2. Write down how many results Congress.gov finds.
3. Count the CSV's rows for the same quarter:

   ```python
   import pandas as pd
   df = pd.read_csv("senate_amendments/amendments_2025-01-01_to_2026-11-12.csv", keep_default_na=False)
   when = pd.to_datetime(df["Latest Action Date"], format="%m/%d/%y")
   quarter = df[(when >= "2025-10-01") & (when <= "2025-12-31")]
   print(len(quarter))
   print(sorted(quarter["S.Amdt.No"]))
   ```

4. If the counts differ, compare the amendment numbers with the search results and look up each one that appears in only one place.

The CSV was made on November 12, 2026. Congress.gov keeps updating, so an amendment acted on after that date can move to a later quarter. Note those differences, but don't count them as errors.

## 3. Amendments: Row Spot Checks

This checks every field for a random sample of rows.

1. Draw 15 rows. Replace `1234` with a number of your choosing and write it in your log, so the sample isn't one the author picked:

   ```python
   sample = df.sample(15, random_state=1234)
   sample[["S.Amdt.No", "Amends", "Sponsor", "Latest Action", "Latest Action Date", "Outcome", "Action Type", "url"]]
   ```

2. Open each row's `url` and check the following:
   - The sponsor, the sponsor's party, and what the amendment amends match the page. For an amendment to another amendment, Amends is that amendment's number.
   - Latest Action and Latest Action Date match the latest action on the page.
   - The amendment's actions include one in which the Senate agreed to it or did not agree to it. That is why it counts.
   - Outcome is `A` if the Senate agreed to the amendment and `NA` if it did not.
   - Action Type is `UC` for unanimous consent, `VV` for a voice vote, and `RCV` for a recorded (yea-nay) vote.
3. Rows with a blank Sponsor Party should be independents, who count with the Democrats. So far, they are Sens. Bernie Sanders (I-VT) and Angus King (I-ME).

## 4. Amendments: Quarterly Counts

This checks that the quarterly table follows from the CSV and matches what was published.

1. Print the table:

   ```python
   import sys
   sys.path.insert(0, "senate_amendments")
   import amendments_helper
   amendments_helper.quarterly_summary(df)
   ```

2. Pick one quarter and recount it by hand using the README's rules: the total, the majority and minority (Republicans hold the majority in the 119th Congress), the four categories, and UC, VV, and RCV.
3. Compare the published "Senate Amendments Considered" sheet in the HCI full data tables with `quarterly_summary` for `amendments_2022-01-01_to_2024-12-31.csv`. The sheet is cumulative within each Congress, except for budget resolutions, so add up the quarters before comparing. The sheet's 2022 totals also include 2021, which the CSV doesn't, so for 2022, compare the change from one quarter to the next.

## 5. Cloture: Recount One Quarter

This counts legislative cloture votes straight from the Senate's page.

1. Open https://www.senate.gov/legislative/cloture/119.htm. Motions are listed by the date they were filed. Under "Action and Result" are the day of the vote, the tally and roll call vote number, and a result code: `I` (invoked), `F` (failed), `N` (no action), `V` (vitiated), or `W` (withdrawn).
2. Pick a quarter, such as January through March 2026. Among motions filed in that quarter, skip the nominations, which are rows whose Measure is "Various" or a PN number. Everything else counts as legislation, including motions to proceed and treaties.
3. Count each `I` and each `F` as one vote. A reconsidered motion shows two votes on one row. Count both.
4. Compare your counts with the `Legislation-Votes`, `Legislation-Voted Inv`, and `Legislation-Votes Failed` rows of `cloture/cloture_summary_119.csv`.
5. Check that the cumulative table, which `cloture/cloture.ipynb` prints with `published_rows`, adds up the quarters correctly.

The executive resolutions (S.Res.) that authorize en bloc consideration of nominations count as legislation for now, as the README explains. If your quarter has any, note how many, because that decision may change.

## 6. Cloture: Special Cases

Check each case below against the Senate's cloture page and the roll call vote pages. Roll call vote N in session S of Congress C is at `https://www.senate.gov/legislative/LIS/roll_call_votes/vote{C}{S}/vote_{C}_{S}_{N}.htm`, with N padded to five digits. For example, vote 219 in the second session of the 118th Congress is at https://www.senate.gov/legislative/LIS/roll_call_votes/vote1182/vote_118_2_00219.htm.

- **Reconsidered motions.** A row whose Subject ends in "Vote No. N reconsidered" is the second vote on a motion. Pick two in `cloture/cloture_results_119.csv` and check both votes.
- **En bloc nominations.** Rows whose Measure is "Various" are nominations. Check two of them on the Senate's page.
- **A missing result.** The Senate's table shows no result for the July 25, 2024, cloture vote on S.2073 (vote 219). `cloture/cloture_results_118.csv` says `I`. Confirm on the roll call page that cloture was invoked 86-1.
- **A vote in the next year.** PN1020 was filed on December 19, 2023, and voted on January 8, 2024. Its Date of Motion in `cloture/cloture_results_118.csv` should be in 2024.

## 7. Fresh Rerun (Optional)

This checks that the code gives the same results when run again. Each notebook overwrites its CSV files, and git shows what changed.

1. **Cloture.** Open `cloture/cloture.ipynb`, set `CONGRESSES = [119]`, and run all cells. Then run `git diff --stat cloture`. Differences should involve only motions filed or voted on after November 12, 2026. Note any others.
2. **Amendments.** Get a free key at https://api.congress.gov/sign-up/ and save it in a file named `.congress_api_key` at the top of the repo. Git ignores this file. Open `senate_amendments/amendments.ipynb`, set `START, END = "01/01/2025", "11/12/2026"`, and run all cells, which takes 10 to 20 minutes. Then run `git diff senate_amendments`. Differences should involve only amendments that Congress.gov changed after November 12, 2026. Note any others.
3. When you're done, run `git checkout -- cloture senate_amendments` to restore the committed files.

## What These Checks Don't Cover

- The `working_days/` folder, which wasn't part of this rebuild
- `scrape_amendments`, the old Congress.gov scraper kept as a fallback

## Log

Copy this table into a document or spreadsheet and fill it in.

| Check | What you compared | Result | Differences |
|---|---|---|---|
| 1. Automated tests | | | |
| 2. Amendments: completeness | Quarters: | | |
| 3. Amendments: row spot checks | Your number: | | |
| 4. Amendments: quarterly counts | Quarter: | | |
| 5. Cloture: recount | Quarter: | | |
| 6. Cloture: special cases | | | |
| 7. Fresh rerun | | | |

For each difference, note the file and row (or the amendment or measure number), what the file says, what the source says, and a link to the source. Don't edit the CSV files by hand. Fixes go through the code, or through `OVERRIDES` in the amendments notebook, so the next run keeps them. Send the log to the person who asked you to check this work.
