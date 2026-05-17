import hashlib
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CUTOFF = datetime(2026, 5, 31, 23, 59, tzinfo=timezone.utc)

from dotenv import load_dotenv

load_dotenv()

from ai_prophet_core import ServerAPIClient  # noqa: E402
from ai_prophet_core.arena import BenchmarkSession  # noqa: E402
from bot.odds_client import OddsClient  # noqa: E402
from bot.strategy import decide_trades  # noqa: E402
from bot.epl_client import get_epl_title_probs  # noqa: E402

# --- Logging ---
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

_fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%SZ")
_root = logging.getLogger()
_root.setLevel(logging.INFO)

_stdout = logging.StreamHandler(sys.stdout)
_stdout.setFormatter(_fmt)
_root.addHandler(_stdout)

_file = logging.FileHandler(LOG_DIR / "bot.log")
_file.setFormatter(_fmt)
_root.addHandler(_file)

log = logging.getLogger("bot")

# --- Config ---
CONFIG: dict[str, Any] = {"strategy": "kalshi-vegas-arb", "version": "1.0"}
CONFIG_HASH = hashlib.sha256(json.dumps(CONFIG, sort_keys=True).encode()).hexdigest()[:16]
EXPERIMENT_SLUG = os.environ.get("EXPERIMENT_SLUG", "kalshi-vegas-arb-v1")
N_TICKS = 96 * 14  # 14 days of 15-min ticks

# Refresh Vegas odds every N ticks (16 ticks = 4 hours)
ODDS_REFRESH_TICKS = 16


def main() -> None:
    api = ServerAPIClient(
        base_url=os.environ["PA_SERVER_URL"],
        api_key=os.environ["PA_SERVER_API_KEY"],
        timeout=30,
    )
    odds = OddsClient()

    with BenchmarkSession(api) as session:
        session.create_experiment(
            slug=EXPERIMENT_SLUG,
            config_hash=CONFIG_HASH,
            config_json=CONFIG,
            n_ticks=N_TICKS,
        )
        part = session.upsert_participant(
            model="custom:kalshi-vegas-arb",
            starting_cash=10_000,
        )
        log.info("Participant idx=%s", part.participant_idx)

        wc_odds = odds.get_world_cup_outrights()
        log.info("WC outrights loaded: %d teams", len(wc_odds))
        epl_odds = odds.get_epl_outrights()
        log.info("EPL outrights loaded: %d teams", len(epl_odds))
        epl_title_probs = get_epl_title_probs()
        log.info("EPL title probs (standings-based): %d teams", len(epl_title_probs))

        tick_count = 0
        while True:
            lease = session.claim_tick()

            if not lease.available:
                reason = getattr(lease, "reason", None)
                if reason == "experiment_completed":
                    log.info("Experiment completed after %d ticks", tick_count)
                    break
                wait = lease.retry_after_sec or 15
                log.info("No tick available reason=%s sleeping=%ds", reason, wait)
                time.sleep(wait)
                continue

            tick = session.load_candidates(lease)
            lease = tick.lease
            tick_count += 1

            candidates = tick.candidates
            markets = candidates.markets if candidates else []
            portfolio = session.get_portfolio(part.participant_idx)
            cash = portfolio.cash if portfolio else "?"
            n_pos = len(portfolio.positions) if portfolio else 0

            log.info(
                "tick=%d id=%s markets=%d cash=%s positions=%d",
                tick_count, lease.tick_id, len(markets), cash, n_pos,
            )

            # On first tick, show which markets resolve before May 31
            if tick_count == 1:
                def to_utc(dt: datetime) -> datetime:
                    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
                early = [m for m in markets if to_utc(m.resolution_time) <= CUTOFF]
                by_topic: dict[str, list[str]] = {}
                for m in early:
                    t = m.topic or m.family or "unknown"
                    by_topic.setdefault(t, []).append(m.market_id)
                log.info("Markets resolving before May 31: %d / %d", len(early), len(markets))
                for topic, ids in sorted(by_topic.items(), key=lambda x: -len(x[1])):
                    log.info("  %-30s %d markets  e.g. %s", topic, len(ids), ids[0])

            # Periodic odds refresh
            if tick_count % ODDS_REFRESH_TICKS == 1:
                wc_odds = odds.get_world_cup_outrights()
                log.info("WC odds refreshed: %d teams", len(wc_odds))

            # Refresh EPL standings every 2h (season is ending — prices move fast)
            if tick_count % 8 == 1:
                epl_title_probs = get_epl_title_probs(force_refresh=(tick_count > 1))
                log.info("EPL title probs refreshed: %d teams", len(epl_title_probs))

            # Decide trades
            intents = decide_trades(candidates, portfolio, wc_odds, epl_odds, epl_title_probs) if (candidates and portfolio) else []

            plan: dict[str, Any] = {
                "reasoning": "kalshi-vegas-arb",
                "wc_teams_loaded": len(wc_odds),
                "intents": len(intents),
            }
            session.put_plan(lease, part.participant_idx, plan)

            result = None
            if intents:
                result = session.submit_intents(lease, part.participant_idx, intents)

            session.finalize(lease, part.participant_idx)
            session.complete_tick(lease)

            if result:
                log.info(
                    "  submitted=%d accepted=%d rejected=%d",
                    len(intents), result.accepted, result.rejected,
                )
                for r in result.rejections:
                    log.warning("  REJECTED %s", r)
            else:
                log.info("  no trades submitted")


if __name__ == "__main__":
    main()
