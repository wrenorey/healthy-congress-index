"""Senate amendments considered, for the Healthy Congress Index.

An amendment is "considered" if it was agreed to or not agreed to on the Senate floor (by roll call,
voice vote, or unanimous consent): Library of Congress action code 94000 (Senate amendment agreed
to) or 95000 (not agreed to). Amendments are dated by their latest action.

Two ways to collect the data, which return the same columns:
- fetch_amendments(): the official Congress.gov API. Runs headless and takes 10-20 minutes. It needs
  a free API key (https://api.congress.gov/sign-up/), saved in a file named .congress_api_key at
  the top of the repo or in the CONGRESS_API_KEY environment variable.
- scrape_amendments(): the original Congress.gov search-page scraper. Opens a visible Chrome
  window, because Congress.gov blocks headless browsers. Kept as a fallback.
"""
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests

COLUMNS = ["Congress", "S.Amdt.No", "Amends", "Sponsor", "Latest Action", "url",
           "Latest Action Date", "Sponsor Party", "Outcome", "Action Type"]

# Party controlling the Senate. Independents caucused with Democrats in all of these Congresses.
SENATE_MAJORITY = {117: "D", 118: "D", 119: "R"}


# ---------------------------------------------------------------------------------------------
# Classification (unchanged from the original scripts)
# ---------------------------------------------------------------------------------------------

def determine_outcome(latest_action):
    if pd.isna(latest_action):
        return "INPUT BY HAND"
    if "not agreed" in latest_action.lower():
        return "NA"  # Not Agreed (read CSVs with keep_default_na=False, or pandas turns this into NaN)
    return "A"       # Agreed


def determine_action_type(latest_action):
    if pd.isna(latest_action):
        return "INPUT BY HAND"
    if "unanimous" in latest_action.lower():
        return "UC"   # Unanimous Consent
    if "Yea-Nay" in latest_action:
        return "RCV"  # Roll Call Vote
    if "Voice Vote" in latest_action:
        return "VV"   # Voice Vote
    return "INPUT BY HAND"


def _add_classification(df):
    # Sponsor Party is R or D; it is blank for independents, as in the original scraper.
    df["Sponsor Party"] = df["Sponsor"].str.extract(r"\[Sen\.-([RD])", expand=False)
    df["Outcome"] = df["Latest Action"].map(determine_outcome)
    df["Action Type"] = df["Latest Action"].map(determine_action_type)
    return df


# ---------------------------------------------------------------------------------------------
# Congress.gov API (headless)
# ---------------------------------------------------------------------------------------------

API = "https://api.congress.gov/v3"
CONSIDERED_CODES = {"94000", "95000"}  # Senate amendment agreed to / not agreed to
DEFAULT_HOURLY_LIMIT = 5000  # used until the API reports the key's actual limit (X-RateLimit-Limit)
KEY_FILE_NAME = ".congress_api_key"  # git-ignored
BILL_TYPES = {"HR": "H.R.", "S": "S.", "HRES": "H.Res.", "SRES": "S.Res.", "HJRES": "H.J.Res.",
              "SJRES": "S.J.Res.", "HCONRES": "H.Con.Res.", "SCONRES": "S.Con.Res."}
NETWORK_ERRORS = (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                  requests.exceptions.ChunkedEncodingError)


def _ordinal(n):
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _congress_of(day):
    """Congress in session on a date (a new Congress starts January 3 of odd years)."""
    year = day.year - 1 if (day.year % 2 == 1 and (day.month, day.day) < (1, 3)) else day.year
    return (year - 1789) // 2 + 1


def _find_api_key(api_key=None):
    """The key passed in, else CONGRESS_API_KEY, else the first .congress_api_key file in this folder
    or any folder above it (so a key saved at the top of the repo is also found from a git worktree)."""
    if api_key:
        return api_key.strip()
    if os.environ.get("CONGRESS_API_KEY"):
        return os.environ["CONGRESS_API_KEY"].strip()
    for folder in Path(__file__).resolve().parents:
        if (folder / KEY_FILE_NAME).is_file():
            return (folder / KEY_FILE_NAME).read_text().strip()
    raise RuntimeError(f"No Congress.gov API key found. Get a free key at https://api.congress.gov/sign-up/ "
                       f"and save it in a file named {KEY_FILE_NAME} at the top of this repo, or set the "
                       "CONGRESS_API_KEY environment variable.")


class _Api:
    """Congress.gov API client. The key is sent in a header, so it never appears in URLs or error
    messages. Requests are paced to the key's hourly limit, and throttling (429), server errors, and
    network errors are retried."""

    def __init__(self, api_key):
        self.session = requests.Session()
        self.session.headers["X-Api-Key"] = api_key
        self.calls = 0
        self.last_start = 0.0
        self.min_interval = 3600 / (0.98 * DEFAULT_HOURLY_LIMIT)  # seconds between request starts

    def get(self, path, **params):
        params["format"] = "json"
        for _ in range(10):
            time.sleep(max(0.0, self.last_start + self.min_interval - time.monotonic()))
            self.last_start = time.monotonic()
            try:
                response = self.session.get(f"{API}/{path}", params=params, timeout=60)
            except NETWORK_ERRORS as error:
                print(f"  network error on {path} ({type(error).__name__}); retrying in 30s")
                time.sleep(30)
                continue
            self.calls += 1
            limit = response.headers.get("X-RateLimit-Limit", "")
            if limit.isdigit() and int(limit) > 0:  # pace to just under this key's hourly limit
                self.min_interval = 3600 / (0.98 * int(limit))
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = response.headers.get("Retry-After", "")
                wait = int(retry_after) if retry_after.isdigit() else 60
                print(f"  API returned {response.status_code} on {path}; waiting {wait}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"Congress.gov API request kept failing: {path}")


def _get_all(api, path, field):
    """Every item from a paged API list."""
    items, offset = [], 0
    while True:
        page = api.get(path, limit=250, offset=offset)
        items += page.get(field, [])
        offset += 250
        if offset >= page["pagination"]["count"]:
            return items


def _list_amendments(api, congress):
    """Every Senate amendment in a Congress, keyed by number. Each listing shows the amendment's
    latest action, if it has one. Records can move between pages while Congress.gov updates them, so
    an incomplete listing is read again with a different page size (so cached pages are not reused)."""
    for page_size in (250, 249, 248):
        listing, offset, count = {}, 0, None
        while count is None or offset < count:
            page = api.get(f"amendment/{congress}/samdt", limit=page_size, offset=offset)
            count = page["pagination"]["count"]
            for item in page.get("amendments", []):
                listing[item["number"]] = item
            offset += page_size
        if len(listing) >= count:
            return listing
        print(f"  the listing changed while it was being read ({len(listing)} of {count}); reading it again")
    raise RuntimeError(f"The list of {_ordinal(congress)} Congress amendments kept changing while it "
                       "was being read. Try again in a few minutes.")


def _amends(detail, details_by_number):
    """What an amendment amends, in Congress.gov's display format (e.g. 'H.R.9468',
    'S.Amdt.6558 (which amends S.Amdt.6552)', 'Treaty Doc. 117-3')."""
    if "amendedAmendment" in detail:
        number = detail["amendedAmendment"]["number"]
        parent = details_by_number.get(number, {})
        if "amendedAmendment" in parent:
            return f"S.Amdt.{number} (which amends S.Amdt.{parent['amendedAmendment']['number']})"
        return f"S.Amdt.{number}"
    if "amendedBill" in detail:
        bill = detail["amendedBill"]
        return f"{BILL_TYPES.get(bill['type'], bill['type'] + '.')}{bill['number']}"
    if "amendedTreaty" in detail:  # the old scraper wrote "N/A" here
        treaty = detail["amendedTreaty"]
        return f"Treaty Doc. {treaty['congress']}-{treaty['treatyNumber']}"
    return "N/A"


def _sponsor(detail):
    """'Sen. Durbin, Richard J. [D-IL]' -> 'Durbin, Richard J. [Sen.-D-IL]' (Congress.gov's display)."""
    sponsors = detail.get("sponsors") or []
    if not sponsors:
        return "N/A"
    name = sponsors[0]["fullName"].removeprefix("Sen. ")
    return re.sub(r"\[(\w+)-(\w+)\]$", r"[Sen.-\1-\2]", name)


def amendment_row(detail, details_by_number):
    congress, number = int(detail["congress"]), detail["number"]
    first_year = 1789 + 2 * (congress - 1)
    action_date = datetime.strptime(detail["latestAction"]["actionDate"], "%Y-%m-%d")
    return {
        "Congress": f"{_ordinal(congress)} Congress ({first_year}-{first_year + 1})",
        "S.Amdt.No": f"S.Amdt.{number}",
        "Amends": _amends(detail, details_by_number),
        "Sponsor": _sponsor(detail),
        "Latest Action": detail["latestAction"]["text"],
        "url": f"congress.gov/amendment/{_ordinal(congress)}-congress/senate-amendment/{number}",
        "Latest Action Date": action_date.strftime("%m/%d/%y"),
    }


def fetch_amendments(start_date, end_date=None, api_key=None):
    """Senate amendments considered whose latest action falls between start_date and end_date
    (MM/DD/YYYY, inclusive; end_date defaults to today), from the Congress.gov API.

    Same selection as the old Congress.gov search: an amendment counts if any of its actions has code
    94000 or 95000, and it is dated by its latest action. Most amendments are submitted but never
    reach the floor and have no latest action, so only the few hundred per Congress whose latest
    action falls in the range are looked up in detail. A run takes 10-20 minutes.
    """
    api = _Api(_find_api_key(api_key))
    start = datetime.strptime(start_date, "%m/%d/%Y").date()
    end = datetime.strptime(end_date, "%m/%d/%Y").date() if end_date else date.today()

    rows = []
    for congress in range(_congress_of(start), _congress_of(end) + 1):
        listing = _list_amendments(api, congress)
        in_range = []
        for number, item in listing.items():
            action_date = (item.get("latestAction") or {}).get("actionDate")
            if action_date and start <= date.fromisoformat(action_date) <= end:
                in_range.append(number)
        print(f"{_ordinal(congress)} Congress: {len(listing)} Senate amendments, "
              f"{len(in_range)} with a latest action in range")

        details = {}
        for i, number in enumerate(in_range, 1):
            actions = _get_all(api, f"amendment/{congress}/samdt/{number}/actions", "actions")
            if any(a.get("actionCode") in CONSIDERED_CODES for a in actions):
                details[number] = api.get(f"amendment/{congress}/samdt/{number}")["amendment"]
            if i % 50 == 0:
                print(f"  {i}/{len(in_range)} checked, {len(details)} considered so far")

        parents = dict(details)  # to show "S.Amdt.X (which amends S.Amdt.Y)"
        for detail in details.values():
            parent = (detail.get("amendedAmendment") or {}).get("number")
            if parent and parent not in parents:
                parents[parent] = api.get(f"amendment/{congress}/samdt/{parent}")["amendment"]
        rows += [amendment_row(detail, parents) for detail in details.values()]

    print(f"Done: {len(rows)} amendments considered ({api.calls} API requests)")
    df = pd.DataFrame(rows, columns=COLUMNS[:-3])
    df = _add_classification(df)
    df["_sort"] = pd.to_datetime(df["Latest Action Date"], format="%m/%d/%y")
    df["_num"] = df["S.Amdt.No"].str.extract(r"(\d+)", expand=False).astype(int)
    df = df.sort_values(["_sort", "_num"], ascending=False).drop(columns=["_sort", "_num"])
    return df[COLUMNS].reset_index(drop=True)


# ---------------------------------------------------------------------------------------------
# Summary for the HCI full data tables
# ---------------------------------------------------------------------------------------------

def amends_category(amends):
    """Mutually exclusive categories, as in the HCI methodology and the published tables."""
    text = str(amends).lower()
    if "amdt" in text:
        return "Amdts Amended"
    if "con" in text:
        return "Budget Resolutions"
    if "res" in text:
        return "Resolutions Amended"
    return "Bills Amended"


def quarterly_summary(df, independents_caucus_with="D"):
    """Per-quarter counts (not cumulative) by latest action date, matching the rows of the
    'Senate Amendments Considered' sheet. Majority and minority use SENATE_MAJORITY for each
    amendment's Congress, so a date range may span two Congresses."""
    df = df.copy()
    when = pd.to_datetime(df["Latest Action Date"], format="%m/%d/%y", errors="coerce")
    if when.isna().any():
        undated = ", ".join(df.loc[when.isna(), "S.Amdt.No"])
        raise ValueError(f"Fill in the Latest Action Date by hand for: {undated}")
    df["Quarter"] = when.dt.year.astype(str) + " Q" + when.dt.quarter.astype(str)

    congress = df["Congress"].str.extract(r"^(\d+)", expand=False).astype(int)
    missing = sorted(set(congress) - set(SENATE_MAJORITY))
    if missing:
        raise ValueError(f"Add the Senate majority party for Congress {missing} to SENATE_MAJORITY")
    majority = congress.map(SENATE_MAJORITY)
    caucus = df["Sponsor"].str.extract(r"\[Sen\.-([RDI])", expand=False).replace("I", independents_caucus_with)
    df["Majority"] = caucus == majority
    df["Minority"] = caucus.notna() & (caucus != majority)

    df["Category"] = df["Amends"].map(amends_category)
    summary = df.groupby("Quarter").agg(**{
        "Total Amendments": ("Quarter", "size"),
        "Majority": ("Majority", "sum"),
        "Minority": ("Minority", "sum"),
    })
    categories = pd.crosstab(df["Quarter"], df["Category"])
    for col in ("Bills Amended", "Resolutions Amended", "Amdts Amended", "Budget Resolutions"):
        summary[col] = categories[col] if col in categories else 0
    for col in ("UC", "VV", "RCV"):  # rows still marked INPUT BY HAND are in none of these
        summary[col] = (df["Action Type"] == col).groupby(df["Quarter"]).sum()
    return summary.T


# ---------------------------------------------------------------------------------------------
# Original Congress.gov search-page scraper (opens a visible Chrome window)
# ---------------------------------------------------------------------------------------------

def get_item_by_name(amendment, name):
    """Text of a labeled field ('Amends Bill:', 'Sponsor:', 'Latest Action:') in a search result."""
    for span in amendment.find_all("span", class_="result-item"):
        strong_tag = span.find("strong")
        if strong_tag and name in strong_tag.text:
            if name == "Latest Action:":  # want all the text, not just the link
                return span.text.strip().split("\n")[1].strip()
            return span.find("a").text.strip()
    return "N/A"


def scrape_amendments(start_date, end_date=None):
    """Same output as fetch_amendments, scraped from Congress.gov's search pages with Selenium."""
    from bs4 import BeautifulSoup
    from lxml import html

    sys.path.append(str(Path(__file__).resolve().parent.parent / "working_days"))
    import workingdays_helper

    dateend = datetime.strptime(end_date, "%m/%d/%Y").date() if end_date else datetime.now().date()
    datestart = datetime.strptime(start_date, "%m/%d/%Y").date()
    next_url = (f"/advanced-search/command-line?query=actionCode:(94000%20OR%2095000)%20"
                f"latestActionDateStr:[%22{datestart:%Y-%m-%d}%22%20TO%20%22{dateend:%Y-%m-%d}%22]"
                f"%20billType:%22SAmdt%22&searchResultViewType=compact&KWICView=false&pageSize=250&page=1")

    data_list = []
    while True:
        tree = workingdays_helper.scrape_w_selenium(f"https://www.congress.gov{next_url}")
        soup = BeautifulSoup(html.tostring(tree, pretty_print=True).decode(), "html.parser")
        amendments = soup.find_all("li", class_="expanded")
        if not amendments:
            break

        for amendment in amendments:
            try:
                heading = amendment.find("span", class_="amendment-heading")
                first_url = heading.find("a")["href"].strip()
                full_text = heading.get_text(strip=False)
                if "to" in full_text:  # an amendment to an amendment: "S.Amdt.X to S.Amdt.Y — ..."
                    amendment_number = full_text.split("—")[0].strip().replace("\n", "")
                else:
                    amendment_number = heading.find("a").text.strip()
                congress_info = heading.text.strip().split("—")[1].strip()
                data_list.append({
                    "Congress": congress_info or "N/A",
                    "S.Amdt.No": amendment_number or "N/A",
                    "Amends": get_item_by_name(amendment, "Amends Bill:") or "N/A",
                    "Sponsor": get_item_by_name(amendment, "Sponsor:") or "N/A",
                    "Latest Action": get_item_by_name(amendment, "Latest Action:") or "N/A",
                    "url": "congress.gov" + first_url if first_url else "N/A",
                })
            except Exception as e:
                print(f"Error processing amendment: {e}")

        next_button = soup.find("a", class_="next")
        if not next_button:
            break
        next_url = next_button["href"]

    df = pd.DataFrame(data_list)
    # "MM/DD/YY description" -> separate date and description
    df[["Latest Action Date", "Latest Action"]] = df["Latest Action"].str.extract(r"(\d{2}/\d{2}/\d{2}) (.+)")
    df = _add_classification(df)

    # "S.Amdt.X to S.Amdt.Y" -> S.Amdt.No "S.Amdt.X", Amends "S.Amdt.Y"
    for i, row in df.iterrows():
        if "to" in row["S.Amdt.No"]:
            df.loc[i, "Amends"] = row["S.Amdt.No"].split("to")[1].strip()
            df.loc[i, "S.Amdt.No"] = row["S.Amdt.No"].split("to")[0].strip()
    return df[COLUMNS]
