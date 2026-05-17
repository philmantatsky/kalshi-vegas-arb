"""
Fetches live EPL standings from ESPN's public API (no key required)
and computes vig-free title-winner probabilities for the remaining
contenders.

Used as a substitute Vegas signal for the 4 Kalshi EPL winner markets
that resolve before May 31.
"""
import json
import logging
import sqlite3
import time
from pathlib import Path

import requests

log = logging.getLogger("epl_client")

ESPN_STANDINGS_URL = "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings"
CACHE_DB = Path("odds_cache.db")
CACHE_KEY = "epl_standings"
CACHE_TTL_SEC = 3600  # refresh every hour — season is ending


def _get_db() -> sqlite3.Connection:
    db = sqlite3.connect(CACHE_DB)
    db.execute(
        "CREATE TABLE IF NOT EXISTS odds_cache (cache_key TEXT PRIMARY KEY, fetched_at REAL, data_json TEXT)"
    )
    db.commit()
    return db


def _cache_get(key: str) -> dict | None:
    db = _get_db()
    row = db.execute(
        "SELECT fetched_at, data_json FROM odds_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    if not row:
        return None
    fetched_at, data_json = row
    if time.time() - fetched_at > CACHE_TTL_SEC:
        return None
    return json.loads(data_json)


def _cache_set(key: str, data: dict) -> None:
    db = _get_db()
    db.execute(
        "INSERT OR REPLACE INTO odds_cache (cache_key, fetched_at, data_json) VALUES (?, ?, ?)",
        (key, time.time(), json.dumps(data)),
    )
    db.commit()


def _parse_entries(obj: dict | list) -> list[dict]:
    """Walk an ESPN response object and collect standing entries wherever they live."""
    results = []
    if isinstance(obj, list):
        for item in obj:
            results.extend(_parse_entries(item))
        return results
    if not isinstance(obj, dict):
        return results
    # If this object has entries with team+stats, it's what we want
    entries = obj.get("entries", [])
    for entry in entries:
        team_name = entry.get("team", {}).get("displayName", "")
        if not team_name:
            continue
        stats = {s["name"]: s["value"] for s in entry.get("stats", []) if "name" in s and "value" in s}
        results.append({
            "team": team_name.lower(),
            "points": int(float(stats.get("points", stats.get("pts", 0)))),
            "played": int(float(stats.get("gamesPlayed", stats.get("played", 0)))),
            "gd": int(float(stats.get("pointDifferential", stats.get("goalDifference", stats.get("gd", 0))))),
        })
    # Recurse into nested containers
    for key in ("groups", "children", "standings", "leagues", "seasons"):
        if key in obj:
            results.extend(_parse_entries(obj[key]))
    return results


def _fetch_standings() -> list[dict]:
    resp = requests.get(ESPN_STANDINGS_URL, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    log.info("ESPN top-level keys: %s", list(data.keys()))
    entries = _parse_entries(data)
    # Deduplicate by team name, keep highest points entry
    seen: dict[str, dict] = {}
    for e in entries:
        if e["team"] not in seen or e["points"] > seen[e["team"]]["points"]:
            seen[e["team"]] = e
    return list(seen.values())


def get_epl_title_probs(*, force_refresh: bool = False) -> dict[str, float]:
    """
    Returns {team_name_lower: probability_of_winning_title}.

    Uses current standings to compute who can still mathematically win.
    On the final day (38 games), whichever team finishes first wins.

    Simple model:
      - Teams that cannot mathematically catch the leader get prob ~0
      - Remaining contenders get probability proportional to current points
        (leader gets higher weight)
    """
    if not force_refresh:
        cached = _cache_get(CACHE_KEY)
        if cached:
            log.info("EPL standings from cache: %s", {k: f"{v:.3f}" for k, v in cached.items()})
            return cached

    try:
        standings = _fetch_standings()
        log.info("EPL standings fetched: %d teams", len(standings))
    except Exception as e:
        log.warning("EPL standings fetch failed: %s", e)
        return {}

    if not standings:
        return {}

    # Sort by points desc, then goal difference desc
    standings.sort(key=lambda x: (x["points"], x["gd"]), reverse=True)

    total_games = 38
    leader_pts = standings[0]["points"]

    contenders: list[dict] = []
    for team in standings:
        games_left = total_games - team["played"]
        max_pts = team["points"] + games_left * 3
        if max_pts >= leader_pts:
            contenders.append(team)

    if not contenders:
        contenders = standings[:1]

    log.info("EPL title contenders: %s", [(t["team"], t["points"]) for t in contenders])

    if len(contenders) == 1:
        # Already decided
        result = {contenders[0]["team"]: 0.97}
        for t in standings[1:]:
            result[t["team"]] = 0.01
        _cache_set(CACHE_KEY, result)
        return result

    # Weighted by points advantage — leader gets more weight
    # Simple logistic-style: exp(points / scale)
    import math
    scale = max(3.0, leader_pts * 0.05)
    weights = {t["team"]: math.exp(t["points"] / scale) for t in contenders}
    total_w = sum(weights.values())
    result = {name: w / total_w for name, w in weights.items()}

    # Non-contenders get near-zero
    for t in standings:
        if t["team"] not in result:
            result[t["team"]] = 0.005

    log.info("EPL title probs: %s", {k: f"{v:.3f}" for k, v in result.items() if v > 0.01})
    _cache_set(CACHE_KEY, result)
    return result
