"""Demo portfolio — simulated trading for learning the system.

State stored in ~/.market_analyzer/demo_portfolio.json.
MA remains stateless — this module reads/writes local files only.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from pydantic import BaseModel

DEMO_DIR = Path.home() / ".market_analyzer"
DEMO_FILE = DEMO_DIR / "demo_portfolio.json"
DEMO_CAPITAL = 100_000.0


class DemoPosition(BaseModel):
    """A simulated open position."""
    position_id: str
    ticker: str
    desk_key: str
    structure_type: str
    legs: list[dict]        # Serialized LegSpec dicts
    entry_date: str         # ISO date
    entry_price: float      # Credit or debit per contract
    contracts: int
    entry_regime_id: int
    dte_at_entry: int
    max_profit: float
    max_loss: float
    status: str = "open"    # "open" | "closed"
    close_date: str | None = None
    close_price: float | None = None
    pnl: float | None = None
    close_reason: str | None = None


class DemoPortfolio(BaseModel):
    """Complete demo portfolio state."""
    created: str
    total_capital: float
    risk_tolerance: str
    market: str
    desks: list[dict]               # Serialized DeskSpec dicts
    asset_allocations: list[dict]   # Serialized AssetAllocation dicts
    positions: list[DemoPosition]
    closed_positions: list[DemoPosition]
    cash_balance: float             # Available cash (capital - deployed)
    peak_nlv: float
    current_nlv: float              # Approximate (cash + position values)


def create_demo_portfolio(
    capital: float = DEMO_CAPITAL,
    risk_tolerance: str = "moderate",
    market: str = "US",
    regime: dict[str, int] | None = None,
) -> DemoPortfolio:
    """Create a new demo portfolio with desk allocation.

    Saves to ~/.market_analyzer/demo_portfolio.json.
    """
    from market_analyzer.features.desk_management import recommend_desk_structure

    rec = recommend_desk_structure(
        total_capital=capital,
        risk_tolerance=risk_tolerance,
        market=market,
        regime=regime,
    )

    portfolio = DemoPortfolio(
        created=datetime.now().isoformat(),
        total_capital=capital,
        risk_tolerance=risk_tolerance,
        market=market,
        desks=[d.model_dump() for d in rec.desks],
        asset_allocations=[a.model_dump() for a in rec.allocations],
        positions=[],
        closed_positions=[],
        cash_balance=capital,
        peak_nlv=capital,
        current_nlv=capital,
    )

    save_demo_portfolio(portfolio)
    return portfolio


def load_demo_portfolio() -> DemoPortfolio | None:
    """Load demo portfolio from disk. Returns None if not found."""
    if not DEMO_FILE.exists():
        return None
    try:
        data = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
        return DemoPortfolio.model_validate(data)
    except Exception:
        return None


def save_demo_portfolio(portfolio: DemoPortfolio) -> None:
    """Save demo portfolio to disk."""
    DEMO_DIR.mkdir(exist_ok=True)
    DEMO_FILE.write_text(portfolio.model_dump_json(indent=2), encoding="utf-8")


def add_demo_position(
    portfolio: DemoPortfolio,
    ticker: str,
    desk_key: str | dict,
    trade_spec,          # TradeSpec
    entry_price: float,
    contracts: int,
    regime_id: int,
) -> DemoPosition:
    """Add a simulated position to the demo portfolio."""
    import uuid

    # suggest_desk_for_trade() returns a dict — extract the key if so
    if isinstance(desk_key, dict):
        desk_key = desk_key.get("desk_key", "unknown")

    position = DemoPosition(
        position_id=str(uuid.uuid4())[:8],
        ticker=ticker,
        desk_key=desk_key,
        structure_type=trade_spec.structure_type or "unknown",
        legs=[l.model_dump() for l in trade_spec.legs],
        entry_date=date.today().isoformat(),
        entry_price=entry_price,
        contracts=contracts,
        entry_regime_id=regime_id,
        dte_at_entry=trade_spec.target_dte,
        max_profit=entry_price * trade_spec.lot_size * contracts,
        max_loss=(trade_spec.wing_width_points or 5.0) * trade_spec.lot_size * contracts - entry_price * trade_spec.lot_size * contracts,
    )

    # Update cash
    if trade_spec.order_side == "debit":
        cost = entry_price * trade_spec.lot_size * contracts
        portfolio.cash_balance -= cost
    else:
        # Credit trade: margin required = wing × lot × contracts
        margin = (trade_spec.wing_width_points or 5.0) * trade_spec.lot_size * contracts
        portfolio.cash_balance -= margin  # Reserve margin

    portfolio.positions.append(position)
    save_demo_portfolio(portfolio)
    return position


def close_demo_position(
    portfolio: DemoPortfolio,
    position_id: str,
    close_price: float,
    reason: str,
) -> DemoPosition | None:
    """Close a demo position and record P&L."""
    pos = None
    for p in portfolio.positions:
        if p.position_id == position_id:
            pos = p
            break

    if pos is None:
        return None

    pos.status = "closed"
    pos.close_date = date.today().isoformat()
    pos.close_price = close_price
    pos.close_reason = reason

    # P&L calculation
    lot = 100  # Default
    if pos.structure_type in ("equity_long", "equity_sell"):
        pos.pnl = (close_price - pos.entry_price) * pos.contracts
    else:
        # Credit trade: profit = (entry - close) * lot * contracts
        pos.pnl = (pos.entry_price - close_price) * lot * pos.contracts

    portfolio.positions.remove(pos)
    portfolio.closed_positions.append(pos)

    # Return margin/update cash
    portfolio.cash_balance += (pos.max_loss + pos.max_profit) + pos.pnl  # Simplified
    portfolio.current_nlv = portfolio.cash_balance + sum(
        p.max_profit * 0.5 for p in portfolio.positions  # Rough estimate
    )
    portfolio.peak_nlv = max(portfolio.peak_nlv, portfolio.current_nlv)

    save_demo_portfolio(portfolio)
    return pos


def get_demo_summary(portfolio: DemoPortfolio) -> dict:
    """Get portfolio summary for CLI display."""
    open_count = len(portfolio.positions)
    closed_count = len(portfolio.closed_positions)
    total_pnl = sum(p.pnl or 0 for p in portfolio.closed_positions)
    winners = sum(1 for p in portfolio.closed_positions if (p.pnl or 0) > 0)
    win_rate = winners / closed_count if closed_count > 0 else 0

    drawdown = (portfolio.peak_nlv - portfolio.current_nlv) / portfolio.peak_nlv if portfolio.peak_nlv > 0 else 0

    # Per-desk breakdown
    desk_positions: dict[str, list] = {}
    for p in portfolio.positions:
        desk_positions.setdefault(p.desk_key, []).append(p)

    return {
        "capital": portfolio.total_capital,
        "current_nlv": portfolio.current_nlv,
        "cash": portfolio.cash_balance,
        "open_positions": open_count,
        "closed_trades": closed_count,
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "drawdown_pct": drawdown,
        "desks": desk_positions,
        "risk_tolerance": portfolio.risk_tolerance,
        "market": portfolio.market,
    }
