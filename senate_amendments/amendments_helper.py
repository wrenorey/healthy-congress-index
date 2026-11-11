"""Senate amendments considered, for the Healthy Congress Index.

An amendment is "considered" if it was agreed to or not agreed to on the Senate floor (by roll call,
voice vote, or unanimous consent). This is Library of Congress action code 94000 (Senate amendment
agreed to) or 95000 (not agreed to). Amendments are dated by their latest action.

Two ways to collect the data, which return the same columns:
- fetch_amendments(): the official Congress.gov API. Runs headless; needs a free API key (sign up at
  https://api.congress.gov/sign-up/) in the CONGRESS_API_KEY environment variable or in a file
  named .congress_api_key at the top of the repo.
- scrape_amendments(): the original congress.gov search-page scraper. Opens a visible Chrome window,
  because congress.gov blocks headless browsers.
"""
import json
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
CACHE_DIR = Path(__file__).resolve().parent / ".api_cache"
KEY_FILE = Path(__file__).resolve().parent.parent / ".congress_api_key"  # git-ignored
BILL_TYPES = {"HR": "H.R.", "S": "S.", "HRES": "H.Res.", "SRES": "S.Res.", "HJRES": "H.J.Res.",
              "SJRES": "S.J.Res.", "HCONRES": "H.Con.Res.", "SCONRES": "S.Con.Res."}


def _ordinal(n):
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _congress_of(day):
    """Congress in session on a date (a new Congress starts January 3 of odd years)."""
    year = day.year - 1 if (day.year % 2 == 1 and (day.month, day.day) < (1, 3)) else day.year
    return (year - 1789) // 2 + 1


class _Api:
    def __init__(self, api_key):
        self.api_key = api_key
        self.session = requests.Session()
        self.calls = 0
        self.last_start = 0.0
        self.min_interval = 3600 / (0.98 * DEFAULT_HOURLY_LIMIT)  # seconds between request starts

    def get(self, path, **params):
        params.update(api_key=self.api_key, format="json")
        for _ in range(10):
            time.sleep(max(0.0, self.last_start + self.min_interval - time.monotonic()))
            self.last_start = time.monotonic()
            response = self.session.get(f"{API}/{path}", params=params, timeout=60)
            self.calls += 1
            limit = response.headers.get("X-RateLimit-Limit", "")
            if limit.isdigit() and int(limit) > 0:  # pace to just under this key's hourly limit
                self.min_interval = 3600 / (0.98 * int(limit))
            if response.status_code == 429 or response.status_code >= 500:
                wait = int(response.headers.get("Retry-After", 60))
                print(f"  API returned {response.status_code}; waiting {wait}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response.json()
        response.raise_for_status()


def _list_amendments(api, congress, start):
    """Numbers and update dates of a Congress's Senate amendments updated on or after start.
    An amendment whose latest action is on or after start was updated on or after it, so this
    skips nothing we need. Records can move between pages while they are being updated, so the
    listing is repeated until it has as many distinct amendments as the API reports."""
    for _ in range(3):
        listing, offset = {}, 0
        while True:
            page = api.get(f"amendment/{congress}/samdt", limit=250, offset=offset,
                           fromDateTime=f"{start.isoformat()}T00:00:00Z")
            for item in page["amendments"]:
                listing[item["number"]] = item["updateDate"]
            offset += 250
            if offset >= page["pagination"]["count"]:
                break
        if len(listing) >= page["pagination"]["count"]:
            break
        print(f"  listing changed while paging ({len(listing)} of {page['pagination']['count']}); retrying")
    return listing


def _cached_amendment(api, congress, number, update_date, need_actions):
    """Detail (and, if asked, actions) for one amendment, re-fetched only when Congress.gov updated it."""
    path = CACHE_DIR / str(congress) / f"{number}.json"
    record = json.loads(path.read_text()) if path.exists() else {}
    if record.get("updateDate") != update_date:
        record = {"updateDate": update_date,
                  "detail": api.get(f"amendment/{congress}/samdt/{number}")["amendment"]}
    if need_actions and "actions" not in record:
        actions, offset = [], 0
        while True:
            page = api.get(f"amendment/{congress}/samdt/{number}/actions", limit=250, offset=offset)
            actions += page["actions"]
            offset += 250
            if offset >= page["pagination"]["count"]:
                break
        record["actions"] = actions
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return record


def _amends(detail, details_by_number):
    """What an amendment amends, in congress.gov's display format (e.g. 'H.R.9468',
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
    """'Sen. Durbin, Richard J. [D-IL]' -> 'Durbin, Richard J. [Sen.-D-IL]' (congress.gov's display)."""
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
    """Senate amendments considered with a latest action between start_date and end_date
    (MM/DD/YYYY, inclusive; end defaults to today), from the Congress.gov API.

    The first run for a Congress makes one request per Senate amendment (3,000-7,000 requests, or
    roughly 30-60 minutes); responses are cached in senate_amendments/.api_cache, so later runs only
    fetch what changed and take a minute or two.
    """
    api_key = api_key or os.environ.get("CONGRESS_API_KEY")
    if not api_key and KEY_FILE.exists():
        api_key = KEY_FILE.read_text().strip()
    if not api_key:
        raise RuntimeError(f"No Congress.gov API key: set CONGRESS_API_KEY or save the key in {KEY_FILE} "
                           "(free at https://api.congress.gov/sign-up/).")
    api = _Api(api_key)
    start = datetime.strptime(start_date, "%m/%d/%Y").date()
    end = datetime.strptime(end_date, "%m/%d/%Y").date() if end_date else date.today()

    rows = []
    for congress in range(_congress_of(start), _congress_of(end) + 1):
        listing = _list_amendments(api, congress, start)
        print(f"{_ordinal(congress)} Congress: checking {len(listing)} Senate amendments")

        details, considered = {}, []
        for i, (number, update_date) in enumerate(listing.items(), 1):
            detail = _cached_amendment(api, congress, number, update_date, need_actions=False)["detail"]
            details[detail["number"]] = detail
            action_date = (detail.get("latestAction") or {}).get("actionDate")
            # Only amendments proposed on the floor can be agreed to or not agreed to, so only those
            # need their action history checked for the 94000/95000 codes. (Most amendments are
            # submitted but never proposed.)
            if (detail.get("proposedDate") and action_date
                    and start <= date.fromisoformat(action_date) <= end):
                record = _cached_amendment(api, congress, number, update_date, need_actions=True)
                if any(a.get("actionCode") in CONSIDERED_CODES for a in record["actions"]):
                    considered.append(detail)
            if i % 250 == 0:
                print(f"  {i}/{len(listing)} checked, {len(considered)} considered so far ({api.calls} requests)")

        for detail in considered:
            number = (detail.get("amendedAmendment") or {}).get("number")
            if number and number not in details:  # parent amendment not updated since start date
                details[number] = api.get(f"amendment/{congress}/samdt/{number}")["amendment"]
            rows.append(amendment_row(detail, details))

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


def quarterly_summary(df, majority_party, independents_caucus_with="D"):
    """Per-quarter counts (not cumulative) by latest action date, matching the rows of the
    'Senate Amendments Considered' sheet. majority_party is 'D' or 'R' for the Senate in question."""
    df = df.copy()
    when = pd.to_datetime(df["Latest Action Date"], format="%m/%d/%y")
    df["Quarter"] = when.dt.year.astype(str) + " Q" + when.dt.quarter.astype(str)
    party = df["Sponsor"].str.extract(r"\[Sen\.-([RDI])", expand=False)
    caucus = party.replace("I", independents_caucus_with)
    df["Majority"] = caucus == majority_party
    df["Minority"] = caucus.notna() & (caucus != majority_party)
    df["Category"] = df["Amends"].map(amends_category)
    summary = df.groupby("Quarter").agg(**{
        "Total Amendments": ("Quarter", "size"),
        "Majority": ("Majority", "sum"),
        "Minority": ("Minority", "sum"),
    })
    categories = pd.crosstab(df["Quarter"], df["Category"])
    for col in ("Bills Amended", "Resolutions Amended", "Amdts Amended", "Budget Resolutions"):
        summary[col] = categories[col] if col in categories else 0
    for col in ("UC", "VV", "RCV"):
        summary[col] = (df["Action Type"] == col).groupby(df["Quarter"]).sum()
    return summary.T


# ---------------------------------------------------------------------------------------------
# Original congress.gov search-page scraper (opens a visible Chrome window)
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
    """Same output as fetch_amendments, scraped from congress.gov's search pages with Selenium."""
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
