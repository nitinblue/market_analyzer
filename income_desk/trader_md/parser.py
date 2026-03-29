from __future__ import annotations
import re
from pathlib import Path

import yaml

from income_desk.trader_md.models import (
    Gate,
    Step,
    Phase,
    WorkflowPlan,
    BrokerProfile,
    UniverseSpec,
    RiskProfile,
)


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split YAML frontmatter from body. Returns (meta_dict, body_text)."""
    m = re.match(r"^---\s*\n(.*?\n)---\s*\n?(.*)", text, re.DOTALL)
    if not m:
        return {}, text
    meta = yaml.safe_load(m.group(1)) or {}
    return meta, m.group(2)


def parse_workflow(path: Path) -> WorkflowPlan:
    """Parse a .workflow.md file into a WorkflowPlan."""
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)

    plan = WorkflowPlan(
        name=meta.get("name", path.stem),
        description=meta.get("description", ""),
        broker_ref=meta.get("broker", "simulated"),
        universe_ref=meta.get("universe", ""),
        risk_ref=meta.get("risk_profile", "moderate"),
    )

    current_phase: Phase | None = None
    current_step: Step | None = None
    current_block: str | None = None  # "inputs", "outputs", "gate"

    for line in body.splitlines():
        stripped = line.strip()

        # Phase header: ## Phase N: Name
        phase_m = re.match(r"^##\s+Phase\s+(\d+):\s*(.+)", stripped)
        if phase_m:
            # Finalize previous step
            if current_step and current_phase:
                current_phase.steps.append(current_step)
                current_step = None
            current_block = None
            current_phase = Phase(name=phase_m.group(2).strip(), number=int(phase_m.group(1)))
            plan.phases.append(current_phase)
            continue

        # Step header: ### Step: Name
        step_m = re.match(r"^###\s+Step:\s*(.+)", stripped)
        if step_m:
            if current_step and current_phase:
                current_phase.steps.append(current_step)
            current_block = None
            current_step = Step(name=step_m.group(1).strip(), workflow="")
            continue

        # Phase-level attributes
        if current_phase and not current_step:
            rp_m = re.match(r"^requires_positions:\s*(true|false)", stripped, re.IGNORECASE)
            if rp_m:
                current_phase.requires_positions = rp_m.group(1).lower() == "true"
                continue

        # Step-level attributes
        if current_step:
            # workflow:
            wf_m = re.match(r"^workflow:\s*(.+)", stripped)
            if wf_m:
                current_step.workflow = wf_m.group(1).strip()
                current_block = None
                continue

            # requires:
            req_m = re.match(r"^requires:\s*(.+)", stripped)
            if req_m:
                current_step.requires = req_m.group(1).strip()
                current_block = None
                continue

            # on_simulated:
            os_m = re.match(r"^on_simulated:\s*(.+)", stripped)
            if os_m:
                current_step.on_simulated = os_m.group(1).strip()
                current_block = None
                continue

            # Block starters
            if stripped == "inputs:":
                current_block = "inputs"
                continue
            if stripped == "outputs:":
                current_block = "outputs"
                continue
            if stripped == "gate:":
                current_block = "gate"
                continue

            # on_fail applies to all gates in this step
            of_m = re.match(r'^on_fail:\s*(\w+)\s*"(.*)"', stripped)
            if of_m:
                action, msg = of_m.group(1), of_m.group(2)
                for g in current_step.gates:
                    g.on_fail = action
                    g.message = msg
                current_block = None
                continue

            # Block content
            if current_block == "inputs":
                kv_m = re.match(r"^(\w+):\s*(.+)", stripped)
                if kv_m:
                    current_step.inputs[kv_m.group(1)] = kv_m.group(2).strip()
                    continue

            if current_block == "outputs":
                kv_m = re.match(r"^(\w+):\s*(.+)", stripped)
                if kv_m:
                    current_step.outputs[kv_m.group(1)] = kv_m.group(2).strip()
                    continue

            if current_block == "gate":
                gate_m = re.match(r"^-\s+(.+)", stripped)
                if gate_m:
                    current_step.gates.append(
                        Gate(expression=gate_m.group(1).strip(), on_fail="HALT", message="")
                    )
                    continue

    # Finalize last step/phase
    if current_step and current_phase:
        current_phase.steps.append(current_step)

    return plan


def parse_broker(path: Path) -> BrokerProfile:
    """Parse a .broker.md file into a BrokerProfile."""
    text = path.read_text(encoding="utf-8")
    meta, _ = _split_frontmatter(text)
    return BrokerProfile(
        name=meta.get("name", path.stem),
        broker_type=meta.get("broker_type", "simulated"),
        mode=meta.get("mode", "live"),
        market=meta.get("market", "US"),
        currency=meta.get("currency", "USD"),
        credentials_source=meta.get("credentials", ".env.trading"),
        fallback=meta.get("fallback", "simulated"),
    )


def parse_universe(path: Path) -> UniverseSpec:
    """Parse a .universe.md file into a UniverseSpec."""
    text = path.read_text(encoding="utf-8")
    meta, body = _split_frontmatter(text)

    tickers: list[str] = []

    # Tickers from frontmatter
    fm_tickers = meta.get("tickers", [])
    if isinstance(fm_tickers, list):
        tickers.extend(str(t).strip() for t in fm_tickers)

    # Tickers from body bullet points: - TICKER  or  - TICKER # comment
    for line in body.splitlines():
        m = re.match(r"^\s*-\s+([A-Z][A-Z0-9.]*)", line)
        if m:
            tickers.append(m.group(1))

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return UniverseSpec(
        name=meta.get("name", path.stem),
        market=meta.get("market", "US"),
        description=meta.get("description", ""),
        tickers=unique,
    )


def parse_risk(path: Path) -> RiskProfile:
    """Parse a .risk.md file into a RiskProfile."""
    text = path.read_text(encoding="utf-8")
    meta, _ = _split_frontmatter(text)

    # Build regime_rules from r1_allowed..r4_allowed keys
    regime_rules: dict[str, bool] = {}
    for key in ("r1", "r2", "r3", "r4"):
        allowed_key = f"{key}_allowed"
        if allowed_key in meta:
            regime_rules[key] = bool(meta[allowed_key])
    if not regime_rules:
        regime_rules = {"r1": True, "r2": True, "r3": False, "r4": False}

    return RiskProfile(
        name=meta.get("name", path.stem),
        max_risk_per_trade_pct=float(meta.get("max_risk_per_trade_pct", 3.0)),
        max_portfolio_risk_pct=float(meta.get("max_portfolio_risk_pct", 30.0)),
        max_positions=int(meta.get("max_positions", 8)),
        min_pop=float(meta.get("min_pop", 0.50)),
        min_dte=int(meta.get("min_dte", 7)),
        max_dte=int(meta.get("max_dte", 45)),
        min_iv_rank=float(meta.get("min_iv_rank", 20.0)),
        max_spread_pct=float(meta.get("max_spread_pct", 0.05)),
        profit_target_pct=float(meta.get("profit_target_pct", 0.50)),
        stop_loss_pct=float(meta.get("stop_loss_pct", 2.0)),
        exit_dte=int(meta.get("exit_dte", 5)),
        regime_rules=regime_rules,
    )


def resolve_references(plan: WorkflowPlan, base_dir: Path) -> WorkflowPlan:
    """Resolve broker, universe, and risk references from base_dir subdirectories."""
    # Broker
    broker_path = base_dir / "broker_profiles" / f"{plan.broker_ref}.broker.md"
    if broker_path.exists():
        plan.broker = parse_broker(broker_path)
    else:
        plan.broker = None

    # Universe
    universe_path = base_dir / "universes" / f"{plan.universe_ref}.universe.md"
    if universe_path.exists():
        plan.universe = parse_universe(universe_path)
    else:
        plan.universe = None

    # Risk
    risk_path = base_dir / "risk_profiles" / f"{plan.risk_ref}.risk.md"
    if risk_path.exists():
        plan.risk = parse_risk(risk_path)
    else:
        plan.risk = None

    return plan
