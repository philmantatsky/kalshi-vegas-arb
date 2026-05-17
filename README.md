# Kalshi–Vegas Arbitrage Bot

A paper-trading bot for the Prophet Arena prediction-market benchmark that exploits pricing inefficiencies between Kalshi sports markets and sharp Vegas sportsbook consensus.

## Strategy

Vegas sportsbook lines (especially Pinnacle/DraftKings/FanDuel consensus) are efficient — billions of dollars of sharp money corrects them in seconds. Kalshi's sports prediction markets are newer and less liquid. When Kalshi's implied probability materially disagrees with the vig-adjusted Vegas consensus, we bet with Vegas.

- Pull Kalshi market prices every 15-minute tick
- Pull Vegas odds from [The Odds API](https://the-odds-api.com/) (cached aggressively)
- Compute vig-adjusted "true" probability from multi-book consensus
- Find edges ≥3–5 percentage points
- Size with fractional Kelly (¼ Kelly) under hard exposure caps
- Exit positions when Kalshi price converges to Vegas consensus

## Architecture

```
bot/main.py          — tick lifecycle loop (claim → load → decide → submit → finalize)
bot/strategy.py      — decide_trades(): orchestrates matching, edge calc, sizing
bot/odds_client.py   — The Odds API wrapper with SQLite caching
bot/market_matcher.py — Kalshi market_id → Vegas game fuzzy matching
bot/edge.py          — vig-adjusted probability math
bot/sizing.py        — fractional Kelly position sizing
```

## Setup

```bash
# 1. Clone and enter the repo
git clone <repo-url>
cd kalshi-vegas-arb

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# Edit .env with your actual keys:
#   PA_SERVER_API_KEY — from prophetarena.co/profile/api-keys
#   PA_SERVER_URL     — https://api.aiprophet.dev
#   ODDS_API_KEY      — from the-odds-api.com

# 5. Run the bot
python -m bot.main
```

Logs are written to stdout and `logs/bot.log`.

## Deployment

Run on any always-on machine for the 2-week evaluation window (May 17–31):

- **Oracle Cloud free tier** — always-free VM (Ampere A1, 4 OCPUs, 24 GB RAM)
- **Fly.io free tier** — `fly launch`, `fly deploy`
- **DigitalOcean** — $5/month droplet

```bash
# Run in background with nohup
nohup python -m bot.main > logs/nohup.log 2>&1 &
```

## License

MIT
