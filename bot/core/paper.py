from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from bot.models.signal import Signal


def _resolve_state_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    return (Path.cwd() / path).resolve()


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _price_for_side(yes_price: float, side: str) -> float:
    yes_price = max(0.001, min(0.999, float(yes_price)))
    return yes_price if side == "YES" else (1.0 - yes_price)


def _value_for_side(qty: float, yes_price: float, side: str) -> float:
    return qty * _price_for_side(yes_price, side)


def _signal_side(action: str) -> str:
    return "YES" if action == "BUY_YES" else "NO"


def _load_state(path: Path, starting_cash_usd: float) -> dict[str, Any]:
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            loaded.setdefault("cash_usd", float(starting_cash_usd))
            loaded.setdefault("positions", {})
            loaded.setdefault("trades", [])
            return loaded
    return {"cash_usd": float(starting_cash_usd), "positions": {}, "trades": []}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def apply_paper_trading(
    cfg: dict[str, Any],
    evaluations: list[dict[str, Any]],
    alerts: list[Signal],
) -> dict[str, Any]:
    paper_cfg = cfg["paper"]
    state_path = _resolve_state_path(str(paper_cfg["state_path"]))
    state = _load_state(state_path, float(paper_cfg["starting_cash_usd"]))

    cash = float(state["cash_usd"])
    positions: dict[str, dict[str, Any]] = state["positions"]
    trades: list[dict[str, Any]] = list(state.get("trades") or [])

    position_size_usd = float(paper_cfg["position_size_usd"])
    max_open_positions = int(paper_cfg["max_open_positions"])
    close_edge_bps = int(paper_cfg["close_edge_bps"])
    now = _now_iso()

    eval_by_market = {str(row["market_id"]): row for row in evaluations}
    signal_by_market = {s.market_id: s for s in alerts}

    opened: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []

    # Close pass.
    for market_id, position in list(positions.items()):
        side = str(position["side"])
        qty = float(position["qty"])
        entry_cost = float(position["cost_usd"])

        row = eval_by_market.get(market_id)
        yes_price = float(row["market_yes_prob"]) if row else float(position.get("last_yes_price", position["entry_yes_price"]))
        current_value = _value_for_side(qty, yes_price, side)
        close_reason: str | None = None

        signal = signal_by_market.get(market_id)
        if signal is not None:
            signal_side = _signal_side(signal.action)
            if signal_side != side:
                close_reason = "opposite_signal"

        if close_reason is None and row is not None:
            edge_bps = int(row["edge_bps"])
            if side == "YES" and edge_bps < close_edge_bps:
                close_reason = "edge_decay"
            if side == "NO" and edge_bps > -close_edge_bps:
                close_reason = "edge_decay"

        if close_reason:
            cash += current_value
            realized_pnl = current_value - entry_cost
            close_trade = {
                "ts": now,
                "type": "CLOSE",
                "market_id": market_id,
                "question": position["question"],
                "side": side,
                "qty": round(qty, 8),
                "yes_price": round(yes_price, 6),
                "proceeds_usd": round(current_value, 2),
                "cost_usd": round(entry_cost, 2),
                "realized_pnl_usd": round(realized_pnl, 2),
                "reason": close_reason,
            }
            trades.append(close_trade)
            closed.append(close_trade)
            del positions[market_id]
        else:
            position["last_yes_price"] = yes_price
            position["last_mark_value_usd"] = round(current_value, 2)
            position["last_mark_ts"] = now

    # Open pass (highest edge first).
    sorted_alerts = sorted(alerts, key=lambda s: abs(s.edge_bps), reverse=True)
    for signal in sorted_alerts:
        if len(positions) >= max_open_positions:
            break
        market_id = signal.market_id
        side = _signal_side(signal.action)
        row = eval_by_market.get(market_id)
        yes_price = float(row["market_yes_prob"]) if row else float(signal.market_yes_prob)
        unit_price = _price_for_side(yes_price, side)

        existing = positions.get(market_id)
        if existing and str(existing["side"]) == side:
            continue

        if cash < position_size_usd:
            break

        qty = position_size_usd / unit_price
        cash -= position_size_usd

        new_position = {
            "market_id": market_id,
            "question": signal.question,
            "side": side,
            "qty": qty,
            "entry_yes_price": yes_price,
            "entry_unit_price": unit_price,
            "cost_usd": position_size_usd,
            "entry_ts": now,
            "last_yes_price": yes_price,
            "last_mark_value_usd": position_size_usd,
            "last_mark_ts": now,
        }
        positions[market_id] = new_position

        open_trade = {
            "ts": now,
            "type": "OPEN",
            "market_id": market_id,
            "question": signal.question,
            "side": side,
            "qty": round(qty, 8),
            "yes_price": round(yes_price, 6),
            "cost_usd": round(position_size_usd, 2),
            "signal_edge_bps": signal.edge_bps,
            "signal_confidence": signal.confidence,
        }
        trades.append(open_trade)
        opened.append(open_trade)

    # Portfolio marks.
    marked_positions: list[dict[str, Any]] = []
    total_mark_value = 0.0
    total_cost = 0.0
    for market_id, position in positions.items():
        row = eval_by_market.get(market_id)
        yes_price = float(row["market_yes_prob"]) if row else float(position.get("last_yes_price", position["entry_yes_price"]))
        qty = float(position["qty"])
        mark_value = _value_for_side(qty, yes_price, str(position["side"]))
        cost = float(position["cost_usd"])
        total_mark_value += mark_value
        total_cost += cost
        marked_positions.append(
            {
                "market_id": market_id,
                "question": position["question"],
                "side": position["side"],
                "qty": round(qty, 8),
                "entry_yes_price": round(float(position["entry_yes_price"]), 6),
                "mark_yes_price": round(yes_price, 6),
                "cost_usd": round(cost, 2),
                "mark_value_usd": round(mark_value, 2),
                "unrealized_pnl_usd": round(mark_value - cost, 2),
            }
        )

    equity = cash + total_mark_value
    summary = {
        "enabled": True,
        "state_path": str(state_path),
        "cash_usd": round(cash, 2),
        "equity_usd": round(equity, 2),
        "open_positions": len(marked_positions),
        "position_value_usd": round(total_mark_value, 2),
        "unrealized_pnl_usd": round(total_mark_value - total_cost, 2),
        "opened": opened,
        "closed": closed,
        "positions": marked_positions,
    }

    state["cash_usd"] = cash
    state["positions"] = positions
    state["trades"] = trades[-1000:]
    state["updated_at"] = now
    state["last_summary"] = summary
    _save_state(state_path, state)
    return summary

