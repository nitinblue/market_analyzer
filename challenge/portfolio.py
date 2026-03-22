"""Portfolio tracker for the $30K Trading Challenge.

All APIs designed for trading platform consumption. YAML is the backing store.
eTrading calls these functions with TradeSpec objects + fill data.

Usage::

    from challenge.portfolio import Portfolio

    port = Portfolio()  # Loads config + trades from YAML

    # Pre-trade risk check
    check = port.check_risk(trade_spec, contracts=2, entry_price=0.72)
    if check.allowed:
        record = port.book_trade(trade_spec, entry_price=0.72, contracts=2)

    # Portfolio status
    status = port.get_status()

    # Close a trade
    port.close_trade("GLD-IC-20260312-001", exit_price=0.35, reason="profit_target")

    # Review
    open_trades = port.list_trades(status="open")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from challenge.models import (
    PortfolioStatus,
    RiskCheckResult,
    RiskLimits,
    TradeRecord,
    TradeStatus,
)

if TYPE_CHECKING:
    from income_desk.models.opportunity import TradeSpec

logger = logging.getLogger(__name__)

# Default data directory
_DEFAULT_DATA_DIR = Path.home() / ".income_desk" / "challenge"


class Portfolio:
    """Portfolio tracker with YAML persistence.

    All inputs come from the trading platform. The portfolio tracks
    trades, enforces risk limits, and reports status.
    """

    def __init__(
        self,
        data_dir: Path | str | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._trades_path = self._data_dir / "trades.yaml"
        self._config_path = (
            Path(config_path) if config_path
            else self._data_dir / "config.yaml"
        )

        self._limits = self._load_config()
        self._trades: list[TradeRecord] = self._load_trades()

    # ── Public API: Trading Platform calls these ──

    def book_trade(
        self,
        trade_spec: TradeSpec,
        entry_price: float,
        contracts: int = 1,
        notes: str = "",
        tags: list[str] | None = None,
    ) -> TradeRecord:
        """Book a new trade from a TradeSpec + fill data.

        Args:
            trade_spec: The TradeSpec from income_desk (plan/opportunity output).
            entry_price: Actual fill price (net credit or debit per spread).
            contracts: Number of contracts filled.
            notes: Optional trade notes.
            tags: Optional tags (e.g., ["income", "hedge"]).

        Returns:
            The booked TradeRecord.

        Raises:
            ValueError: If risk check fails (call check_risk first to preview).
        """
        check = self.check_risk(trade_spec, contracts=contracts, entry_price=entry_price)
        if not check.allowed:
            raise ValueError(
                f"Trade blocked by risk limits: {'; '.join(check.violations)}"
            )

        trade_id = self._generate_trade_id(trade_spec)
        bp_used = self._compute_buying_power(trade_spec, entry_price, contracts)

        record = TradeRecord(
            trade_id=trade_id,
            ticker=trade_spec.ticker,
            structure_type=trade_spec.structure_type or "unknown",
            order_side=trade_spec.order_side or "credit",
            legs=[leg.model_dump(mode="json") for leg in trade_spec.legs],
            target_expiration=trade_spec.target_expiration.isoformat(),
            wing_width=trade_spec.wing_width_points,
            entry_date=date.today().isoformat(),
            entry_price=entry_price,
            contracts=contracts,
            buying_power_used=bp_used,
            profit_target_pct=trade_spec.profit_target_pct,
            stop_loss_pct=trade_spec.stop_loss_pct,
            exit_dte=trade_spec.exit_dte,
            max_entry_price=trade_spec.max_entry_price,
            notes=notes,
            tags=tags or [],
        )

        self._trades.append(record)
        self._save_trades()

        logger.info(
            "Booked %s: %s %s %dx @ %.2f (BP: $%.0f)",
            trade_id, trade_spec.ticker, trade_spec.structure_type,
            contracts, entry_price, bp_used,
        )
        return record

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        reason: str = "manual",
    ) -> TradeRecord:
        """Close an open trade.

        Args:
            trade_id: The trade ID to close.
            exit_price: Fill price to close (debit for credits, credit for debits).
            reason: Why closed: "profit_target", "stop_loss", "expiration",
                    "manual", "adjustment", "regime_change".

        Returns:
            The updated TradeRecord with P&L.
        """
        record = self._find_trade(trade_id)
        if not record.is_open:
            raise ValueError(f"Trade {trade_id} is already {record.status}")

        record.status = TradeStatus.CLOSED
        record.exit_date = date.today().isoformat()
        record.exit_price = exit_price
        record.exit_reason = reason
        record.realized_pnl = self._compute_pnl(record, exit_price)

        self._save_trades()

        logger.info(
            "Closed %s: P&L $%.2f (%s)",
            trade_id, record.realized_pnl, reason,
        )
        return record

    def expire_trade(self, trade_id: str) -> TradeRecord:
        """Mark a trade as expired (worthless or at max profit for credits)."""
        record = self._find_trade(trade_id)
        if not record.is_open:
            raise ValueError(f"Trade {trade_id} is already {record.status}")

        record.status = TradeStatus.EXPIRED
        record.exit_date = date.today().isoformat()
        record.exit_price = 0.0
        record.exit_reason = "expiration"

        if record.order_side == "credit":
            record.realized_pnl = record.entry_price * 100 * record.contracts
        else:
            record.realized_pnl = -(record.entry_price * 100 * record.contracts)

        self._save_trades()
        return record

    def check_risk(
        self,
        trade_spec: TradeSpec,
        contracts: int = 1,
        entry_price: float = 0.0,
    ) -> RiskCheckResult:
        """Pre-trade risk check — call before booking.

        Args:
            trade_spec: The proposed trade.
            contracts: Number of contracts.
            entry_price: Expected fill price.

        Returns:
            RiskCheckResult with allowed/violations/warnings.
        """
        violations: list[str] = []
        warnings: list[str] = []
        limits = self._limits

        open_trades = [t for t in self._trades if t.is_open]
        open_count = len(open_trades)
        total_risk = sum(t.max_loss or 0 for t in open_trades)
        bp_used = sum(t.buying_power_used for t in open_trades)
        bp_available = limits.account_size - bp_used

        proposed_bp = self._compute_buying_power(trade_spec, entry_price, contracts)
        proposed_risk = self._compute_max_loss(trade_spec, entry_price, contracts)

        # 1. Max positions
        if open_count >= limits.max_positions:
            violations.append(
                f"Max positions reached ({open_count}/{limits.max_positions})"
            )

        # 2. Max per ticker
        ticker_count = sum(
            1 for t in open_trades if t.ticker == trade_spec.ticker
        )
        if ticker_count >= limits.max_per_ticker:
            violations.append(
                f"Max positions for {trade_spec.ticker} reached "
                f"({ticker_count}/{limits.max_per_ticker})"
            )

        # 3. Single trade risk limit
        max_single = limits.account_size * limits.max_single_trade_risk_pct
        if proposed_risk > max_single:
            violations.append(
                f"Trade risk ${proposed_risk:.0f} exceeds single-trade limit "
                f"${max_single:.0f} ({limits.max_single_trade_risk_pct:.0%})"
            )

        # 4. Portfolio risk limit
        portfolio_risk_after = total_risk + proposed_risk
        max_portfolio = limits.account_size * limits.max_portfolio_risk_pct
        if portfolio_risk_after > max_portfolio:
            violations.append(
                f"Portfolio risk would be ${portfolio_risk_after:.0f}, "
                f"exceeds limit ${max_portfolio:.0f} "
                f"({limits.max_portfolio_risk_pct:.0%})"
            )

        # 5. Buying power reserve
        bp_after = bp_available - proposed_bp
        min_reserve = limits.account_size * limits.min_buying_power_reserve_pct
        if bp_after < min_reserve:
            violations.append(
                f"Buying power after (${bp_after:.0f}) below reserve "
                f"${min_reserve:.0f} ({limits.min_buying_power_reserve_pct:.0%})"
            )

        # 6. Allowed structures
        st = trade_spec.structure_type or "unknown"
        if st not in limits.allowed_structures:
            violations.append(
                f"Structure '{st}' not in allowed list"
            )

        # 7. Sector concentration
        sector = limits.ticker_sectors.get(trade_spec.ticker, "other")
        sector_risk = defaultdict(float)
        for t in open_trades:
            s = limits.ticker_sectors.get(t.ticker, "other")
            sector_risk[s] += t.max_loss or 0
        sector_risk[sector] += proposed_risk
        max_sector = limits.account_size * limits.max_sector_concentration_pct
        if sector_risk[sector] > max_sector:
            violations.append(
                f"Sector '{sector}' risk ${sector_risk[sector]:.0f} "
                f"exceeds limit ${max_sector:.0f}"
            )

        # Warnings (non-blocking)
        if bp_after < limits.account_size * 0.30:
            warnings.append(
                f"Buying power will be below 30% (${bp_after:.0f})"
            )
        if ticker_count >= limits.max_per_ticker - 1 and ticker_count > 0:
            warnings.append(
                f"Already {ticker_count} position(s) in {trade_spec.ticker}"
            )
        portfolio_risk_pct = portfolio_risk_after / limits.account_size if limits.account_size > 0 else 0

        return RiskCheckResult(
            allowed=len(violations) == 0,
            violations=violations,
            warnings=warnings,
            available_capital=bp_available,
            buying_power_after=bp_after,
            portfolio_risk_after_pct=portfolio_risk_pct,
            position_count_after=open_count + 1,
            ticker_count_after=ticker_count + 1,
        )

    def get_status(self) -> PortfolioStatus:
        """Full portfolio snapshot — designed for dashboard display."""
        limits = self._limits
        open_trades = [t for t in self._trades if t.is_open]
        closed_trades = [t for t in self._trades if t.status in (TradeStatus.CLOSED, TradeStatus.EXPIRED)]

        total_risk = sum(t.max_loss or 0 for t in open_trades)
        bp_used = sum(t.buying_power_used for t in open_trades)
        bp_available = limits.account_size - bp_used
        reserve = limits.account_size * limits.min_buying_power_reserve_pct

        # P&L stats
        pnls = [t.realized_pnl for t in closed_trades if t.realized_pnl is not None]
        winners = [p for p in pnls if p > 0]
        losers = [p for p in pnls if p < 0]

        total_pnl = sum(pnls) if pnls else 0.0
        win_rate = len(winners) / len(pnls) if pnls else 0.0

        # Concentration
        tickers: dict[str, int] = defaultdict(int)
        sectors_risk: dict[str, float] = defaultdict(float)
        for t in open_trades:
            tickers[t.ticker] += 1
            sector = limits.ticker_sectors.get(t.ticker, "other")
            sectors_risk[sector] += t.max_loss or 0

        sector_pct = {
            s: v / limits.account_size if limits.account_size > 0 else 0
            for s, v in sectors_risk.items()
        }

        # Heat
        heat_pct = bp_used / limits.account_size if limits.account_size > 0 else 0
        if heat_pct < 0.50:
            heat = "cool"
        elif heat_pct < 0.75:
            heat = "warm"
        else:
            heat = "hot"

        return PortfolioStatus(
            account_size=limits.account_size,
            total_risk_deployed=total_risk,
            buying_power_used=bp_used,
            buying_power_available=bp_available,
            cash_reserve=reserve,
            open_positions=len(open_trades),
            max_positions=limits.max_positions,
            portfolio_risk_pct=total_risk / limits.account_size if limits.account_size > 0 else 0,
            total_realized_pnl=total_pnl,
            total_trades=len(closed_trades),
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=round(win_rate, 4),
            avg_winner=round(sum(winners) / len(winners), 2) if winners else 0.0,
            avg_loser=round(sum(losers) / len(losers), 2) if losers else 0.0,
            largest_winner=max(winners) if winners else 0.0,
            largest_loser=min(losers) if losers else 0.0,
            tickers_deployed=dict(tickers),
            sectors_deployed={s: round(v, 2) for s, v in sectors_risk.items()},
            sector_concentration_pct={s: round(v, 4) for s, v in sector_pct.items()},
            portfolio_heat=heat,
            heat_pct=round(heat_pct, 4),
        )

    def get_trade(self, trade_id: str) -> TradeRecord:
        """Get a single trade by ID."""
        return self._find_trade(trade_id)

    def list_trades(
        self,
        status: str | TradeStatus | None = None,
        ticker: str | None = None,
    ) -> list[TradeRecord]:
        """List trades with optional filters.

        Args:
            status: Filter by status ("open", "closed", "expired").
            ticker: Filter by ticker.
        """
        result = self._trades
        if status is not None:
            s = TradeStatus(status) if isinstance(status, str) else status
            result = [t for t in result if t.status == s]
        if ticker is not None:
            result = [t for t in result if t.ticker == ticker]
        return result

    def update_notes(self, trade_id: str, notes: str) -> TradeRecord:
        """Update notes on a trade."""
        record = self._find_trade(trade_id)
        record.notes = notes
        self._save_trades()
        return record

    def add_tag(self, trade_id: str, tag: str) -> TradeRecord:
        """Add a tag to a trade."""
        record = self._find_trade(trade_id)
        if tag not in record.tags:
            record.tags.append(tag)
            self._save_trades()
        return record

    def update_config(self, **kwargs) -> RiskLimits:
        """Update risk limit config. Pass any RiskLimits field as kwarg.

        Example::
            port.update_config(account_size=50000, max_positions=8)
        """
        data = self._limits.model_dump()
        data.update(kwargs)
        self._limits = RiskLimits(**data)
        self._save_config()
        return self._limits

    @property
    def limits(self) -> RiskLimits:
        """Current risk limits."""
        return self._limits

    # ── Internal ──

    def _find_trade(self, trade_id: str) -> TradeRecord:
        for t in self._trades:
            if t.trade_id == trade_id:
                return t
        raise ValueError(f"Trade not found: {trade_id}")

    def _generate_trade_id(self, trade_spec: TradeSpec) -> str:
        """Generate unique trade ID: TICKER-STRUCT-DATE-SEQ."""
        today = date.today().strftime("%Y%m%d")
        st = (trade_spec.structure_type or "trade").upper()[:4]
        # Abbreviate structure type
        abbrev = {
            "IRON": "IC", "CRED": "CS", "DEBI": "DS",
            "CALE": "CAL", "DIAG": "DG", "RATI": "RS",
            "LONG": "LO", "STRD": "STR", "STRA": "STR",
            "PMCC": "PMCC", "DOUB": "DCL", "IRON": "IC",
        }
        short = abbrev.get(st, st)

        # Find next sequence number
        prefix = f"{trade_spec.ticker}-{short}-{today}"
        existing = [t for t in self._trades if t.trade_id.startswith(prefix)]
        seq = len(existing) + 1

        return f"{prefix}-{seq:03d}"

    def _compute_buying_power(
        self, trade_spec: TradeSpec, entry_price: float, contracts: int,
    ) -> float:
        """Estimate buying power requirement."""
        # Defined risk: wing_width * 100 * contracts
        if trade_spec.wing_width_points and trade_spec.wing_width_points > 0:
            return trade_spec.wing_width_points * 100 * contracts
        # Debit trades: cost is the BP
        if trade_spec.order_side == "debit":
            return entry_price * 100 * contracts
        # Fallback: use entry_price * 100 * contracts * 5 (margin estimate)
        return entry_price * 100 * contracts * 5

    def _compute_max_loss(
        self, trade_spec: TradeSpec, entry_price: float, contracts: int,
    ) -> float:
        """Compute maximum loss for risk tracking."""
        if trade_spec.order_side == "credit" and trade_spec.wing_width_points:
            return (trade_spec.wing_width_points - entry_price) * 100 * contracts
        if trade_spec.order_side == "debit":
            return entry_price * 100 * contracts
        # Undefined risk fallback — flag it
        return entry_price * 100 * contracts * 5

    @staticmethod
    def _compute_pnl(record: TradeRecord, exit_price: float) -> float:
        """Compute realized P&L in dollars."""
        if record.order_side == "credit":
            # Collected credit, paying debit to close
            return (record.entry_price - exit_price) * 100 * record.contracts
        else:
            # Paid debit, receiving credit to close
            return (exit_price - record.entry_price) * 100 * record.contracts

    # ── YAML Persistence ──

    def _load_config(self) -> RiskLimits:
        if self._config_path.exists():
            with open(self._config_path) as f:
                data = yaml.safe_load(f) or {}
            return RiskLimits(**data)
        # Create default config
        limits = RiskLimits()
        self._limits = limits
        self._save_config()
        return limits

    def _save_config(self) -> None:
        with open(self._config_path, "w") as f:
            yaml.dump(
                self._limits.model_dump(mode="json"),
                f, default_flow_style=False, sort_keys=False,
            )

    def _load_trades(self) -> list[TradeRecord]:
        if not self._trades_path.exists():
            return []
        with open(self._trades_path) as f:
            data = yaml.safe_load(f)
        if not data or not isinstance(data, list):
            return []
        return [TradeRecord(**t) for t in data]

    def _save_trades(self) -> None:
        data = [t.model_dump(mode="json") for t in self._trades]
        with open(self._trades_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
