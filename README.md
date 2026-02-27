# Polymarket Weather Bot

Scans active weather-related Polymarket markets, estimates model probability from Open-Meteo forecasts, emits JSON trading signals, and can run paper-trading simulation.

## What It Does

- pulls active markets from Polymarket Gamma
- filters weather-like questions
- estimates model `YES` probability from weather data
- computes edge (bps) vs market `YES` price
- emits `BUY_YES` / `BUY_NO` alerts when thresholds pass
- optional paper trading with persistent local state file

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/config.example.yaml config/config.yaml
python -m bot.main --config config/config.yaml --mode scan --once
python -m bot.main --config config/config.yaml --mode paper --once
```

## Railway Deploy

This repo includes:

- `Procfile`
- `railway.json`
- `runtime.txt`

Default start command:

```bash
python -m bot.main --mode alert --config config/config.yaml
```

## Config Fallback (Env-Only Mode)

If `config/config.yaml` is missing, the bot still runs using defaults + env vars.

Recommended env vars on Railway:

- `PYTHONUNBUFFERED=1`
- `BOT_SCAN_INTERVAL_SECONDS=300`
- `BOT_SCAN_LIMIT=75`
- `POLYMARKET_MIN_LIQUIDITY=1000`
- `SIGNAL_MIN_EDGE_BPS=300`
- `SIGNAL_MIN_CONFIDENCE=0.55`
- `WEATHER_LOOKAHEAD_HOURS=72`
- `BOT_MODE=alert` (or `paper`)

Paper trading env vars:

- `PAPER_ENABLED=true`
- `PAPER_STATE_PATH=state/paper_state.json`
- `PAPER_STARTING_CASH_USD=10000`
- `PAPER_POSITION_SIZE_USD=100`
- `PAPER_MAX_OPEN_POSITIONS=12`
- `PAPER_CLOSE_EDGE_BPS=100`

Optional endpoint overrides:

- `POLYMARKET_GAMMA_URL`
- `WEATHER_GEOCODE_URL`
- `WEATHER_FORECAST_URL`

Optional list override:

- `POLYMARKET_WEATHER_KEYWORDS=weather,temperature,rain,snow,wind`

## Notes

- This is alert/scanning logic only. It does not execute trades.
- Paper mode simulates entries/exits and updates a state file; no real trading API calls are made.
- Use `--once` for one-pass checks.
- For always-on Railway worker mode, omit `--once`.
