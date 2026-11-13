"""Cloture motions for the Healthy Congress Index.

Reads the Senate's cloture tables (https://www.senate.gov/legislative/cloture/{congress}.htm)
with a plain HTTP request; no browser is needed.

Counting rules (from the original HCI scripts and the Internal HCI Methodology):
- A row whose Measure contains "PN" is a Nomination, even when its Subject says "motion to proceed"
  (the original summaries grouped rows by Measure). Otherwise a row whose Subject mentions "motion
  to proceed" is a Motion to Proceed, and everything else is Legislation. The Legislation group in
  the summary includes motions to proceed (and treaties).
- A reconsidered motion is listed on one row with two vote dates, votes, and results. It is split
  into two rows: the original vote, and a copy whose Subject keeps the "Vote No. X reconsidered" note.
- Votes Invoked counts Result "I", Votes Failed counts Result "F" (both include reconsidered votes),
  Votes = Invoked + Failed, Reconsidered counts rows whose Subject contains "recons", and
  Motions Filed = rows - Reconsidered.
- Quarters are assigned by the date the motion was filed.

Deliberate changes from the original scripts:
- Reconsidered rows are split on the table's line breaks, not on commas. (The original split titles
  that contain commas, so it could type a reconsidered motion to proceed as Legislation.)
- Date filters are inclusive. (The original dropped motions filed on the last day of a range.)
- En bloc nominations, which the Senate has listed since 2025 with Measure "Various" and the PN numbers
  in the Subject, count as Nominations, and so do the executive resolutions (S.Res.) that authorize
  en bloc consideration (decided November 2026). S.Res.50 in 2019, a general change to nomination
  procedure, stays Legislation, as in the published 116th Congress numbers.
- A recorded vote that the table lists without a result code gets its result from the official roll
  call (scrape_cloture prints each one it fills).
"""
import re
from datetime import date, datetime

import pandas as pd
import requests
from lxml import etree, html

URL = "https://www.senate.gov/legislative/cloture/{congress}.htm"
ROLL_CALL_URL = ("https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress}{session}/"
                 "vote_{congress}_{session}_{number:05d}.xml")
TABLE_IDS = ("ClotureMotions1st", "ClotureMotions2nd")
GROUPS = ("Legislation", "Nomination", "Motion to Proceed")
METRICS = ("Motions Filed", "Votes", "Voted Inv", "Votes Failed", "Reconsidered")
COLUMNS = ["Date Filed", "Measure", "Legislation Type", "Subject", "Filed By",
           "Date of Motion", "Vote", "Vote No.", "Result", "Quarter", "Year"]

LEGISLATIVE_MEASURE = re.compile(r"^(H\.R\.|S\.|H\.J\.Res\.|H\.Res\.|H\.Con\.Res\.|Treaty Doc\.)")
NOMINATION_IN_SUBJECT = re.compile(r"\bPN\d")
EN_BLOC = re.compile(r"\ben bloc consideration\b", re.IGNORECASE)
_SEP = ""  # private-use character standing in for <br>, so a cell can be split into its lines


def _cell_lines(td):
    """Return a cell's <br>-separated lines, with footnote markers and hidden sort keys removed."""
    for el in td.xpath('.//sup | .//span[@style="display:none"]'):
        el.drop_tree()
    for br in td.xpath(".//br"):
        br.tail = _SEP + (br.tail or "")
    lines = (" ".join(part.split()) for part in td.text_content().split(_SEP))
    return [line for line in lines if line]


def _parse_day(text, year=None):
    """'Jan 8', 'July 21', 'Sept 3', 'September 17', or 'Mar 21, 2024' -> date. A year in the text
    wins over the year argument."""
    text = re.sub(r"\bSept\b", "Sep", text.replace(".", "").strip())
    if not re.search(r"\d{4}$", text):
        if year is None:
            return None
        text = f"{text}, {year}"
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _vote_date(text, filed):
    """A vote date such as 'Jan 8' is the first such date on or after the filing date (a motion filed
    in December can be voted on in January). Dates that show their year are taken as written."""
    if re.search(r"\d{4}\s*$", text):
        return _parse_day(text)
    for year in (filed.year, filed.year + 1):
        day = _parse_day(text, year)
        if day and day >= filed:
            return day
    return _parse_day(text, filed.year)


def legislation_type(measure, subject):
    if "PN" in measure:  # even a motion to proceed to a nomination, as in the original summaries
        return "Nomination"
    if EN_BLOC.search(subject):  # en bloc nominations, and the S.Res. that authorize them
        return "Nomination"
    if not LEGISLATIVE_MEASURE.match(measure) and NOMINATION_IN_SUBJECT.search(subject):
        return "Nomination"  # en bloc nominations: Measure "Various", PN numbers in the Subject
    if "motion to proceed" in subject:
        return "Motion to Proceed"
    return "Legislation"


def parse_cloture_page(page_html):
    """Turn one Congress's cloture page into one row per cloture motion, plus one row for each
    reconsideration vote. Prints a warning for anything that looks inconsistent."""
    if isinstance(page_html, bytes):
        # The pages are UTF-8 (per the HTTP header) but also carry an iso-8859-1 meta tag; decode
        # explicitly so lxml does not have to guess.
        page_html = page_html.decode("utf-8", errors="replace")
    root = html.fromstring(page_html)
    rows, warnings = [], []
    for table_id in TABLE_IDS:
        tables = root.xpath(f'//table[@id="{table_id}"]')
        if not tables:
            continue  # the second-session table does not exist yet early in a Congress
        table = tables[0]
        header = table.xpath('.//th[starts-with(normalize-space(), "Motions Filed in")]')
        year = int(header[0].text_content().split()[-1])
        trs = table.xpath("./tbody/tr") or table.xpath(".//tr[td]")
        if not trs:
            raise ValueError(f"The {table_id} table on the Senate's page has no rows; has the layout changed?")

        for tr in trs:
            tds = tr.xpath("./td")
            sort_key = tds[0].xpath('string(.//span[@style="display:none"])').strip()
            visible = " ".join(_cell_lines(tds[0]))
            filed = _parse_day(visible, year)
            try:
                keyed = date(year, int(sort_key[:-2]), int(sort_key[-2:]))
            except ValueError:
                keyed = None
            if filed is None:
                filed = keyed
            elif keyed != filed:
                warnings.append(f"{table_id}: visible date {visible!r} and sort key {sort_key!r} disagree; "
                                f"using {filed}")
            if filed is None:
                raise ValueError(f"Cannot read the filing date {visible!r} (sort key {sort_key!r}) in {table_id}")

            measure = " ".join(_cell_lines(tds[1]))
            subject_lines = _cell_lines(tds[2])
            filed_by = " ".join(_cell_lines(tds[3]))
            days, votes, results = _cell_lines(tds[4]), _cell_lines(tds[5]), _cell_lines(tds[6])
            if not (len(days) == len(votes) == len(results)):
                warnings.append(f"{filed} {measure}: {len(days)} vote date(s), {len(votes)} vote(s), and "
                                f"{len(results)} result(s) listed")
            if not ("PN" in measure or LEGISLATIVE_MEASURE.match(measure) or measure == "Various"):
                warnings.append(f"{filed}: unfamiliar Measure {measure!r}; check how it is classified")

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
                    "Date of Motion": _vote_date(day, filed) if day else None,
                    "Vote": vote_text.strip(),
                    "Vote No.": f"No. {vote_no.strip()}" if vote_no else "",
                    "Result": results[i] if i < len(results) else "",
                    "Quarter": (filed.month - 1) // 3 + 1,
                    "Year": filed.year,
                })
    for warning in warnings:
        print("WARNING:", warning)
    return pd.DataFrame(rows, columns=COLUMNS)


def roll_call_result(congress, vote_day, vote_no):
    """'I' or 'F' for a cloture vote, from the Senate's roll call record (None if it can't be read)."""
    first_year = 1789 + 2 * (congress - 1)
    session = 1 if vote_day.year == first_year else 2
    number = int(re.sub(r"\D", "", vote_no))
    try:
        response = requests.get(ROLL_CALL_URL.format(congress=congress, session=session, number=number),
                                timeout=60)
        response.raise_for_status()
        result = etree.fromstring(response.content).findtext("vote_result") or ""
    except (requests.RequestException, etree.XMLSyntaxError):
        return None
    if "Agreed" in result:
        return "I"
    if "Rejected" in result:
        return "F"
    return None


def fill_missing_results(results, congress):
    """Fill in the result of recorded votes that the cloture table lists without one."""
    missing = (results["Result"] == "") & (results["Vote No."] != "") & results["Date of Motion"].notna()
    for i in results.index[missing]:
        row = results.loc[i]
        result = roll_call_result(congress, row["Date of Motion"], row["Vote No."])
        if result:
            results.loc[i, "Result"] = result
            print(f"Filled in missing result {result!r} for {row['Measure']} vote {row['Vote No.']} "
                  f"({row['Date of Motion']}) from the Senate roll call")
        else:
            print(f"WARNING: {row['Measure']} vote {row['Vote No.']} has no result; check it by hand")
    return results


def scrape_cloture(congress, start=None, end=None):
    """Cloture rows for one Congress, optionally limited to motions filed between start and end
    (inclusive, MM/DD/YYYY). For the published table, scrape the whole Congress (see published_rows)."""
    response = requests.get(URL.format(congress=congress), timeout=60)
    response.raise_for_status()
    results = fill_missing_results(parse_cloture_page(response.content), congress)
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
    votes invoked, and votes failed, by quarter of the Congress. The running totals start at the first
    quarter in the summary, so pass the summary of a whole Congress."""
    rows = {
        "Votes on Cloture - Legislation": "Legislation-Votes",
        "Cloture Votes Invoked - Legislation": "Legislation-Voted Inv",
        "Cloture Votes Failed - Legislation": "Legislation-Votes Failed",
    }
    return pd.DataFrame({label: summary.loc[row].cumsum() for label, row in rows.items()}).T
