from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG: dict[str, Any] = {
    "bot": {
        "scan_interval_seconds": 300,
        "scan_limit": 75,
        "request_timeout_seconds": 12,
        "log_level": "INFO",
    },
    "polymarket": {
        "gamma_url": "https://gamma-api.polymarket.com/markets",
        "min_liquidity": 1000.0,
        "weather_keywords": [
            "weather",
            "temperature",
            "rain",
            "snow",
            "precip",
            "hurricane",
            "wind",
            "degrees",
            "f ",
            "c ",
            "hot",
            "cold",
        ],
    },
    "weather": {
        "geocode_url": "https://geocoding-api.open-meteo.com/v1/search",
        "forecast_url": "https://api.open-meteo.com/v1/forecast",
        "lookahead_hours": 72,
    },
    "signal": {
        "min_edge_bps": 300,
        "min_confidence": 0.55,
    },
}


ENV_MAP: dict[str, tuple[str, callable]] = {
    "BOT_SCAN_INTERVAL_SECONDS": ("bot.scan_interval_seconds", int),
    "BOT_SCAN_LIMIT": ("bot.scan_limit", int),
    "BOT_REQUEST_TIMEOUT_SECONDS": ("bot.request_timeout_seconds", int),
    "POLYMARKET_GAMMA_URL": ("polymarket.gamma_url", str),
    "POLYMARKET_MIN_LIQUIDITY": ("polymarket.min_liquidity", float),
    "POLYMARKET_WEATHER_KEYWORDS": (
        "polymarket.weather_keywords",
        lambda raw: [x.strip() for x in raw.split(",") if x.strip()],
    ),
    "WEATHER_GEOCODE_URL": ("weather.geocode_url", str),
    "WEATHER_FORECAST_URL": ("weather.forecast_url", str),
    "WEATHER_LOOKAHEAD_HOURS": ("weather.lookahead_hours", int),
    "SIGNAL_MIN_EDGE_BPS": ("signal.min_edge_bps", int),
    "SIGNAL_MIN_CONFIDENCE": ("signal.min_confidence", float),
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(base.get(key), dict) and isinstance(value, dict):
            deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def set_path(config: dict[str, Any], dotted_path: str, value: Any) -> None:
    parts = dotted_path.split(".")
    node: dict[str, Any] = config
    for part in parts[:-1]:
        current = node.get(part)
        if not isinstance(current, dict):
            current = {}
            node[part] = current
        node = current
    node[parts[-1]] = value


def load_config(config_path: str | None) -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if config_path:
        path = Path(config_path)
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"Expected dict in config file: {path}")
            deep_merge(cfg, raw)

    for env_key, (path, parser) in ENV_MAP.items():
        raw_value = os.getenv(env_key)
        if raw_value is None:
            continue
        set_path(cfg, path, parser(raw_value))

    return cfg

