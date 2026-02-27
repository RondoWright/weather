from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class Signal:
    market_id: str
    question: str
    action: str
    market_yes_prob: float
    model_yes_prob: float
    edge_bps: int
    confidence: float
    liquidity: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_signal(
    market: dict[str, Any],
    model_prob: float,
    confidence: float,
    rationale: str,
    cfg: dict[str, Any],
) -> Signal | None:
    signal_cfg = cfg["signal"]
    min_edge_bps = int(signal_cfg["min_edge_bps"])
    min_confidence = float(signal_cfg["min_confidence"])

    market_yes_prob = float(market["yes_price"])
    liquidity = float(market["liquidity"])
    edge_bps = int(round((model_prob - market_yes_prob) * 10_000))

    if confidence < min_confidence:
        return None

    if edge_bps >= min_edge_bps:
        action = "BUY_YES"
    elif edge_bps <= -min_edge_bps:
        action = "BUY_NO"
    else:
        return None

    return Signal(
        market_id=str(market["id"]),
        question=str(market["question"]),
        action=action,
        market_yes_prob=round(market_yes_prob, 4),
        model_yes_prob=round(float(model_prob), 4),
        edge_bps=edge_bps,
        confidence=round(float(confidence), 4),
        liquidity=round(liquidity, 2),
        rationale=rationale,
    )

