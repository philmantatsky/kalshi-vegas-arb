"""Main decision function: given a tick + portfolio + Vegas odds, return trade intents."""
import logging
from datetime import datetime, timezone

from ai_prophet_core import TradeIntentRequest
from ai_prophet_core.client_models import CandidatesResponse, PortfolioResponse

from bot.market_matcher import match_world_cup, match_epl, match_game_market
from bot.edge import is_liquid, yes_edge, no_edge, MIN_EDGE, MIN_MINUTES
from bot.sizing import kelly_dollars, apply_caps, to_shares

log = logging.getLogger("strategy")

MAX_INTENTS_PER_TICK = 20
MAX_OPEN_POSITIONS = 28  # server limit is 30; leave 2 slots buffer
MIN_DOLLARS = 2.0  # don't bother submitting tiny orders


def decide_trades(
    candidates: CandidatesResponse,
    portfolio: PortfolioResponse,
    wc_odds: dict[str, float],
    epl_odds: dict[str, float] | None = None,
    epl_title_probs: dict[str, float] | None = None,
    game_probs: dict | None = None,
) -> list[TradeIntentRequest]:
    now = datetime.now(timezone.utc)
    cash = float(portfolio.cash)

    # Build exposure map from current positions
    market_usd: dict[str, float] = {}
    gross_usd = 0.0
    held: dict[str, str] = {}  # market_id → side held ("YES" or "NO")
    held_shares: dict[str, float] = {}
    for pos in portfolio.positions:
        price = float(pos.current_price) if pos.current_price else 0.0
        notional = float(pos.shares) * price
        market_usd[pos.market_id] = market_usd.get(pos.market_id, 0.0) + notional
        gross_usd += notional
        held[pos.market_id] = pos.side
        held_shares[pos.market_id] = float(pos.shares)

    bankroll = cash + gross_usd
    intents: list[TradeIntentRequest] = []

    # --- Exit pass: sell positions that have converged ---
    for pos in portfolio.positions:
        if len(intents) >= MAX_INTENTS_PER_TICK:
            break
        mid = pos.market_id
        vegas_prob = match_epl(mid, epl_odds or {})
        if vegas_prob is None:
            vegas_prob = match_epl(mid, epl_title_probs or {})
        if vegas_prob is None:
            vegas_prob = match_world_cup(mid, wc_odds)
        if vegas_prob is None and game_probs:
            vegas_prob = match_game_market(mid, game_probs)
        if vegas_prob is None:
            continue

        bid = float(pos.current_price) if pos.current_price else 0.0
        if bid <= 0:
            continue

        should_exit = False
        if pos.side == "YES":
            # Exit YES when YES price has risen to/past fair value
            remaining_edge = yes_edge(bid, vegas_prob)
            should_exit = remaining_edge < 0.005  # less than 0.5% edge left
        else:
            # Exit NO when YES price has fallen to/past fair value
            # NO current price ≈ 1 - YES bid; remaining edge on NO side
            no_bid = float(pos.current_price) if pos.current_price else 0.0
            remaining_edge = no_edge(1.0 - no_bid, vegas_prob)
            should_exit = remaining_edge < 0.005

        if should_exit:
            log.info("EXIT %s %s shares=%.2f", mid, pos.side, float(pos.shares))
            intents.append(TradeIntentRequest(
                market_id=mid,
                action="SELL",
                side=pos.side,
                shares=f"{float(pos.shares):.4f}",
                idempotency_key="",
            ))

    open_positions = len(portfolio.positions)

    # --- Entry pass: find new edges ---
    for m in candidates.markets:
        if len(intents) >= MAX_INTENTS_PER_TICK:
            break

        # Server hard-caps at 30 open positions
        if open_positions >= MAX_OPEN_POSITIONS:
            break

        # Skip if already holding this market (avoid adding to a position mid-convergence)
        if m.market_id in held:
            continue

        # Skip markets resolving too soon
        res_time = m.resolution_time
        if res_time.tzinfo is None:
            res_time = res_time.replace(tzinfo=timezone.utc)
        minutes_left = (res_time - now).total_seconds() / 60
        if minutes_left < MIN_MINUTES:
            continue

        yes_ask = float(m.quote.best_ask)
        yes_bid = float(m.quote.best_bid)

        if not is_liquid(yes_bid, yes_ask):
            continue

        # Priority: EPL title (ESPN/Odds API) → WC outrights → game markets
        vegas_prob = match_epl(m.market_id, epl_odds or {})
        if vegas_prob is None and epl_title_probs:
            vegas_prob = match_epl(m.market_id, epl_title_probs)
        if vegas_prob is None:
            vegas_prob = match_world_cup(m.market_id, wc_odds)
        if vegas_prob is None and game_probs:
            vegas_prob = match_game_market(m.market_id, game_probs)
        if vegas_prob is None:
            continue

        log.info(
            "  EDGE %s vegas=%.3f yes_ask=%.3f yes_edge=%.3f no_edge=%.3f",
            m.market_id, vegas_prob, yes_ask,
            yes_edge(yes_ask, vegas_prob), no_edge(yes_bid, vegas_prob),
        )

        cur_market_usd = market_usd.get(m.market_id, 0.0)

        y_edge = yes_edge(yes_ask, vegas_prob)
        n_edge = no_edge(yes_bid, vegas_prob)

        if y_edge >= n_edge and y_edge >= MIN_EDGE:
            target = kelly_dollars(y_edge, yes_ask, bankroll)
            capped = apply_caps(target, current_market_usd=cur_market_usd, current_gross_usd=gross_usd)
            if capped >= MIN_DOLLARS and capped <= cash:
                log.info(
                    "BUY YES %s | vegas=%.3f kalshi_ask=%.3f edge=%.3f shares=%s",
                    m.market_id, vegas_prob, yes_ask, y_edge, to_shares(capped, yes_ask),
                )
                intents.append(TradeIntentRequest(
                    market_id=m.market_id,
                    action="BUY",
                    side="YES",
                    shares=to_shares(capped, yes_ask),
                    idempotency_key="",
                ))
                gross_usd += capped
                market_usd[m.market_id] = cur_market_usd + capped
                cash -= capped
                open_positions += 1

        elif n_edge >= MIN_EDGE:
            no_ask = 1.0 - yes_bid
            target = kelly_dollars(n_edge, no_ask, bankroll)
            capped = apply_caps(target, current_market_usd=cur_market_usd, current_gross_usd=gross_usd)
            if capped >= MIN_DOLLARS and capped <= cash:
                log.info(
                    "BUY NO  %s | vegas=%.3f no_ask=%.3f edge=%.3f shares=%s",
                    m.market_id, vegas_prob, no_ask, n_edge, to_shares(capped, no_ask),
                )
                intents.append(TradeIntentRequest(
                    market_id=m.market_id,
                    action="BUY",
                    side="NO",
                    shares=to_shares(capped, no_ask),
                    idempotency_key="",
                ))
                gross_usd += capped
                market_usd[m.market_id] = cur_market_usd + capped
                cash -= capped
                open_positions += 1

    return intents
