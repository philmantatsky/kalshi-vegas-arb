MIN_EDGE = 0.03       # 3 percentage points — skip anything smaller
MAX_SPREAD = 0.08     # skip illiquid markets with wide bid-ask spreads
MIN_MINUTES = 60      # skip markets resolving within 60 minutes


def is_liquid(best_bid: float, best_ask: float) -> bool:
    return 0 < best_bid < best_ask and (best_ask - best_bid) <= MAX_SPREAD


def yes_edge(kalshi_yes_ask: float, vegas_yes_prob: float) -> float:
    """Positive → YES is underpriced on Kalshi (buy YES)."""
    return vegas_yes_prob - kalshi_yes_ask


def no_edge(kalshi_yes_bid: float, vegas_yes_prob: float) -> float:
    """Positive → NO is underpriced on Kalshi (buy NO).
    NO ask ≈ 1 - YES bid (the complement of what someone will pay for YES).
    """
    no_ask = 1.0 - kalshi_yes_bid
    return (1.0 - vegas_yes_prob) - no_ask
