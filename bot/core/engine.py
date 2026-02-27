from __future__ import annotations

import datetime as dt
from typing import Any

from bot.adapters.polymarket import fetch_weather_candidates
from bot.adapters.weather import estimate_yes_probability
from bot.core.paper import apply_paper_trading
from bot.models.signal import Signal, evaluate_signal


def run_scan(cfg: dict[str, Any], mode: str = "alert") -> dict[str, Any]:
    candidates = fetch_weather_candidates(cfg)
    alerts: list[Signal] = []
    evaluations: list[dict[str, Any]] = []
    skipped = 0

    for market in candidates:
        try:
            model_prob, confidence, rationale = estimate_yes_probability(
                question=str(market["question"]),
                cfg=cfg,
            )
            market_yes_prob = float(market["yes_price"])
            edge_bps = int(round((model_prob - market_yes_prob) * 10_000))
            signal = evaluate_signal(
                market=market,
                model_prob=model_prob,
                confidence=confidence,
                rationale=rationale,
                cfg=cfg,
            )

            evaluations.append(
                {
                    "market_id": str(market["id"]),
                    "question": str(market["question"]),
                    "liquidity": round(float(market["liquidity"]), 2),
                    "market_yes_prob": round(market_yes_prob, 4),
                    "model_yes_prob": round(float(model_prob), 4),
                    "confidence": round(float(confidence), 4),
                    "edge_bps": edge_bps,
                    "signal_action": signal.action if signal else None,
                }
            )

            if signal is None:
                skipped += 1
                continue
            alerts.append(signal)
        except Exception as exc:  # pragma: no cover - fail-open by market
            skipped += 1
            print(
                f"[warn] market={market.get('id')} skipped due to adapter error: {exc}",
                flush=True,
            )

    payload: dict[str, Any] = {
        "timestamp": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "scanned_count": len(candidates),
        "skipped_count": skipped,
        "alerts_count": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
        "evaluations": evaluations,
    }
    paper_enabled = bool(cfg["paper"]["enabled"]) or mode == "paper"
    if paper_enabled:
        payload["paper"] = apply_paper_trading(cfg, evaluations, alerts)
    return payload
