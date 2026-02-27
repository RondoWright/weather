from __future__ import annotations

import datetime as dt
from typing import Any

from bot.adapters.polymarket import fetch_weather_candidates
from bot.adapters.weather import estimate_yes_probability
from bot.models.signal import Signal, evaluate_signal


def run_scan(cfg: dict[str, Any]) -> dict[str, Any]:
    candidates = fetch_weather_candidates(cfg)
    alerts: list[Signal] = []
    skipped = 0

    for market in candidates:
        try:
            model_prob, confidence, rationale = estimate_yes_probability(
                question=str(market["question"]),
                cfg=cfg,
            )
            signal = evaluate_signal(
                market=market,
                model_prob=model_prob,
                confidence=confidence,
                rationale=rationale,
                cfg=cfg,
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

    return {
        "timestamp": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "scanned_count": len(candidates),
        "skipped_count": skipped,
        "alerts_count": len(alerts),
        "alerts": [a.to_dict() for a in alerts],
    }

