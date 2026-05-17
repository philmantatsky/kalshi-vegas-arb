"""Maps Kalshi market_ids to Vegas odds data.

Supported formats:
  KXMENWORLDCUP-26-AR  → WC outright winner for country
  KXNBAGAME-26FEB22ORLLAC → NBA H2H game (future use)
"""
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from bot.odds_client import VegasEvent

# --- World Cup country code mapping ------------------------------------------
# ISO 3166-1 alpha-2 → lowercase name as it appears in The Odds API

WC_COUNTRY_CODES: dict[str, str] = {
    "AR": "argentina",
    "AU": "australia",
    "BE": "belgium",
    "BR": "brazil",
    "CA": "canada",
    "CL": "chile",
    "CN": "china pr",
    "CO": "colombia",
    "CR": "costa rica",
    "DE": "germany",
    "DK": "denmark",
    "EC": "ecuador",
    "EG": "egypt",
    "ES": "spain",
    "FR": "france",
    "GB": "england",
    "GH": "ghana",
    "HR": "croatia",
    "HU": "hungary",
    "IR": "iran",
    "IT": "italy",
    "JP": "japan",
    "KR": "south korea",
    "MA": "morocco",
    "MX": "mexico",
    "NG": "nigeria",
    "NL": "netherlands",
    "NO": "norway",
    "PE": "peru",
    "PL": "poland",
    "PT": "portugal",
    "RO": "romania",
    "RS": "serbia",
    "SA": "saudi arabia",
    "SE": "sweden",
    "SN": "senegal",
    "TR": "turkey",
    "UA": "ukraine",
    "US": "united states",
    "UY": "uruguay",
    "VE": "venezuela",
    "ZA": "south africa",
    "NZ": "new zealand",
    "PY": "paraguay",
    "BO": "bolivia",
    "PA": "panama",
    "SV": "el salvador",
    "HN": "honduras",
    "JM": "jamaica",
}

_WC_RE = re.compile(r"^(?:kalshi:)?KXMENWORLDCUP-\d+-(?P<cc>[A-Z]{2,3})$", re.IGNORECASE)


def match_world_cup(market_id: str, wc_odds: dict[str, float]) -> float | None:
    """Return Vegas vig-adjusted probability that the YES outcome wins, or None."""
    m = _WC_RE.match(market_id)
    if not m:
        return None
    cc = m.group("cc").upper()
    country = WC_COUNTRY_CODES.get(cc)
    if country is None:
        return None

    # Exact match
    prob = wc_odds.get(country)
    if prob is not None:
        return prob

    # Fuzzy: any Vegas team name that contains our country or vice versa
    for name, p in wc_odds.items():
        if country in name or name in country:
            return p

    return None


# --- Premier League matching --------------------------------------------------

EPL_ABBREV: dict[str, str] = {
    "ARS": "arsenal",
    "AVL": "aston villa",
    "BOU": "bournemouth",
    "BRE": "brentford",
    "BHA": "brighton",
    "CHE": "chelsea",
    "CRY": "crystal palace",
    "EVE": "everton",
    "FUL": "fulham",
    "IPS": "ipswich",
    "LEI": "leicester",
    "LIV": "liverpool",
    "MCI": "manchester city",
    "MUN": "manchester united",
    "NEW": "newcastle",
    "NFO": "nottingham forest",
    "SOU": "southampton",
    "TOT": "tottenham",
    "WHU": "west ham",
    "WOL": "wolves",
}

_EPL_RE = re.compile(r"^(?:kalshi:)?KXPREMIERLEAGUE-\d+-(?P<abbrev>[A-Z]+)$", re.IGNORECASE)


def match_epl(market_id: str, epl_odds: dict[str, float]) -> float | None:
    """Return Vegas vig-adjusted probability that this team wins the EPL, or None."""
    m = _EPL_RE.match(market_id)
    if not m:
        return None
    abbrev = m.group("abbrev").upper()
    team = EPL_ABBREV.get(abbrev)
    if team is None:
        return None
    prob = epl_odds.get(team)
    if prob is not None:
        return prob
    # Fuzzy fallback
    for name, p in epl_odds.items():
        if team in name or name in team:
            return p
    return None


# --- H2H game matching (NBA/MLB/etc) -----------------------------------------

SPORT_KEY_MAP: dict[str, str] = {
    "NBA": "basketball_nba",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
    "NFL": "americanfootball_nfl",
}

MONTH_MAP: dict[str, int] = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

ABBREV_TO_NAME: dict[str, str] = {
    "ATL": "atlanta hawks", "BOS": "boston celtics", "BKN": "brooklyn nets",
    "CHA": "charlotte hornets", "CHI": "chicago bulls", "CLE": "cleveland cavaliers",
    "DAL": "dallas mavericks", "DEN": "denver nuggets", "DET": "detroit pistons",
    "GSW": "golden state warriors", "HOU": "houston rockets", "IND": "indiana pacers",
    "LAC": "los angeles clippers", "LAL": "los angeles lakers", "MEM": "memphis grizzlies",
    "MIA": "miami heat", "MIL": "milwaukee bucks", "MIN": "minnesota timberwolves",
    "NOP": "new orleans pelicans", "NYK": "new york knicks", "OKC": "oklahoma city thunder",
    "ORL": "orlando magic", "PHI": "philadelphia 76ers", "PHX": "phoenix suns",
    "POR": "portland trail blazers", "SAC": "sacramento kings", "SAS": "san antonio spurs",
    "TOR": "toronto raptors", "UTA": "utah jazz", "WAS": "washington wizards",
}

_GAME_RE = re.compile(
    r"^(?:kalshi:)?KX(?P<sport>[A-Z]+)GAME-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})(?P<teams>[A-Z]+)$",
    re.IGNORECASE,
)


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()


def _abbrev_matches(abbrev: str, full_name: str) -> bool:
    canonical = ABBREV_TO_NAME.get(abbrev.upper())
    if not canonical:
        return False
    norm = _normalize(full_name)
    words = canonical.split()
    return canonical in norm or bool(words and words[-1] in norm)


def match_game(market_id: str, events: list[VegasEvent]) -> tuple[VegasEvent, bool] | None:
    """Returns (event, is_home_team_yes) or None. is_home_team_yes=True if YES = home wins."""
    m = _GAME_RE.match(market_id)
    if not m:
        return None
    sport = SPORT_KEY_MAP.get(m.group("sport").upper())
    if not sport:
        return None
    mon = MONTH_MAP.get(m.group("mon").upper())
    if not mon:
        return None
    game_date = date(2000 + int(m.group("yy")), mon, int(m.group("dd")))
    teams = [m.group("teams")[i:i+3] for i in range(0, len(m.group("teams")), 3)]
    if len(teams) < 2:
        return None

    for event in events:
        if event.sport != sport:
            continue
        try:
            ev_date = datetime.fromisoformat(
                event.commence_time.replace("Z", "+00:00")
            ).astimezone(timezone.utc).date()
        except ValueError:
            continue
        if ev_date != game_date:
            continue
        home_ok = any(_abbrev_matches(a, event.home_team) for a in teams)
        away_ok = any(_abbrev_matches(a, event.away_team) for a in teams)
        if home_ok and away_ok:
            # Determine which team is the YES outcome (first team in ticker)
            is_home_yes = _abbrev_matches(teams[-1], event.home_team)
            return event, is_home_yes
    return None
