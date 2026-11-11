"""Cloture motions for the Healthy Congress Index.

Reads the Senate's cloture tables (https://www.senate.gov/legislative/cloture/{congress}.htm)
with a plain HTTP request; no browser is needed.

Counting rules are unchanged from the original HCI scripts (see README.md):
- A row whose Subject mentions "motion to proceed" is a Motion to Proceed; otherwise a row whose
  Measure contains "PN" is a Nomination; everything else is Legislation. The Legislation group in
  the summary includes motions to proceed (and treaties).
- A reconsidered motion is listed on one row with two vote dates, votes, and results. It is split
  into two rows: the original vote, and a copy whose Subject keeps the "Vote No. X reconsidered" note.
- Votes Invoked counts Result "I", Votes Failed counts Result "F" (both include reconsidered votes),
  Votes = Invoked + Failed, Reconsidered counts rows whose Subject contains "recons", and
  Motions Filed = rows - Reconsidered.
- Quarters are assigned by the date the motion was filed.
"""
from datetime import date, datetime

import pandas as pd
import requests
from lxml import html

URL = "https://www.senate.gov/legislative/cloture/{congress}.htm"
TABLE_IDS = ("ClotureMotions1st", "ClotureMotions2nd")
GROUPS = ("Legislation", "Nomination", "Motion to Proceed")
METRICS = ("Motions Filed", "Votes", "Voted Inv", "Votes Failed", "Reconsidered")
COLUMNS = ["Date Filed", "Measure", "Legislation Type", "Subject", "Filed By",
           "Date of Motion", "Vote", "Vote No.", "Result", "Quarter", "Year"]

_SEP = ""  # private-use character standing in for <br>, so a cell can be split into its lines


def _cell_lines(td):
    """Return a cell's <br>-separated lines, with footnote markers and hidden sort keys removed."""
    for el in td.xpath('.//sup | .//span[@style="display:none"]'):
        el.drop_tree()
    for br in td.xpath(".//br"):
        br.tail = _SEP + (br.tail or "")
    lines = (" ".join(part.split()) for part in td.text_content().split(_SEP))
    return [line for line in lines if line]


def _parse_vote_day(text, filed):
    """Parse a vote date such as 'Jan 8', 'July 21', or 'Mar 21, 2024' (year defaults to filing year)."""
    text = text.replace("Sept", "Sep")
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d", "%B %d"):
        try:
            parsed = datetime.strptime(text, fmt).date()
        except ValueError:
            continue
        if "%Y" not in fmt:
            parsed = parsed.replace(year=filed.year)
        return parsed
    return None


def legislation_type(measure, subject):
    if "motion to proceed" in subject:
        return "Motion to Proceed"
    if "PN" in measure:
        return "Nomination"
    return "Legislation"


def parse_cloture_page(page_html):
    """Turn one Congress's cloture page into one row per cloture vote (reconsidered votes split out)."""
    if isinstance(page_html, bytes):
        # The pages are UTF-8 (per the HTTP header) but also carry an iso-8859-1 meta tag; decode
        # explicitly so lxml does not have to guess.
        page_html = page_html.decode("utf-8", errors="replace")
    root = html.fromstring(page_html)
    rows = []
    for table_id in TABLE_IDS:
        tables = root.xpath(f'//table[@id="{table_id}"]')
        if not tables:
            continue  # the second-session table does not exist yet early in a Congress
        table = tables[0]
        header = table.xpath('.//thead//th[starts-with(normalize-space(), "Motions Filed in")]')
        year = int(header[0].text_content().split()[-1])

        for tr in table.xpath("./tbody/tr"):
            tds = tr.xpath("./td")
            sort_key = tds[0].xpath('string(.//span[@style="display:none"])').strip()  # "MMDD"
            filed = date(year, int(sort_key[:2]), int(sort_key[2:]))
            measure = " ".join(_cell_lines(tds[1]))
            subject_lines = _cell_lines(tds[2])
            filed_by = " ".join(_cell_lines(tds[3]))
            days, votes, results = _cell_lines(tds[4]), _cell_lines(tds[5]), _cell_lines(tds[6])

            n = max(len(days), len(votes), len(results), 1)
            for i in range(n):
                if i == 0:  # the original vote: drop the "Vote No. X reconsidered" note
                    subject = ", ".join(s for s in subject_lines if "reconsidered" not in s)
                else:       # the reconsideration vote keeps the note
                    subject = ", ".join(subject_lines)
                vote = votes[i] if i < len(votes) else ""
                vote_text, _, vote_no = vote.partition("No.")
                day = days[i] if i < len(days) else ""
                rows.append({
                    "Date Filed": filed,
                    "Measure": measure,
                    "Legislation Type": legislation_type(measure, subject),
                    "Subject": subject,
                    "Filed By": filed_by,
                    "Date of Motion": _parse_vote_day(day, filed) if day else None,
                    "Vote": vote_text.strip(),
                    "Vote No.": f"No. {vote_no.strip()}" if vote_no else "",
                    "Result": results[i] if i < len(results) else "",
                    "Quarter": (filed.month - 1) // 3 + 1,
                    "Year": filed.year,
                })
    return pd.DataFrame(rows, columns=COLUMNS)


def scrape_cloture(congress, start=None, end=None):
    """Cloture rows for one Congress, optionally limited to motions filed between start and end
    (inclusive, MM/DD/YYYY)."""
    response = requests.get(URL.format(congress=congress), timeout=60)
    response.raise_for_status()
    results = parse_cloture_page(response.content)
    if start:
        results = results[results["Date Filed"] >= datetime.strptime(start, "%m/%d/%Y").date()]
    if end:
        results = results[results["Date Filed"] <= datetime.strptime(end, "%m/%d/%Y").date()]
    return results.reset_index(drop=True)


def summarize_cloture(results):
    """Per-quarter counts (not cumulative) for each group, in the layout of the old cloture_summary CSVs."""
    years = sorted(results["Year"].unique())
    quarters = [(y, q) for y in years for q in range(1, 5)]
    summary = pd.DataFrame(0, index=[f"{g}-{m}" for g in GROUPS for m in METRICS],
                           columns=[f"Q{q}-{y}" for y, q in quarters])
    for group in GROUPS:
        if group == "Legislation":
            in_group = results["Legislation Type"] != "Nomination"
        else:
            in_group = results["Legislation Type"] == group
        for y, q in quarters:
            df = results[in_group & (results["Year"] == y) & (results["Quarter"] == q)]
            reconsidered = df["Subject"].str.contains("recons").sum()
            invoked, failed = (df["Result"] == "I").sum(), (df["Result"] == "F").sum()
            col = f"Q{q}-{y}"
            summary.loc[f"{group}-Motions Filed", col] = len(df) - reconsidered
            summary.loc[f"{group}-Votes", col] = invoked + failed
            summary.loc[f"{group}-Voted Inv", col] = invoked
            summary.loc[f"{group}-Votes Failed", col] = failed
            summary.loc[f"{group}-Reconsidered", col] = reconsidered
    return summary


def published_rows(summary):
    """The three rows posted in the HCI full data tables: cumulative legislative cloture votes,
    votes invoked, and votes failed, by quarter of the Congress."""
    rows = {
        "Votes on Cloture - Legislation": "Legislation-Votes",
        "Cloture Votes Invoked - Legislation": "Legislation-Voted Inv",
        "Cloture Votes Failed - Legislation": "Legislation-Votes Failed",
    }
    return pd.DataFrame({label: summary.loc[row].cumsum() for label, row in rows.items()}).T
