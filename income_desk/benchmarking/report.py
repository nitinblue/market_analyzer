"""Report formatting — human-readable calibration output."""

from __future__ import annotations

from tabulate import tabulate

from income_desk.benchmarking.models import CalibrationReport


def format_calibration_report(report: CalibrationReport) -> str:
    """Format CalibrationReport as human-readable text with tables."""
    lines: list[str] = []

    # Header
    title = f"Calibration Report"
    if report.period:
        title += f" — {report.period}"
    lines.append(title)
    lines.append("=" * len(title))
    lines.append("")

    # Overall
    lines.append(f"Total trades: {report.total_trades}")
    if report.win_rate is not None:
        lines.append(f"Win rate:     {report.win_rate:.1%}")
    if report.avg_pnl is not None:
        lines.append(f"Avg P&L:      ${report.avg_pnl:,.2f}")
    lines.append("")

    # POP Calibration
    if report.pop_buckets:
        lines.append("POP Calibration")
        lines.append("-" * 40)
        pop_rows = []
        for b in report.pop_buckets:
            pop_rows.append([
                f"{b.predicted_low:.0f}-{b.predicted_high:.0f}%",
                f"{b.actual_win_rate:.1f}%",
                b.count,
                f"{b.error:+.1f}pp",
            ])
        lines.append(tabulate(
            pop_rows,
            headers=["Predicted POP", "Actual Win%", "Trades", "Error"],
            tablefmt="simple",
        ))
        if report.pop_rmse is not None:
            lines.append(f"\nPOP RMSE: {report.pop_rmse:.1f}pp")
        lines.append("")

    # Regime Accuracy
    if report.regime_accuracy:
        lines.append("Regime Persistence")
        lines.append("-" * 40)
        regime_rows = []
        for r in report.regime_accuracy:
            regime_rows.append([
                f"R{r.regime_id}",
                r.count,
                r.persisted_count,
                f"{r.persistence_rate:.0%}",
            ])
        lines.append(tabulate(
            regime_rows,
            headers=["Regime", "Trades", "Persisted", "Rate"],
            tablefmt="simple",
        ))
        if report.regime_persistence_rate is not None:
            lines.append(f"\nOverall persistence: {report.regime_persistence_rate:.0%}")
        lines.append("")

    # Score Correlation
    if report.score_win_correlation is not None or report.avg_score_winners is not None:
        lines.append("Score vs Outcome")
        lines.append("-" * 40)
        if report.score_win_correlation is not None:
            lines.append(f"Correlation:        {report.score_win_correlation:+.3f}")
        if report.avg_score_winners is not None:
            lines.append(f"Avg score (winners): {report.avg_score_winners:.2f}")
        if report.avg_score_losers is not None:
            lines.append(f"Avg score (losers):  {report.avg_score_losers:.2f}")
        lines.append("")

    # Summary
    if report.summary:
        lines.append(f"Summary: {report.summary}")

    return "\n".join(lines)
