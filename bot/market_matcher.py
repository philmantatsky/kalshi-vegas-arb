"""Maps Kalshi market_ids to Vegas odds data.

Supported formats:
  KXMENWORLDCUP-26-AR          → WC outright winner for country
  KXPREMIERLEAGUE-26-ARS       → EPL title winner
  KXNBAGAME-26MAY18CLEDET-CLE  → NBA game, YES = Cleveland wins
  KXMLBGAME-26MAY18NYYNYK-NYY  → MLB game, YES = Yankees win
  KXNHLGAME-26MAY18FLATOR-FLA  → NHL game, YES = Florida wins
  KXEPLGAME-26MAY18ARSBUR-ARS  → EPL match result, YES = Arsenal wins
  KXEPLGAME-26MAY18ARSBUR-TIE  → EPL match result, YES = Draw
"""
import re



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
    "EPL": "soccer_epl",
    "UCL": "soccer_uefa_champs_league",
    "MLS": "soccer_usa_mls",
}

MONTH_MAP: dict[str, int] = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

NBA_ABBREV: dict[str, str] = {
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

MLB_ABBREV: dict[str, str] = {
    "ARI": "arizona diamondbacks", "ATL": "atlanta braves", "BAL": "baltimore orioles",
    "BOS": "boston red sox", "CHC": "chicago cubs", "CWS": "chicago white sox",
    "CIN": "cincinnati reds", "CLE": "cleveland guardians", "COL": "colorado rockies",
    "DET": "detroit tigers", "HOU": "houston astros", "KCR": "kansas city royals",
    "LAA": "los angeles angels", "LAD": "los angeles dodgers", "MIA": "miami marlins",
    "MIL": "milwaukee brewers", "MIN": "minnesota twins", "NYM": "new york mets",
    "NYY": "new york yankees", "OAK": "athletics", "PHI": "philadelphia phillies",
    "PIT": "pittsburgh pirates", "SDP": "san diego padres", "SFG": "san francisco giants",
    "SEA": "seattle mariners", "STL": "st. louis cardinals", "TBR": "tampa bay rays",
    "TEX": "texas rangers", "TOR": "toronto blue jays", "WSN": "washington nationals",
}

NHL_ABBREV: dict[str, str] = {
    "ANA": "anaheim ducks", "BOS": "boston bruins", "BUF": "buffalo sabres",
    "CGY": "calgary flames", "CAR": "carolina hurricanes", "CHI": "chicago blackhawks",
    "COL": "colorado avalanche", "CBJ": "columbus blue jackets", "DAL": "dallas stars",
    "DET": "detroit red wings", "EDM": "edmonton oilers", "FLA": "florida panthers",
    "LAK": "los angeles kings", "MIN": "minnesota wild", "MTL": "montreal canadiens",
    "NSH": "nashville predators", "NJD": "new jersey devils", "NYI": "new york islanders",
    "NYR": "new york rangers", "OTT": "ottawa senators", "PHI": "philadelphia flyers",
    "PIT": "pittsburgh penguins", "STL": "st. louis blues", "SJS": "san jose sharks",
    "SEA": "seattle kraken", "TBL": "tampa bay lightning", "TOR": "toronto maple leafs",
    "VAN": "vancouver canucks", "VGK": "vegas golden knights", "WSH": "washington capitals",
    "WPG": "winnipeg jets", "UTA": "utah hockey club",
}

EPL_GAME_ABBREV: dict[str, str] = {
    **EPL_ABBREV,
    "BUR": "burnley", "LEE": "leeds", "NOR": "norwich", "SWA": "swansea",
    "MID": "middlesbrough", "SHU": "sheffield united", "WBA": "west bromwich",
    "LUT": "luton", "SHW": "sheffield wednesday", "PNE": "preston",
    "SUN": "sunderland", "BLB": "blackburn",
}

SPORT_ABBREV: dict[str, dict[str, str]] = {
    "basketball_nba": NBA_ABBREV,
    "baseball_mlb": MLB_ABBREV,
    "icehockey_nhl": NHL_ABBREV,
    "soccer_epl": EPL_GAME_ABBREV,
}

# Matches: KXNBAGAME-26MAY18CLEDET-CLE  or  KXEPLGAME-26MAY18ARSBUR-TIE
_GAME_RE = re.compile(
    r"^(?:kalshi:)?KX(?P<sport>[A-Z]+)GAME-(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<dd>\d{2})"
    r"(?P<game_teams>[A-Z]+)-(?P<yes_team>[A-Z]+)$",
    re.IGNORECASE,
)


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _abbrev_to_full(abbrev: str, sport_key: str) -> str | None:
    abbrev_dict = SPORT_ABBREV.get(sport_key, {})
    canonical = abbrev_dict.get(abbrev.upper())
    if canonical:
        return canonical
    # Fallback: try across all dicts
    for d in SPORT_ABBREV.values():
        if abbrev.upper() in d:
            return d[abbrev.upper()]
    return None


def _team_matches(full_name_lower: str, candidate: str) -> bool:
    """True if candidate (full team name, lowercased) matches full_name_lower."""
    fn = _normalize(full_name_lower)
    cn = _normalize(candidate)
    if fn == cn:
        return True
    # last-word match (e.g. "cavaliers" in "cleveland cavaliers")
    last = fn.split()[-1] if fn.split() else fn
    return last in cn or cn in fn


def match_game_market(
    market_id: str,
    all_game_probs: dict[str, dict[tuple[str, str], dict[str, float]]],
) -> float | None:
    """Return vig-adjusted fair probability for the YES outcome of a game market.

    all_game_probs: {sport_key: {(home_lower, away_lower): {team_lower: prob}}}
    """
    m = _GAME_RE.match(market_id)
    if not m:
        return None

    sport_key = SPORT_KEY_MAP.get(m.group("sport").upper())
    if not sport_key:
        return None

    mon = MONTH_MAP.get(m.group("mon").upper())
    if not mon:
        return None

    yes_abbrev = m.group("yes_team").upper()

    # Handle soccer draw
    is_draw = yes_abbrev == "TIE"

    game_probs = all_game_probs.get(sport_key, {})

    # Find the right game by matching BOTH teams in the ticker against known games
    game_team_str = m.group("game_teams").upper()
    # Split 6-char combined code into two 3-char abbrevs
    if len(game_team_str) == 6:
        ticker_teams = [game_team_str[:3], game_team_str[3:]]
    else:
        ticker_teams = [game_team_str[i:i+3] for i in range(0, len(game_team_str), 3)]

    ticker_full = [_abbrev_to_full(a, sport_key) for a in ticker_teams]

    for (home_lower, away_lower), probs in game_probs.items():
        # Verify this game's date is close to the ticker date
        # (game_probs is already filtered to upcoming games, so just match teams)

        # Check both ticker teams appear in this game
        home_match = any(
            t and _team_matches(t, home_lower) for t in ticker_full
        )
        away_match = any(
            t and _team_matches(t, away_lower) for t in ticker_full
        )
        if not (home_match and away_match):
            continue

        if is_draw:
            return probs.get("draw")

        # Identify which team is YES
        yes_full = _abbrev_to_full(yes_abbrev, sport_key)
        if yes_full is None:
            return None
        for team_name, prob in probs.items():
            if _team_matches(yes_full, team_name):
                return prob

    return None
