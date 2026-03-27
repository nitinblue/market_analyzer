"""Self-contained HTML report generator for release readiness.

Produces a single HTML file (no external dependencies) that renders the
ReadinessReport as an interactive dashboard with:
- Overall GO/NO-GO verdict banner
- Per-stage pass/fail cards with timing
- API replay manifest per call (collapsible input/output JSON)
- Invariant check details
- Gaps and improvements summary

Usage::

    from income_desk.regression.release_readiness import run_release_readiness
    from income_desk.regression.readiness_report import write_html, write_manifest

    report = run_release_readiness()
    write_html(report, "release_readiness.html")
    write_manifest(report, "release_readiness_manifest.json")
"""

from __future__ import annotations

import json
from pathlib import Path

from income_desk.regression.release_readiness import ReadinessReport, StageVerdict


def _verdict_color(verdict: str) -> str:
    colors = {
        "GO": "#22c55e",
        "CONDITIONAL-GO": "#eab308",
        "NO-GO": "#ef4444",
        "PASS": "#22c55e",
        "FAIL": "#ef4444",
        "WARN": "#eab308",
        "SKIP": "#6b7280",
    }
    return colors.get(verdict, "#6b7280")


def _verdict_emoji(verdict: str) -> str:
    emojis = {
        "GO": "&#x2705;",
        "CONDITIONAL-GO": "&#x26A0;",
        "NO-GO": "&#x274C;",
        "PASS": "&#x2705;",
        "FAIL": "&#x274C;",
        "WARN": "&#x26A0;",
        "SKIP": "&#x23ED;",
    }
    return emojis.get(verdict, "")


def _render_api_call(call, idx: int) -> str:
    """Render a single API call as an HTML collapsible section."""
    status = "PASS" if not call.error and all(call.invariants_passed) else "FAIL"
    if call.error:
        status = "ERROR"

    color = _verdict_color(status)
    inv_summary = ""
    if call.invariants_checked:
        passed = sum(call.invariants_passed)
        total = len(call.invariants_checked)
        inv_summary = f" &mdash; {passed}/{total} invariants"

    error_html = ""
    if call.error:
        error_html = f'<div class="error-box">{call.error}</div>'

    invariant_rows = ""
    for desc, passed in zip(call.invariants_checked, call.invariants_passed):
        icon = "&#x2705;" if passed else "&#x274C;"
        invariant_rows += f"<tr><td>{icon}</td><td>{desc}</td></tr>\n"

    inputs_json = json.dumps(call.inputs, indent=2, default=str) if call.inputs else "{}"
    outputs_json = json.dumps(call.outputs, indent=2, default=str) if call.outputs else "null"

    return f"""
    <details class="api-call">
        <summary style="border-left: 4px solid {color};">
            <span class="api-name">{call.api}</span>
            <span class="api-module">{call.module}</span>
            <span class="api-timing">{call.duration_ms:.0f}ms</span>
            <span class="api-status" style="color:{color};">{status}{inv_summary}</span>
        </summary>
        <div class="api-body">
            {error_html}
            <div class="invariants">
                <h4>Invariant Checks</h4>
                <table>{invariant_rows}</table>
            </div>
            <div class="replay-section">
                <h4>API Replay (eTrading Verification)</h4>
                <div class="code-tabs">
                    <div class="tab-content">
                        <h5>Inputs</h5>
                        <pre class="json">{inputs_json}</pre>
                        <h5>Outputs ({call.output_type})</h5>
                        <pre class="json">{outputs_json}</pre>
                    </div>
                </div>
            </div>
        </div>
    </details>
    """


def _render_stage(stage) -> str:
    """Render a workflow stage as an HTML card."""
    verdict = stage.verdict.value if hasattr(stage.verdict, "value") else stage.verdict
    color = _verdict_color(verdict)
    emoji = _verdict_emoji(verdict)

    api_calls_html = "\n".join(
        _render_api_call(c, i) for i, c in enumerate(stage.api_calls)
    )

    notes_html = ""
    if stage.notes:
        notes_html = "<div class='stage-notes'>" + "<br>".join(stage.notes) + "</div>"

    error_html = ""
    if stage.error:
        error_html = f'<div class="error-box">{stage.error}</div>'

    return f"""
    <div class="stage-card" style="border-top: 4px solid {color};">
        <div class="stage-header">
            <div class="stage-title">
                <span class="stage-number">{stage.stage_number}</span>
                <span class="stage-name">{stage.stage}</span>
                <span class="stage-verdict" style="background:{color};">{emoji} {verdict}</span>
            </div>
            <div class="stage-meta">
                <span>{stage.description}</span>
                <span class="stage-timing">{stage.duration_ms:.0f}ms</span>
                <span>{len(stage.api_calls)} APIs | {stage.total_invariants} checks | {stage.passed_invariants} passed</span>
            </div>
        </div>
        {error_html}
        {notes_html}
        <div class="api-calls">
            {api_calls_html}
        </div>
    </div>
    """


def generate_html(report: ReadinessReport) -> str:
    """Generate complete self-contained HTML report."""
    verdict_color = _verdict_color(report.overall_verdict)
    verdict_emoji = _verdict_emoji(report.overall_verdict)

    pass_rate = (
        f"{report.passed_invariants}/{report.total_invariants} "
        f"({report.passed_invariants / report.total_invariants * 100:.1f}%)"
        if report.total_invariants > 0
        else "0/0"
    )

    stages_html = "\n".join(_render_stage(s) for s in report.stages)

    # Regression pipeline results
    regression_html = ""
    if report.regression_result:
        regression_json = json.dumps(report.regression_result, indent=2, default=str)
        reg_verdict = report.regression_result.get("verdict", "unknown") if isinstance(report.regression_result, dict) else "unknown"
        reg_color = _verdict_color("PASS" if reg_verdict == "GREEN" else "FAIL")
        regression_html = f"""
        <div class="stage-card" style="border-top: 4px solid {reg_color};">
            <div class="stage-header">
                <div class="stage-title">
                    <span class="stage-number">R</span>
                    <span class="stage-name">REGRESSION PIPELINE</span>
                    <span class="stage-verdict" style="background:{reg_color};">{reg_verdict}</span>
                </div>
                <div class="stage-meta">Existing regression validation (8 domains)</div>
            </div>
            <details class="api-call">
                <summary>Full regression results</summary>
                <pre class="json">{regression_json}</pre>
            </details>
        </div>
        """

    # Gaps
    gaps_html = ""
    if report.gaps_found:
        gap_items = "\n".join(f"<li>{g}</li>" for g in report.gaps_found)
        gaps_html = f"""
        <div class="gaps-section">
            <h2>Gaps Found ({len(report.gaps_found)})</h2>
            <ul>{gap_items}</ul>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>income_desk Release Readiness — {report.run_date}</title>
<style>
    :root {{
        --bg: #0f172a; --surface: #1e293b; --surface2: #334155;
        --text: #e2e8f0; --text-dim: #94a3b8; --accent: #3b82f6;
        --green: #22c55e; --red: #ef4444; --yellow: #eab308;
    }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
        background: var(--bg); color: var(--text);
        line-height: 1.6; padding: 20px;
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}

    /* Header */
    .header {{
        text-align: center; padding: 30px 20px;
        background: var(--surface); border-radius: 12px;
        margin-bottom: 24px;
    }}
    .header h1 {{ font-size: 1.8rem; margin-bottom: 8px; }}
    .header .subtitle {{ color: var(--text-dim); font-size: 0.9rem; }}
    .verdict-banner {{
        display: inline-block; padding: 12px 40px; margin: 16px 0;
        font-size: 2rem; font-weight: 700; border-radius: 8px;
        background: {verdict_color}20; color: {verdict_color};
        border: 2px solid {verdict_color};
    }}
    .summary-stats {{
        display: flex; justify-content: center; gap: 40px;
        margin-top: 16px; flex-wrap: wrap;
    }}
    .stat {{ text-align: center; }}
    .stat .value {{ font-size: 1.4rem; font-weight: 700; }}
    .stat .label {{ font-size: 0.8rem; color: var(--text-dim); }}

    /* Stage cards */
    .stage-card {{
        background: var(--surface); border-radius: 8px;
        margin-bottom: 16px; overflow: hidden;
    }}
    .stage-header {{ padding: 16px 20px; }}
    .stage-title {{
        display: flex; align-items: center; gap: 12px;
        margin-bottom: 6px;
    }}
    .stage-number {{
        display: inline-flex; align-items: center; justify-content: center;
        width: 28px; height: 28px; border-radius: 50%;
        background: var(--accent); color: white; font-weight: 700;
        font-size: 0.85rem;
    }}
    .stage-name {{ font-size: 1.1rem; font-weight: 600; }}
    .stage-verdict {{
        padding: 2px 12px; border-radius: 4px; font-size: 0.8rem;
        font-weight: 600; color: white;
    }}
    .stage-meta {{ font-size: 0.8rem; color: var(--text-dim); display: flex; gap: 16px; flex-wrap: wrap; }}
    .stage-timing {{ color: var(--accent); }}

    /* API calls */
    .api-calls {{ padding: 0 20px 16px; }}
    .api-call {{ margin-bottom: 8px; }}
    .api-call summary {{
        padding: 8px 12px; background: var(--surface2); border-radius: 6px;
        cursor: pointer; display: flex; align-items: center; gap: 12px;
        font-size: 0.85rem; list-style: none;
    }}
    .api-call summary::-webkit-details-marker {{ display: none; }}
    .api-call summary::before {{
        content: '\\25B6'; font-size: 0.7rem; transition: transform 0.2s;
    }}
    .api-call[open] summary::before {{ transform: rotate(90deg); }}
    .api-name {{ font-weight: 600; font-family: 'Consolas', monospace; }}
    .api-module {{ color: var(--text-dim); font-size: 0.75rem; }}
    .api-timing {{ color: var(--accent); margin-left: auto; }}
    .api-status {{ font-weight: 600; font-size: 0.8rem; }}
    .api-body {{ padding: 12px 16px; background: var(--bg); border-radius: 0 0 6px 6px; }}

    /* Invariants table */
    .invariants table {{ width: 100%; border-collapse: collapse; margin: 8px 0; }}
    .invariants td {{ padding: 4px 8px; font-size: 0.8rem; border-bottom: 1px solid var(--surface2); }}
    .invariants h4 {{ font-size: 0.85rem; color: var(--accent); margin-bottom: 4px; }}

    /* Replay */
    .replay-section {{ margin-top: 12px; }}
    .replay-section h4 {{ font-size: 0.85rem; color: var(--accent); margin-bottom: 4px; }}
    .replay-section h5 {{ font-size: 0.75rem; color: var(--text-dim); margin: 8px 0 4px; }}
    pre.json {{
        background: var(--surface); padding: 12px; border-radius: 6px;
        font-size: 0.75rem; overflow-x: auto; max-height: 300px;
        white-space: pre-wrap; word-break: break-all;
    }}

    /* Error */
    .error-box {{
        background: #ef444420; border: 1px solid #ef4444;
        border-radius: 6px; padding: 8px 12px; margin: 8px 0;
        font-size: 0.8rem; color: #fca5a5;
    }}

    /* Gaps */
    .gaps-section {{
        background: var(--surface); border-radius: 8px;
        padding: 20px; margin-top: 16px;
    }}
    .gaps-section h2 {{ font-size: 1.1rem; margin-bottom: 12px; color: var(--red); }}
    .gaps-section ul {{ padding-left: 20px; }}
    .gaps-section li {{ font-size: 0.85rem; margin-bottom: 4px; color: var(--text-dim); }}

    /* Stage notes */
    .stage-notes {{ padding: 8px 20px; font-size: 0.8rem; color: var(--text-dim); }}

    /* Footer */
    .footer {{
        text-align: center; padding: 20px; margin-top: 24px;
        font-size: 0.75rem; color: var(--text-dim);
    }}

    @media (max-width: 768px) {{
        .summary-stats {{ gap: 20px; }}
        .stage-meta {{ flex-direction: column; gap: 4px; }}
    }}
</style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>income_desk Release Readiness</h1>
        <div class="subtitle">v{report.version} &bull; {report.run_date} &bull; Markets: {', '.join(report.markets_tested)}</div>
        <div class="verdict-banner">{verdict_emoji} {report.overall_verdict}</div>
        <div class="summary-stats">
            <div class="stat">
                <div class="value">{report.total_apis_tested}</div>
                <div class="label">APIs Tested</div>
            </div>
            <div class="stat">
                <div class="value">{pass_rate}</div>
                <div class="label">Invariants Passed</div>
            </div>
            <div class="stat">
                <div class="value">{report.duration_ms:.0f}ms</div>
                <div class="label">Total Duration</div>
            </div>
            <div class="stat">
                <div class="value">{len([s for s in report.stages if s.verdict.value == 'PASS'])}/{len(report.stages)}</div>
                <div class="label">Stages Passed</div>
            </div>
        </div>
    </div>

    <h2 style="margin: 20px 0 12px; font-size: 1.2rem;">Trading Workflow Validation</h2>
    {stages_html}
    {regression_html}
    {gaps_html}

    <div class="footer">
        Generated by income_desk release readiness &bull; {report.run_at}<br>
        API replay manifests included — eTrading can call each API with the shown inputs and verify outputs match.
    </div>
</div>
</body>
</html>"""


def write_html(report: ReadinessReport, path: str | Path) -> Path:
    """Write HTML report to file."""
    p = Path(path)
    p.write_text(generate_html(report), encoding="utf-8")
    return p


def write_manifest(report: ReadinessReport, path: str | Path) -> Path:
    """Write JSON API replay manifest for eTrading verification.

    Each entry contains the API name, module, exact inputs, expected outputs,
    and invariant checks. eTrading can replay each call and compare outputs.
    """
    manifest = {
        "version": report.version,
        "run_date": report.run_date,
        "overall_verdict": report.overall_verdict,
        "total_apis": report.total_apis_tested,
        "stages": [],
    }

    for stage in report.stages:
        stage_entry = {
            "stage": stage.stage,
            "stage_number": stage.stage_number,
            "verdict": stage.verdict.value if hasattr(stage.verdict, "value") else stage.verdict,
            "api_calls": [],
        }
        for call in stage.api_calls:
            stage_entry["api_calls"].append({
                "api": call.api,
                "module": call.module,
                "inputs": call.inputs,
                "outputs": call.outputs,
                "output_type": call.output_type,
                "invariants_checked": call.invariants_checked,
                "invariants_passed": call.invariants_passed,
                "duration_ms": call.duration_ms,
                "error": call.error,
            })
        manifest["stages"].append(stage_entry)

    p = Path(path)
    p.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return p
