"""Crash sentinel: monitors market health and signals playbook phase transitions.

Pure function — takes regime results and metrics, returns SentinelReport.

Signal priority (highest to lowest):
    RED    — Crash active: trading disabled, or 3+ R4s, or 2+ R4s with high ATR
    ORANGE — Pre-crash: 1 R4 + 2 R2, or rising R4 prob with confirmed R4, or oversold
    BLUE   — Post-crash opportunity: IV rich with no R4s, or recovery pattern
    YELLOW — Elevated risk: single R4, rising R4 prob, or cautious env with high ATR
    GREEN  — Normal operations
"""
from __future__ import annotations

from datetime import datetime

from income_desk.models.sentinel import SentinelReport, SentinelSignal, SentinelTicker


def assess_crash_sentinel(
    regime_results: dict[str, dict],  # ticker -> {regime_id, confidence, r4_prob}
    iv_ranks: dict[str, float],       # ticker -> iv_rank (0-100)
    environment: str = "normal",      # From context.assess()
    trading_allowed: bool = True,
    position_size_factor: float = 1.0,
    spy_atr_pct: float = 1.0,
    spy_rsi: float = 50.0,
) -> SentinelReport:
    """Assess market health and return a SentinelReport.

    Args:
        regime_results: Per-ticker regime data. Each value must contain:
            - regime_id (int): 1–4
            - confidence (float): 0–1
            - r4_prob (float): probability of R4 state (0–1)
        iv_ranks: Per-ticker IV rank (0–100). Missing tickers simply excluded from avg.
        environment: Context environment label (e.g. "normal", "cautious", "risk_off").
        trading_allowed: False if black swan / circuit breaker has fired.
        position_size_factor: From context.assess() (0–1).
        spy_atr_pct: SPY ATR as % of price. Elevated > 2.0%.
        spy_rsi: SPY 14-day RSI. Deeply oversold < 30.

    Returns:
        SentinelReport with signal, reasons, actions, and playbook phase guidance.
    """
    # --- Build per-ticker summaries ---
    ticker_entries: list[SentinelTicker] = []
    r4_count = 0
    r2_count = 0
    r1_count = 0
    max_r4_prob = 0.0

    for ticker, data in regime_results.items():
        regime_id = int(data.get("regime_id", 1))
        confidence = float(data.get("confidence", 0.0))
        r4_prob = float(data.get("r4_prob", 0.0))
        iv_rank = iv_ranks.get(ticker)

        ticker_entries.append(SentinelTicker(
            ticker=ticker,
            regime_id=regime_id,
            regime_confidence=confidence,
            r4_probability=r4_prob,
            iv_rank=iv_rank,
        ))

        if regime_id == 4:
            r4_count += 1
        elif regime_id == 2:
            r2_count += 1
        elif regime_id == 1:
            r1_count += 1

        max_r4_prob = max(max_r4_prob, r4_prob)

    avg_iv_rank = (
        sum(iv_ranks.values()) / len(iv_ranks) if iv_ranks else 0.0
    )

    # Collect R4 ticker names for messages
    r4_tickers = [t for t, d in regime_results.items() if int(d.get("regime_id", 1)) == 4]

    # --- Determine signal level (priority order: RED > ORANGE > BLUE > YELLOW > GREEN) ---
    signal = SentinelSignal.GREEN
    reasons: list[str] = []
    actions: list[str] = []

    # RED: Crash active
    if not trading_allowed:
        signal = SentinelSignal.RED
        reasons.append("Black swan alert — trading disabled")
        actions.append("100% CASH. Do not trade. Wait for all-clear.")

    elif r4_count >= 3:
        signal = SentinelSignal.RED
        reasons.append(f"{r4_count}/{len(regime_results)} tickers in R4 — broad-based crash")
        actions.append("100% CASH. Close all positions immediately.")
        actions.append("Set alerts at SPY -10%/-15%/-20% from here.")

    elif r4_count >= 2 and spy_atr_pct > 2.0:
        signal = SentinelSignal.RED
        reasons.append(f"{r4_count} R4 tickers + SPY ATR {spy_atr_pct:.1f}% (elevated)")
        actions.append("Close all positions. Raise to 100% cash.")

    # ORANGE: Pre-crash warning
    elif r4_count >= 1 and r2_count >= 2:
        signal = SentinelSignal.ORANGE
        reasons.append(
            f"R4 on {r4_tickers}, R2 spreading ({r2_count} tickers)"
        )
        actions.append("Close any position with DTE > 30.")
        actions.append("Tighten ALL stops to 1.5x credit.")
        actions.append("No new entries. Prepare for Phase 1.")

    elif max_r4_prob > 0.30 and r4_count >= 1:
        signal = SentinelSignal.ORANGE
        reasons.append(
            f"R4 probability rising ({max_r4_prob:.0%} max) with {r4_count} confirmed R4"
        )
        actions.append("Reduce position count. Tighten stops.")

    elif r4_count >= 1 and spy_rsi < 30:
        signal = SentinelSignal.ORANGE
        reasons.append(f"R4 active + SPY RSI {spy_rsi:.0f} (deeply oversold)")
        actions.append("Close DTE > 21 positions. No new entries.")

    # BLUE: Post-crash opportunity
    elif r4_count == 0 and r2_count >= 2 and avg_iv_rank > 60:
        signal = SentinelSignal.BLUE
        reasons.append(
            f"No R4, {r2_count} R2 tickers, avg IV rank {avg_iv_rank:.0f}% — premiums rich"
        )
        actions.append("CRASH PLAYBOOK PHASE 2: Deploy per stabilization rules.")
        actions.append("Quarter Kelly, 3 max positions, 21 DTE, 3.0x stops.")
        actions.append("Uncorrelated tickers first (GLD, TLT before SPY).")

    elif r2_count >= 1 and r1_count >= 2 and avg_iv_rank > 45:
        signal = SentinelSignal.BLUE
        reasons.append(
            f"Recovery: {r1_count} R1 + {r2_count} R2, IV rank {avg_iv_rank:.0f}% still elevated"
        )
        actions.append("CRASH PLAYBOOK PHASE 3: Scale up deployment.")
        actions.append("Half Kelly, 5 positions, 25% risk budget.")
        actions.append("DTE optimizer for front-month theta advantage.")

    # YELLOW: Elevated risk
    elif r4_count == 1:
        signal = SentinelSignal.YELLOW
        r4_ticker = r4_tickers[0] if r4_tickers else "unknown"
        reasons.append(f"{r4_ticker} in R4 — contagion risk")
        actions.append(f"Avoid {r4_ticker}. Reduce correlated positions.")
        actions.append("Tighten stops on all positions to 2.0x max.")

    elif max_r4_prob > 0.20:
        signal = SentinelSignal.YELLOW
        reasons.append(f"R4 probability elevated ({max_r4_prob:.0%}) — regime transition possible")
        actions.append("No new positions on affected tickers.")

    elif spy_atr_pct > 2.0 and environment == "cautious":
        signal = SentinelSignal.YELLOW
        reasons.append(f"SPY ATR {spy_atr_pct:.1f}% elevated, market cautious")
        actions.append("Trade at 75% size. Shorter DTE (21 not 35).")

    # GREEN: Normal
    else:
        reasons.append("All systems normal")
        actions.append("Standard income trading operations.")

    # --- Determine playbook phase and sizing params ---
    if signal == SentinelSignal.RED:
        playbook_phase = "crash"
        sizing_params: dict = {"max_positions": 0}

    elif signal == SentinelSignal.ORANGE:
        playbook_phase = "pre_crash"
        sizing_params = {"max_positions": 0, "action": "close_all_dte_30+"}

    elif signal == SentinelSignal.BLUE:
        if r2_count >= 2:
            # Stabilization phase — most conservative BLUE
            playbook_phase = "stabilization"
            sizing_params = {
                "max_positions": 3,
                "max_risk_pct": 0.15,
                "safety_factor": 0.25,
                "drawdown_halt_pct": 0.05,
            }
        else:
            # Recovery phase — scaling back up
            playbook_phase = "recovery"
            sizing_params = {
                "max_positions": 5,
                "max_risk_pct": 0.25,
                "safety_factor": 0.50,
            }

    elif signal == SentinelSignal.YELLOW:
        playbook_phase = "elevated"
        sizing_params = {"max_risk_pct": 0.20}

    else:  # GREEN
        playbook_phase = "normal"
        sizing_params = {
            "max_positions": 5,
            "max_risk_pct": 0.25,
            "safety_factor": 0.50,
        }

    return SentinelReport(
        signal=signal,
        as_of=datetime.now(),
        reasons=reasons,
        actions=actions,
        tickers=ticker_entries,
        r4_count=r4_count,
        r2_count=r2_count,
        r1_count=r1_count,
        avg_iv_rank=avg_iv_rank,
        max_r4_probability=max_r4_prob,
        environment=environment,
        position_size_factor=position_size_factor,
        playbook_phase=playbook_phase,
        sizing_params=sizing_params,
    )
