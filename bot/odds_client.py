import json
import logging
import os
import sqlite3
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger("odds_client")

ODDS_API_BASE = "https://api.the-odds-api.com/v4"
CACHE_DB = Path("odds_cache.db")
CACHE_TTL_SEC = 4 * 3600  # refetch every 4h → ~84 req/14 days for 3 sport keys

SHARP_BOOKS = {"pinnacle", "draftkings", "fanduel", "betmgm", "bovada"}


@dataclass
class OddsBook:
    name: str
    home_price: float
    away_price: float


@dataclass
class VegasEvent:
    event_id: str
    sport: str
    home_team: str
    away_team: str
    commence_time: str
    books: list[OddsBook] = field(default_factory=list)


class OddsClient:
    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ["ODDS_API_KEY"]
        self._db = self._init_db()

    def _init_db(self) -> sqlite3.Connection:
        db = sqlite3.connect(CACHE_DB)
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS odds_cache (
                cache_key TEXT PRIMARY KEY,
                fetched_at REAL,
                data_json TEXT
            )
            """
        )
        db.commit()
        return db

    def _cache_get(self, key: str, ttl: float = CACHE_TTL_SEC) -> list[dict] | None:
        row = self._db.execute(
            "SELECT fetched_at, data_json FROM odds_cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        fetched_at, data_json = row
        if time.time() - fetched_at > ttl:
            return None
        return json.loads(data_json)

    def _cache_set(self, key: str, data: list[dict]) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO odds_cache (cache_key, fetched_at, data_json) VALUES (?, ?, ?)",
            (key, time.time(), json.dumps(data)),
        )
        self._db.commit()

    def _get(self, path: str, params: dict) -> list[dict]:
        params["apiKey"] = self._api_key
        resp = requests.get(f"{ODDS_API_BASE}{path}", params=params, timeout=15)
        resp.raise_for_status()
        remaining = resp.headers.get("x-requests-remaining", "?")
        used = resp.headers.get("x-requests-used", "?")
        log.info("odds_api %s remaining=%s used=%s", path, remaining, used)
        return resp.json()

    # --- Discovery -------------------------------------------------------------

    def list_sports(self) -> list[dict]:
        """Return all sports available to this API key (including out-of-season)."""
        return self._get("/sports/", {"all": "true"})

    # --- World Cup outrights ---------------------------------------------------

    def get_world_cup_outrights(self, *, force_refresh: bool = False) -> dict[str, float]:
        """Returns {country_name_lower: vig_adjusted_fair_probability}.

        The vig adjustment normalizes each book's implied probs so they sum to 1,
        then we take the median across sharp books per team.
        """
        CACHE_KEY = "wc_outrights"
        if not force_refresh:
            cached = self._cache_get(CACHE_KEY)
            if cached is not None:
                return {item["name"]: item["prob"] for item in cached}

        # Try outrights endpoint first, fall back to odds endpoint (some sports use either)
        raw = None
        for path, params in [
            ("/sports/soccer_fifa_world_cup_winner/outrights/", {"regions": "us", "markets": "outrights", "oddsFormat": "decimal"}),
            ("/sports/soccer_fifa_world_cup_winner/odds/",      {"regions": "us", "markets": "outrights", "oddsFormat": "decimal"}),
        ]:
            try:
                raw = self._get(path, params)
                break
            except requests.HTTPError as e:
                log.warning("WC fetch %s failed: %s", path, e)

        if not raw:
            return {}

        # Collect per-team fair probs across sharp books
        team_probs: dict[str, list[float]] = {}
        for event in raw:
            for bm in event.get("bookmakers", []):
                if bm.get("key") not in SHARP_BOOKS:
                    continue
                for market in bm.get("markets", []):
                    if market.get("key") != "outrights":
                        continue
                    outcomes = [o for o in market.get("outcomes", []) if o.get("price", 0) > 1]
                    if not outcomes:
                        continue
                    total_implied = sum(1.0 / o["price"] for o in outcomes)
                    for o in outcomes:
                        fair = (1.0 / o["price"]) / total_implied
                        team_probs.setdefault(o["name"].lower(), []).append(fair)

        result = {name: statistics.median(probs) for name, probs in team_probs.items()}
        log.info("WC outrights loaded: %d teams", len(result))

        self._cache_set(CACHE_KEY, [{"name": k, "prob": v} for k, v in result.items()])
        return result

    # --- Premier League outrights ---------------------------------------------

    def get_epl_outrights(self, *, force_refresh: bool = False) -> dict[str, float]:
        """Returns {team_name_lower: vig_adjusted_fair_probability} for EPL winner."""
        CACHE_KEY = "epl_outrights"
        if not force_refresh:
            cached = self._cache_get(CACHE_KEY)
            if cached is not None:
                return {item["name"]: item["prob"] for item in cached}

        raw = None
        for path, params in [
            ("/sports/soccer_epl/outrights/",  {"regions": "us", "markets": "outrights", "oddsFormat": "decimal"}),
            ("/sports/soccer_epl/odds/",        {"regions": "us", "markets": "outrights", "oddsFormat": "decimal"}),
        ]:
            try:
                raw = self._get(path, params)
                break
            except requests.HTTPError as e:
                log.warning("EPL outrights fetch %s failed: %s", path, e)

        if not raw:
            return {}

        team_probs: dict[str, list[float]] = {}
        for event in raw:
            for bm in event.get("bookmakers", []):
                if bm.get("key") not in SHARP_BOOKS:
                    continue
                for market in bm.get("markets", []):
                    if market.get("key") != "outrights":
                        continue
                    outcomes = [o for o in market.get("outcomes", []) if o.get("price", 0) > 1]
                    if not outcomes:
                        continue
                    total_implied = sum(1.0 / o["price"] for o in outcomes)
                    for o in outcomes:
                        fair = (1.0 / o["price"]) / total_implied
                        team_probs.setdefault(o["name"].lower(), []).append(fair)

        import statistics
        result = {name: statistics.median(probs) for name, probs in team_probs.items()}
        log.info("EPL outrights loaded: %s", result)
        self._cache_set(CACHE_KEY, [{"name": k, "prob": v} for k, v in result.items()])
        return result

    # --- H2H game fair probabilities ------------------------------------------

    def get_game_probs(
        self, sport_key: str, *, force_refresh: bool = False, ttl: float = CACHE_TTL_SEC
    ) -> dict[tuple[str, str], dict[str, float]]:
        """Returns {(home_lower, away_lower): {team_lower: vig_adj_fair_prob}}.

        Soccer includes a 'draw' key. TTL defaults to 30 min — game lines move.
        """
        cache_key = f"gprobs_{sport_key}"
        if not force_refresh:
            cached = self._cache_get(cache_key, ttl=ttl)
            if cached is not None:
                return {(item["home"], item["away"]): item["probs"] for item in cached}

        try:
            raw = self._get(
                f"/sports/{sport_key}/odds/",
                {"regions": "us", "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso"},
            )
        except requests.HTTPError as e:
            log.warning("game_probs %s failed: %s", sport_key, e)
            return {}

        now_iso = datetime.now(timezone.utc).isoformat()
        result: dict[tuple[str, str], dict[str, float]] = {}
        for game in raw:
            if game.get("commence_time", "") < now_iso:
                continue
            home = game["home_team"].lower()
            away = game["away_team"].lower()
            team_raw: dict[str, list[float]] = {}
            for bm in game.get("bookmakers", []):
                if bm.get("key") not in SHARP_BOOKS:
                    continue
                for mkt in bm.get("markets", []):
                    if mkt.get("key") != "h2h":
                        continue
                    outcomes = [o for o in mkt.get("outcomes", []) if o.get("price", 0) > 1]
                    if not outcomes:
                        continue
                    total = sum(1.0 / o["price"] for o in outcomes)
                    for o in outcomes:
                        fair = (1.0 / o["price"]) / total
                        team_raw.setdefault(o["name"].lower(), []).append(fair)
            if team_raw:
                result[(home, away)] = {
                    name: statistics.median(vals) for name, vals in team_raw.items()
                }

        serializable = [{"home": h, "away": a, "probs": p} for (h, a), p in result.items()]
        self._cache_set(cache_key, serializable)
        log.info("game_probs %s loaded: %d games", sport_key, len(result))
        return result

    # --- H2H game events (NBA/MLB/etc, legacy) --------------------------------

    def get_events(self, sport: str, *, force_refresh: bool = False) -> list[VegasEvent]:
        if not force_refresh:
            cached = self._cache_get(sport)
            if cached is not None:
                return self._parse_events(sport, cached)
        raw = self._get(
            f"/sports/{sport}/odds/",
            {"regions": "us", "markets": "h2h", "oddsFormat": "decimal", "dateFormat": "iso"},
        )
        self._cache_set(sport, raw)
        return self._parse_events(sport, raw)

    @staticmethod
    def _parse_events(sport: str, raw: list[dict]) -> list[VegasEvent]:
        events: list[VegasEvent] = []
        now = datetime.now(timezone.utc).isoformat()
        for item in raw:
            commence = item.get("commence_time", "")
            if commence and commence < now:
                continue
            books: list[OddsBook] = []
            for bm in item.get("bookmakers", []):
                for market in bm.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    outcomes = market.get("outcomes", [])
                    if len(outcomes) < 2:
                        continue
                    prices = {o["name"]: o["price"] for o in outcomes}
                    home = item["home_team"]
                    away = item["away_team"]
                    if home not in prices:
                        continue
                    books.append(OddsBook(bm["key"], prices[home], prices.get(away, 0.0)))
            if not books:
                continue
            sharp = [b for b in books if b.name in SHARP_BOOKS]
            events.append(VegasEvent(item["id"], sport, item["home_team"], item["away_team"], commence, sharp or books))
        return events
