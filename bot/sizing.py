KELLY_FRACTION = 0.25
MAX_TRADE_USD = 400.0    # max dollars per single trade
MAX_MARKET_USD = 600.0   # max cumulative exposure per market_id
MAX_GROSS_USD = 5_000.0  # max total open exposure (50% of bankroll)


def kelly_dollars(
    edge: float,
    entry_price: float,
    bankroll: float,
    *,
    kelly_fraction: float = KELLY_FRACTION,
) -> float:
    """Target dollars to invest using fractional Kelly.

    For a binary bet at price p with true prob q:
      Kelly fraction = (q - p) / (1 - p) = edge / (1 - p)
    """
    if edge <= 0 or entry_price <= 0 or entry_price >= 1:
        return 0.0
    kelly_full = edge / (1.0 - entry_price)
    return bankroll * kelly_full * kelly_fraction


def apply_caps(
    target_dollars: float,
    *,
    current_market_usd: float = 0.0,
    current_gross_usd: float = 0.0,
) -> float:
    d = min(target_dollars, MAX_TRADE_USD)
    d = min(d, MAX_MARKET_USD - current_market_usd)
    d = min(d, MAX_GROSS_USD - current_gross_usd)
    return max(d, 0.0)


def to_shares(dollars: float, price: float) -> str:
    """Convert dollar amount to share count string for the API."""
    if price <= 0:
        return "0"
    return f"{dollars / price:.4f}"
