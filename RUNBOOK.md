# Deployment Runbook — Kalshi Vegas Arbitrage Bot

Target: fresh Oracle Cloud Ubuntu 22.04 ARM (Ampere A1.Flex) VM.

---

## 1. System prerequisites

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev \
    git build-essential
```

Verify Python version:
```bash
python3.11 --version   # must be 3.11.x
```

---

## 2. Clone the repo

```bash
cd ~
git clone https://github.com/YOUR_ORG/kalshi-vegas-arb.git
cd kalshi-vegas-arb
```

---

## 3. Create and populate `.env`

```bash
cp .env.example .env
nano .env
```

Fill in all four values:

| Variable | Description | Where to get it |
|---|---|---|
| `PA_SERVER_API_KEY` | Prophet Arena API key | prophetarena.co/profile/api-keys |
| `PA_SERVER_URL` | Prophet Arena base URL | Always `https://api.aiprophet.dev` |
| `ODDS_API_KEY` | The Odds API key | the-odds-api.com dashboard |
| `EXPERIMENT_SLUG` | Experiment name | Use `kalshi-vegas-arb-v1` for testing, `kalshi-vegas-arb` for production |

**Do not commit `.env`.** It is gitignored.

---

## 4. Install dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Run manually to verify

```bash
source .venv/bin/activate
python -m bot.main
```

Expected output within 30 seconds:
```
INFO bot Participant idx=0
INFO bot WC outrights loaded: 48 teams
INFO bot EPL title probs (standings-based): 20 teams
INFO bot No tick available reason=None sleeping=15s
```

Wait up to 15 minutes for a tick. When one fires you should see:
```
INFO bot tick=1 id=2026-05-17T... markets=256 cash=10000.00 positions=0
INFO bot   no trades submitted   ← or BUY YES/NO lines if edges found
INFO bot   submitted=N accepted=N rejected=0
```

`Ctrl+C` once confirmed. Do NOT let it run long on the test slug — ticks are consumed.

---

## 6. systemd service

### Create the unit file

```bash
sudo nano /etc/systemd/system/prophet-bot.service
```

Paste this exactly (replace `/home/ubuntu` if your home dir differs):

```ini
[Unit]
Description=Prophet Arena Trading Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/kalshi-vegas-arb
EnvironmentFile=/home/ubuntu/kalshi-vegas-arb/.env
ExecStart=/home/ubuntu/kalshi-vegas-arb/.venv/bin/python -m bot.main
Restart=on-failure
RestartSec=15
StandardOutput=journal
StandardError=journal
SyslogIdentifier=prophet-bot

[Install]
WantedBy=multi-user.target
```

### Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable prophet-bot
sudo systemctl start prophet-bot
```

### Verify it's running

```bash
sudo systemctl status prophet-bot
```

Should show `Active: active (running)`.

---

## 7. Checking logs

```bash
# Follow live logs
journalctl -u prophet-bot -f

# Last 100 lines
journalctl -u prophet-bot -n 100

# Filter for trades only
journalctl -u prophet-bot | grep -E "BUY|SELL|submitted|accepted"

# Filter for errors
journalctl -u prophet-bot | grep -E "ERROR|REJECTED|Traceback"
```

Confirm the bot is ticking by looking for lines like:
```
INFO bot tick=N id=2026-05-17T...
```
These appear every 15 minutes.

---

## 8. Slug switch — Sunday 5 PM CT (22:00 UTC)

This is the go-live step. Do it as close to 5 PM CT as possible.

```bash
# Edit .env on the VM
nano /home/ubuntu/kalshi-vegas-arb/.env

# Change:
EXPERIMENT_SLUG=kalshi-vegas-arb-v1
# To:
EXPERIMENT_SLUG=kalshi-vegas-arb

# Restart the service
sudo systemctl restart prophet-bot

# Confirm it picked up the new slug
journalctl -u prophet-bot -f
```

Look for:
```
INFO httpx HTTP Request: POST https://api.aiprophet.dev/experiments "HTTP/1.1 200 OK"
INFO bot Participant idx=0
```

The bot is now live on the competition slug. Do NOT change the slug again.

---

## 9. Ongoing health checks

The bot is self-healing (systemd auto-restarts on crash). To confirm it's alive:

```bash
# Is the service running?
sudo systemctl is-active prophet-bot

# When did it last tick?
journalctl -u prophet-bot | grep "tick=" | tail -3

# API quota remaining?
journalctl -u prophet-bot | grep "remaining=" | tail -5
```

If the bot has been silent for >20 minutes, something is wrong:
```bash
sudo systemctl restart prophet-bot
journalctl -u prophet-bot -f
```

---

## 10. Stopping the bot

```bash
sudo systemctl stop prophet-bot
```

To prevent auto-restart on reboot:
```bash
sudo systemctl disable prophet-bot
```
