from __future__ import annotations

import json
from typing import Any

import requests


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_yes_price(market: dict[str, Any]) -> float | None:
    # Common direct shape from Gamma payloads.
    direct = market.get("yesPrice") or market.get("yes_price")
    if direct is not None:
        price = _to_float(direct, -1)
        return price if 0 <= price <= 1 else None

    outcomes = market.get("outcomes")
    prices = market.get("outcomePrices") or market.get("outcome_prices")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            outcomes = None
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except json.JSONDecodeError:
            prices = None

    if isinstance(outcomes, list) and isinstance(prices, list) and len(outcomes) == len(prices):
        for idx, outcome in enumerate(outcomes):
            if str(outcome).strip().lower() == "yes":
                yes = _to_float(prices[idx], -1)
                return yes if 0 <= yes <= 1 else None
    return None


def _extract_liquidity(market: dict[str, Any]) -> float:
    for key in ("liquidity", "liquidityNum", "liquidityClob", "volume", "volumeNum"):
        if key in market:
            return _to_float(market.get(key), 0.0)
    return 0.0


def _is_weather_market(question: str, keywords: list[str]) -> bool:
    q = question.lower()
    return any(keyword.lower() in q for keyword in keywords)


def _normalize_markets(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("markets", "data", "results"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def fetch_weather_candidates(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    bot_cfg = cfg["bot"]
    poly_cfg = cfg["polymarket"]
    timeout = int(bot_cfg["request_timeout_seconds"])
    scan_limit = int(bot_cfg["scan_limit"])
    min_liquidity = float(poly_cfg["min_liquidity"])
    keywords = list(poly_cfg["weather_keywords"])

    response = requests.get(
        str(poly_cfg["gamma_url"]),
        params={
            "active": "true",
            "archived": "false",
            "closed": "false",
            "limit": scan_limit,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    raw_markets = _normalize_markets(response.json())

    candidates: list[dict[str, Any]] = []
    for market in raw_markets:
        question = str(market.get("question") or market.get("title") or "").strip()
        if not question:
            continue
        if not _is_weather_market(question, keywords):
            continue
        yes_price = _extract_yes_price(market)
        if yes_price is None:
            continue
        liquidity = _extract_liquidity(market)
        if liquidity < min_liquidity:
            continue

        candidates.append(
            {
                "id": str(market.get("id") or market.get("conditionId") or market.get("slug") or question),
                "question": question,
                "yes_price": yes_price,
                "liquidity": liquidity,
                "raw": market,
            }
        )

    return sorted(candidates, key=lambda x: x["liquidity"], reverse=True)

