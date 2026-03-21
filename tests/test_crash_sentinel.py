"""Tests for crash sentinel API.

Covers all signal transitions, playbook phases, and serialization.
"""
from __future__ import annotations

import pytest
from datetime import datetime

from market_analyzer.features.crash_sentinel import assess_crash_sentinel
from market_analyzer.models.sentinel import SentinelReport, SentinelSignal, SentinelTicker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _r(regime_id: int, confidence: float = 0.80, r4_prob: float = 0.05) -> dict:
    """Build a minimal regime_results entry."""
    return {"regime_id": regime_id, "confidence": confidence, "r4_prob": r4_prob}


def _all_r1(n: int = 5) -> dict[str, dict]:
    tickers = ["SPY", "QQQ", "IWM", "GLD", "TLT"][:n]
    return {t: _r(1) for t in tickers}


# ---------------------------------------------------------------------------
# GREEN signal tests
# ---------------------------------------------------------------------------

def test_all_r1_green():
    report = assess_crash_sentinel(
        regime_results=_all_r1(),
        iv_ranks={"SPY": 25.0, "QQQ": 22.0, "IWM": 20.0, "GLD": 18.0, "TLT": 15.0},
    )
    assert report.signal == SentinelSignal.GREEN
    assert report.r4_count == 0
    assert report.playbook_phase == "normal"
    assert report.sizing_params["max_positions"] == 5
    assert "Standard income" in report.actions[0]


def test_green_no_iv_ranks():
    """GREEN with no IV rank data available."""
    report = assess_crash_sentinel(
        regime_results=_all_r1(),
        iv_ranks={},
    )
    assert report.signal == SentinelSignal.GREEN
    assert report.avg_iv_rank == 0.0


# ---------------------------------------------------------------------------
# YELLOW signal tests
# ---------------------------------------------------------------------------

def test_one_r4_yellow():
    """YELLOW with single R4 ticker but low R4 probability (just entered R4, not escalating).

    r4_prob is set low (0.28) to stay below the 0.30 ORANGE threshold.
    Only 1 R2 ticker (below the 2 R2 required for ORANGE).
    No RSI extreme. Result: YELLOW (single R4, contagion risk).
    """
    regimes = {
        "SPY": _r(1),
        "QQQ": _r(1),
        "IWM": _r(4, confidence=0.70, r4_prob=0.28),  # R4 but prob below ORANGE threshold
        "GLD": _r(1),
        "TLT": _r(2),  # Only 1 R2 — not enough for ORANGE
    }
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks={"SPY": 25.0, "QQQ": 22.0},
        spy_rsi=50.0,  # Not oversold
    )
    assert report.signal == SentinelSignal.YELLOW
    assert report.r4_count == 1
    assert report.playbook_phase == "elevated"
    assert report.sizing_params == {"max_risk_pct": 0.20}
    assert "IWM" in report.reasons[0]
    assert "contagion" in report.reasons[0]


def test_r4_prob_elevated_yellow():
    """YELLOW from high R4 probability even without confirmed R4."""
    regimes = {
        "SPY": _r(1, r4_prob=0.25),
        "QQQ": _r(2, r4_prob=0.22),
        "IWM": _r(1),
        "GLD": _r(1),
        "TLT": _r(1),
    }
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks={},
        spy_atr_pct=1.5,
    )
    assert report.signal == SentinelSignal.YELLOW
    assert report.max_r4_probability > 0.20
    assert "R4 probability elevated" in report.reasons[0]


def test_cautious_env_high_atr_yellow():
    """YELLOW from cautious environment with elevated ATR."""
    report = assess_crash_sentinel(
        regime_results=_all_r1(),
        iv_ranks={},
        environment="cautious",
        spy_atr_pct=2.5,
    )
    assert report.signal == SentinelSignal.YELLOW
    assert "cautious" in report.reasons[0]


# ---------------------------------------------------------------------------
# ORANGE signal tests
# ---------------------------------------------------------------------------

def test_r4_plus_two_r2_orange():
    regimes = {
        "SPY": _r(4, r4_prob=0.75),
        "QQQ": _r(2),
        "IWM": _r(2),
        "GLD": _r(1),
        "TLT": _r(1),
    }
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks={"SPY": 60.0, "QQQ": 55.0},
    )
    assert report.signal == SentinelSignal.ORANGE
    assert report.r4_count == 1
    assert report.r2_count == 2
    assert report.playbook_phase == "pre_crash"
    assert report.sizing_params["action"] == "close_all_dte_30+"
    assert report.sizing_params["max_positions"] == 0


def test_r4_prob_rising_orange():
    """ORANGE when R4 prob > 30% with at least 1 confirmed R4."""
    regimes = {
        "SPY": _r(4, r4_prob=0.80),
        "QQQ": _r(1, r4_prob=0.35),  # r4_prob high but not confirmed
        "IWM": _r(1),
        "GLD": _r(1),
        "TLT": _r(1),
    }
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks={},
    )
    assert report.signal == SentinelSignal.ORANGE
    assert report.max_r4_probability > 0.30
    assert "probability rising" in report.reasons[0]


def test_spy_rsi_extreme_with_r4_orange():
    """ORANGE when R4 present and SPY RSI deeply oversold.

    r4_prob is set below 0.30 so the 'probability rising' ORANGE check does not fire first.
    That allows the RSI-based ORANGE check to be the determining condition.
    """
    regimes = {
        "SPY": _r(4, r4_prob=0.28),  # R4 confirmed, but prob below 0.30 threshold
        "QQQ": _r(1),
        "IWM": _r(1),
        "GLD": _r(1),
        "TLT": _r(1),
    }
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks={},
        spy_rsi=25.0,  # < 30 — deeply oversold
    )
    assert report.signal == SentinelSignal.ORANGE
    assert "RSI" in report.reasons[0]
    assert "oversold" in report.reasons[0]


# ---------------------------------------------------------------------------
# RED signal tests
# ---------------------------------------------------------------------------

def test_three_r4_red():
    regimes = {
        "SPY": _r(4, r4_prob=0.85),
        "QQQ": _r(4, r4_prob=0.80),
        "IWM": _r(4, r4_prob=0.75),
        "GLD": _r(2),
        "TLT": _r(2),
    }
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks={},
    )
    assert report.signal == SentinelSignal.RED
    assert report.r4_count == 3
    assert report.playbook_phase == "crash"
    assert report.sizing_params == {"max_positions": 0}
    assert "100% CASH" in report.actions[0]


def test_trading_disabled_red():
    """RED immediately when trading_allowed=False (black swan circuit breaker)."""
    report = assess_crash_sentinel(
        regime_results=_all_r1(),
        iv_ranks={},
        trading_allowed=False,
    )
    assert report.signal == SentinelSignal.RED
    assert "black swan" in report.reasons[0].lower()
    assert report.playbook_phase == "crash"


def test_two_r4_high_atr_red():
    """RED with 2 R4 tickers AND high SPY ATR."""
    regimes = {
        "SPY": _r(4, r4_prob=0.85),
        "QQQ": _r(4, r4_prob=0.80),
        "IWM": _r(2),
        "GLD": _r(1),
        "TLT": _r(1),
    }
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks={},
        spy_atr_pct=2.5,  # > 2.0 threshold
    )
    assert report.signal == SentinelSignal.RED
    assert "ATR" in report.reasons[0]


# ---------------------------------------------------------------------------
# BLUE signal tests
# ---------------------------------------------------------------------------

def test_no_r4_high_iv_r2_blue():
    """BLUE (stabilization): no R4, 2+ R2, avg IV rank > 60."""
    regimes = {
        "SPY": _r(2, r4_prob=0.05),
        "QQQ": _r(2, r4_prob=0.05),
        "IWM": _r(1),
        "GLD": _r(1),
        "TLT": _r(1),
    }
    iv_ranks = {"SPY": 75.0, "QQQ": 70.0, "IWM": 65.0, "GLD": 60.0, "TLT": 55.0}
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks=iv_ranks,
    )
    assert report.signal == SentinelSignal.BLUE
    assert report.r4_count == 0
    assert report.r2_count == 2
    assert report.avg_iv_rank > 60
    assert report.playbook_phase == "stabilization"


def test_recovery_r1_plus_r2_elevated_iv_blue():
    """BLUE (recovery): 2+ R1, 1+ R2, avg IV rank > 45."""
    regimes = {
        "SPY": _r(1, r4_prob=0.03),
        "QQQ": _r(1, r4_prob=0.03),
        "IWM": _r(1, r4_prob=0.03),
        "GLD": _r(2, r4_prob=0.05),
        "TLT": _r(1, r4_prob=0.03),
    }
    iv_ranks = {"SPY": 55.0, "QQQ": 50.0, "IWM": 48.0, "GLD": 52.0, "TLT": 45.0}
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks=iv_ranks,
    )
    assert report.signal == SentinelSignal.BLUE
    assert report.r4_count == 0
    assert report.r1_count >= 2
    assert report.r2_count >= 1
    assert report.avg_iv_rank > 45
    assert report.playbook_phase == "recovery"


# ---------------------------------------------------------------------------
# Playbook phase sizing tests
# ---------------------------------------------------------------------------

def test_playbook_phase_stabilization_sizing():
    """Stabilization phase must have quarter-Kelly sizing params."""
    regimes = {
        "SPY": _r(2),
        "QQQ": _r(2),
        "IWM": _r(1),
        "GLD": _r(1),
        "TLT": _r(1),
    }
    iv_ranks = {"SPY": 72.0, "QQQ": 68.0, "IWM": 65.0}
    report = assess_crash_sentinel(regime_results=regimes, iv_ranks=iv_ranks)

    assert report.signal == SentinelSignal.BLUE
    assert report.playbook_phase == "stabilization"
    assert report.sizing_params["max_positions"] == 3
    assert report.sizing_params["max_risk_pct"] == 0.15
    assert report.sizing_params["safety_factor"] == 0.25
    assert report.sizing_params["drawdown_halt_pct"] == 0.05


def test_playbook_phase_crash_zero_positions():
    """Crash phase must result in zero allowed positions."""
    regimes = {
        "SPY": _r(4),
        "QQQ": _r(4),
        "IWM": _r(4),
        "GLD": _r(2),
        "TLT": _r(2),
    }
    report = assess_crash_sentinel(regime_results=regimes, iv_ranks={})

    assert report.signal == SentinelSignal.RED
    assert report.playbook_phase == "crash"
    assert report.sizing_params["max_positions"] == 0


def test_playbook_phase_normal_full_sizing():
    """Normal (GREEN) phase must allow full sizing."""
    report = assess_crash_sentinel(
        regime_results=_all_r1(),
        iv_ranks={"SPY": 30.0},
    )
    assert report.playbook_phase == "normal"
    assert report.sizing_params["max_positions"] == 5
    assert report.sizing_params["max_risk_pct"] == 0.25
    assert report.sizing_params["safety_factor"] == 0.50


def test_playbook_phase_recovery_sizing():
    """Recovery phase must have half-Kelly sizing."""
    regimes = {
        "SPY": _r(1),
        "QQQ": _r(1),
        "IWM": _r(1),
        "GLD": _r(2),
        "TLT": _r(1),
    }
    iv_ranks = {"SPY": 55.0, "QQQ": 50.0, "IWM": 48.0, "GLD": 52.0, "TLT": 46.0}
    report = assess_crash_sentinel(regime_results=regimes, iv_ranks=iv_ranks)

    assert report.playbook_phase == "recovery"
    assert report.sizing_params["max_positions"] == 5
    assert report.sizing_params["max_risk_pct"] == 0.25
    assert report.sizing_params["safety_factor"] == 0.50


# ---------------------------------------------------------------------------
# Serialization test (for eTrading API consumption)
# ---------------------------------------------------------------------------

def test_serialization_for_etrading():
    """SentinelReport must serialize cleanly for eTrading JSON consumption."""
    regimes = {
        "SPY": _r(4, r4_prob=0.80),
        "QQQ": _r(2, r4_prob=0.15),
        "IWM": _r(2, r4_prob=0.10),
        "GLD": _r(1),
        "TLT": _r(1),
    }
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks={"SPY": 65.0, "QQQ": 60.0},
        environment="risk_off",
        position_size_factor=0.5,
        spy_atr_pct=1.8,
        spy_rsi=32.0,
    )

    # Must be a valid SentinelReport
    assert isinstance(report, SentinelReport)

    # Serialize to dict (eTrading JSON payload)
    data = report.model_dump()

    # All required fields present
    assert "signal" in data
    assert "as_of" in data
    assert "reasons" in data
    assert "actions" in data
    assert "tickers" in data
    assert "r4_count" in data
    assert "r2_count" in data
    assert "r1_count" in data
    assert "avg_iv_rank" in data
    assert "max_r4_probability" in data
    assert "environment" in data
    assert "position_size_factor" in data
    assert "playbook_phase" in data
    assert "sizing_params" in data

    # Signal is string-serializable
    assert data["signal"] in ("green", "yellow", "orange", "red", "blue")

    # Tickers is a list of dicts
    assert isinstance(data["tickers"], list)
    for t in data["tickers"]:
        assert "ticker" in t
        assert "regime_id" in t
        assert "regime_confidence" in t
        assert "r4_probability" in t
        assert "iv_rank" in t

    # Reconstruct from dict
    rebuilt = SentinelReport.model_validate(data)
    assert rebuilt.signal == report.signal
    assert rebuilt.playbook_phase == report.playbook_phase

    # environment and size_factor passed through correctly
    assert data["environment"] == "risk_off"
    assert data["position_size_factor"] == 0.5


def test_ticker_entries_populated():
    """All tickers from regime_results must appear in report.tickers."""
    tickers = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
    regimes = {t: _r(1) for t in tickers}
    iv_ranks = {"SPY": 30.0, "QQQ": 28.0}  # Only partial IV data

    report = assess_crash_sentinel(regime_results=regimes, iv_ranks=iv_ranks)

    assert len(report.tickers) == 5
    reported_tickers = {entry.ticker for entry in report.tickers}
    assert reported_tickers == set(tickers)

    # IV rank None for tickers without data
    spy_entry = next(e for e in report.tickers if e.ticker == "SPY")
    assert spy_entry.iv_rank == 30.0

    iwm_entry = next(e for e in report.tickers if e.ticker == "IWM")
    assert iwm_entry.iv_rank is None


def test_empty_regime_results_green():
    """Empty regime_results with no data should return GREEN (nothing alarming)."""
    report = assess_crash_sentinel(regime_results={}, iv_ranks={})
    assert report.signal == SentinelSignal.GREEN
    assert report.r4_count == 0
    assert report.tickers == []


def test_signal_priority_red_over_orange():
    """RED takes priority: trading_allowed=False overrides any ORANGE conditions."""
    regimes = {
        "SPY": _r(4, r4_prob=0.80),
        "QQQ": _r(2),
        "IWM": _r(2),
        "GLD": _r(1),
        "TLT": _r(1),
    }
    # ORANGE conditions met, but trading_allowed=False should give RED
    report = assess_crash_sentinel(
        regime_results=regimes,
        iv_ranks={},
        trading_allowed=False,
    )
    assert report.signal == SentinelSignal.RED
    assert report.playbook_phase == "crash"
