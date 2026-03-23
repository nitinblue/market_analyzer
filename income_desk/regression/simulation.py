"""Synthetic snapshot generators for after-hours testing.

Create realistic snapshot dicts for testing when markets are closed.
Each function returns a dict matching the snapshot JSON format used by
eTrading (same structure as ``snapshot_US_*.json``).
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any


def create_calm_market() -> dict[str, Any]:
    """R1 regime, low vol, 3 healthy trades, all passing."""
    now = datetime.now()
    return {
        "snapshot_id": f"sim-calm-{now:%Y%m%d-%H%M%S}",
        "market": "US",
        "captured_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "broker_connected": True,
        "regime": {"regime_id": 1, "confidence": 0.82},
        "portfolios": [
            {"id": "p-taxable", "name": "Taxable", "capital": 50000.0},
            {"id": "p-ira", "name": "IRA", "capital": 200000.0},
        ],
        "desks": [
            {
                "desk_key": "desk_income",
                "capital": 50000.0,
                "risk_limits": {
                    "max_positions": 8,
                    "max_single_position_pct": 15,
                    "max_daily_loss": 1000.0,
                },
            },
        ],
        "open_trades": [
            _make_spy_iron_condor(
                trade_id="sim-calm-ic-spy",
                entry_price=1.80,
                current_price=0.90,
                total_pnl=90.0,
                health_status="safe",
            ),
            _make_aapl_credit_spread(
                trade_id="sim-calm-cs-aapl",
                entry_price=1.20,
                current_price=0.60,
                total_pnl=60.0,
                health_status="safe",
            ),
            _make_spy_credit_spread(
                trade_id="sim-calm-cs-spy",
                entry_price=0.95,
                current_price=0.50,
                total_pnl=45.0,
                health_status="safe",
            ),
        ],
        "decision_log": [
            {
                "action": "HOLD",
                "ticker": "SPY",
                "reason": "All trades safe, R1 low-vol mean-reverting",
            },
        ],
        "closed_today": [],
        "stats": {"total_pnl": 195.0, "win_rate": 1.0},
    }


def create_volatile_market() -> dict[str, Any]:
    """R2 regime, high vol, trades with tested sides, some warnings."""
    now = datetime.now()
    return {
        "snapshot_id": f"sim-volatile-{now:%Y%m%d-%H%M%S}",
        "market": "US",
        "captured_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "broker_connected": True,
        "regime": {"regime_id": 2, "confidence": 0.71},
        "portfolios": [
            {"id": "p-taxable", "name": "Taxable", "capital": 50000.0},
            {"id": "p-ira", "name": "IRA", "capital": 200000.0},
        ],
        "desks": [
            {
                "desk_key": "desk_income",
                "capital": 50000.0,
                "risk_limits": {
                    "max_positions": 8,
                    "max_single_position_pct": 15,
                    "max_daily_loss": 1500.0,
                },
            },
        ],
        "open_trades": [
            _make_spy_iron_condor(
                trade_id="sim-vol-ic-spy",
                entry_price=2.50,
                current_price=3.10,
                total_pnl=-60.0,
                health_status="tested",
            ),
            _make_aapl_credit_spread(
                trade_id="sim-vol-cs-aapl",
                entry_price=1.60,
                current_price=1.80,
                total_pnl=-20.0,
                health_status="tested",
            ),
        ],
        "decision_log": [
            {
                "action": "MONITOR",
                "ticker": "SPY",
                "reason": "R2 high-vol, put side tested — monitor closely",
            },
            {
                "action": "HOLD",
                "ticker": "AAPL",
                "reason": "Tested but within adjustment threshold",
            },
        ],
        "closed_today": [],
        "stats": {"total_pnl": -80.0, "win_rate": 0.0},
    }


def create_crash_scenario() -> dict[str, Any]:
    """R4 regime, trades breached, PnL negative, health critical."""
    now = datetime.now()
    return {
        "snapshot_id": f"sim-crash-{now:%Y%m%d-%H%M%S}",
        "market": "US",
        "captured_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "broker_connected": True,
        "regime": {"regime_id": 4, "confidence": 0.88},
        "portfolios": [
            {"id": "p-taxable", "name": "Taxable", "capital": 50000.0},
            {"id": "p-ira", "name": "IRA", "capital": 200000.0},
        ],
        "desks": [
            {
                "desk_key": "desk_income",
                "capital": 50000.0,
                "risk_limits": {
                    "max_positions": 8,
                    "max_single_position_pct": 15,
                    "max_daily_loss": 1500.0,
                },
            },
        ],
        "open_trades": [
            _make_spy_iron_condor(
                trade_id="sim-crash-ic-spy",
                entry_price=1.80,
                current_price=4.50,
                total_pnl=-270.0,
                health_status="breached",
            ),
            _make_aapl_credit_spread(
                trade_id="sim-crash-cs-aapl",
                entry_price=1.20,
                current_price=3.80,
                total_pnl=-260.0,
                health_status="breached",
            ),
            _make_spy_credit_spread(
                trade_id="sim-crash-cs-spy",
                entry_price=0.95,
                current_price=4.20,
                total_pnl=-325.0,
                health_status="max_loss",
            ),
        ],
        "decision_log": [
            {
                "action": "CLOSE",
                "ticker": "SPY",
                "reason": "R4 high-vol trending, IC breached — close immediately",
            },
            {
                "action": "CLOSE",
                "ticker": "AAPL",
                "reason": "Breached in R4 — risk-off",
            },
            {
                "action": "CLOSE",
                "ticker": "SPY",
                "reason": "Credit spread at max loss — close",
            },
        ],
        "closed_today": [
            {
                "id": "sim-crash-closed-1",
                "ticker": "QQQ",
                "pnl": -180.0,
                "reason": "Stopped out in crash",
            },
        ],
        "stats": {"total_pnl": -855.0, "win_rate": 0.0},
    }


def create_from_snapshot(base_snapshot: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Clone a snapshot with modifications for testing edge cases.

    Supports nested key overrides using dunder notation:
    ``create_from_snapshot(snap, regime__confidence=0.5)``
    sets ``snap["regime"]["confidence"] = 0.5``.

    Direct key overrides replace the value at top level:
    ``create_from_snapshot(snap, broker_connected=False)``
    """
    result = copy.deepcopy(base_snapshot)
    for key, value in overrides.items():
        if "__" in key:
            parts = key.split("__")
            target = result
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
        else:
            result[key] = value
    return result


# ── Internal helpers ──


def _make_spy_iron_condor(
    trade_id: str,
    entry_price: float,
    current_price: float,
    total_pnl: float,
    health_status: str,
) -> dict[str, Any]:
    """SPY iron condor with 4 legs."""
    return {
        "id": trade_id,
        "ticker": "SPY",
        "trade_type": "real",
        "strategy_type": "iron_condor",
        "entry_price": entry_price,
        "current_price": current_price,
        "total_pnl": total_pnl,
        "health_status": health_status,
        "decision_lineage": {
            "score": 0.72,
            "gates": [{"name": "ev", "passed": True}],
            "strategy_type": "iron_condor",
        },
        "legs": [
            {
                "id": f"{trade_id}-l1",
                "symbol_ticker": "SPY",
                "asset_type": "option",
                "option_type": "put",
                "strike": 555.0,
                "expiration": "2026-04-17",
                "quantity": -1,
                "entry_price": 2.80,
                "current_price": 2.80 + (current_price - entry_price) * 0.3,
                "dxlink_symbol": ".SPY260417P555",
                "action": "STO",
            },
            {
                "id": f"{trade_id}-l2",
                "symbol_ticker": "SPY",
                "asset_type": "option",
                "option_type": "put",
                "strike": 550.0,
                "expiration": "2026-04-17",
                "quantity": 1,
                "entry_price": 2.30,
                "current_price": 2.30 + (current_price - entry_price) * 0.2,
                "dxlink_symbol": ".SPY260417P550",
                "action": "BTO",
            },
            {
                "id": f"{trade_id}-l3",
                "symbol_ticker": "SPY",
                "asset_type": "option",
                "option_type": "call",
                "strike": 600.0,
                "expiration": "2026-04-17",
                "quantity": -1,
                "entry_price": 3.20,
                "current_price": 3.20 + (current_price - entry_price) * 0.3,
                "dxlink_symbol": ".SPY260417C600",
                "action": "STO",
            },
            {
                "id": f"{trade_id}-l4",
                "symbol_ticker": "SPY",
                "asset_type": "option",
                "option_type": "call",
                "strike": 605.0,
                "expiration": "2026-04-17",
                "quantity": 1,
                "entry_price": 2.70,
                "current_price": 2.70 + (current_price - entry_price) * 0.2,
                "dxlink_symbol": ".SPY260417C605",
                "action": "BTO",
            },
        ],
    }


def _make_aapl_credit_spread(
    trade_id: str,
    entry_price: float,
    current_price: float,
    total_pnl: float,
    health_status: str,
) -> dict[str, Any]:
    """AAPL put credit spread with 2 legs."""
    return {
        "id": trade_id,
        "ticker": "AAPL",
        "trade_type": "real",
        "strategy_type": "credit_spread",
        "entry_price": entry_price,
        "current_price": current_price,
        "total_pnl": total_pnl,
        "health_status": health_status,
        "decision_lineage": {
            "score": 0.61,
            "gates": [{"name": "ev", "passed": True}],
            "strategy_type": "credit_spread",
        },
        "legs": [
            {
                "id": f"{trade_id}-l1",
                "symbol_ticker": "AAPL",
                "asset_type": "option",
                "option_type": "put",
                "strike": 210.0,
                "expiration": "2026-04-17",
                "quantity": -1,
                "entry_price": 3.50,
                "current_price": 3.50 + (current_price - entry_price) * 0.6,
                "dxlink_symbol": ".AAPL260417P210",
                "action": "STO",
            },
            {
                "id": f"{trade_id}-l2",
                "symbol_ticker": "AAPL",
                "asset_type": "option",
                "option_type": "put",
                "strike": 205.0,
                "expiration": "2026-04-17",
                "quantity": 1,
                "entry_price": 2.30,
                "current_price": 2.30 + (current_price - entry_price) * 0.4,
                "dxlink_symbol": ".AAPL260417P205",
                "action": "BTO",
            },
        ],
    }


def _make_spy_credit_spread(
    trade_id: str,
    entry_price: float,
    current_price: float,
    total_pnl: float,
    health_status: str,
) -> dict[str, Any]:
    """SPY call credit spread with 2 legs."""
    return {
        "id": trade_id,
        "ticker": "SPY",
        "trade_type": "real",
        "strategy_type": "credit_spread",
        "entry_price": entry_price,
        "current_price": current_price,
        "total_pnl": total_pnl,
        "health_status": health_status,
        "decision_lineage": {
            "score": 0.58,
            "gates": [{"name": "ev", "passed": True}],
            "strategy_type": "credit_spread",
        },
        "legs": [
            {
                "id": f"{trade_id}-l1",
                "symbol_ticker": "SPY",
                "asset_type": "option",
                "option_type": "call",
                "strike": 595.0,
                "expiration": "2026-04-17",
                "quantity": -1,
                "entry_price": 2.50,
                "current_price": 2.50 + (current_price - entry_price) * 0.6,
                "dxlink_symbol": ".SPY260417C595",
                "action": "STO",
            },
            {
                "id": f"{trade_id}-l2",
                "symbol_ticker": "SPY",
                "asset_type": "option",
                "option_type": "call",
                "strike": 600.0,
                "expiration": "2026-04-17",
                "quantity": 1,
                "entry_price": 1.55,
                "current_price": 1.55 + (current_price - entry_price) * 0.4,
                "dxlink_symbol": ".SPY260417C600",
                "action": "BTO",
            },
        ],
    }
