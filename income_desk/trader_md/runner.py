"""TradingRunner -- execute .workflow.md files against income_desk engine."""
from __future__ import annotations

import re
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ExecutionContext:
    """Runtime state that accumulates as phases/steps execute."""

    universe: list[str] = field(default_factory=list)
    capital: float = 50_000.0
    market: str = "US"
    currency: str = "USD"
    risk: Any = None  # resolved RiskProfile
    positions: list = field(default_factory=list)  # for monitoring phases
    phases: dict[str, dict] = field(default_factory=dict)  # "phase1" -> {output_name: value}
    current_step_result: Any = None
    interactive: bool = False
    verbose: bool = False


@dataclass
class StepResult:
    """Outcome of one step."""

    step_name: str
    workflow: str
    status: str  # "OK", "SKIPPED", "BLOCKED", "HALTED", "FAILED", "WARNED", "ALERT"
    message: str = ""
    duration_ms: int = 0
    gate_results: list[tuple[str, bool]] = field(default_factory=list)


@dataclass
class ExecutionReport:
    """Full run outcome."""

    plan_name: str
    market: str
    broker: str
    data_source: str
    started_at: datetime = field(default_factory=datetime.now)
    step_results: list[StepResult] = field(default_factory=list)
    halted: bool = False
    halt_reason: str = ""


# ---------------------------------------------------------------------------
# Workflow -> module mapping
# ---------------------------------------------------------------------------

_MODULE_MAP = {
    "check_portfolio_health": "portfolio_health",
    "generate_daily_plan": "daily_plan",
    "snapshot_market": "market_snapshot",
    "scan_universe": "scan_universe",
    "rank_opportunities": "rank_opportunities",
    "validate_trade": "validate_trade",
    "size_position": "size_position",
    "price_trade": "price_trade",
    "monitor_positions": "monitor_positions",
    "adjust_position": "adjust_position",
    "assess_overnight_risk": "overnight_risk",
    "aggregate_portfolio_greeks": "portfolio_greeks",
    "stress_test_portfolio": "stress_test",
    "run_benchmark": "benchmarking",
    "check_expiry_day": "expiry_day",
    "generate_daily_report": "daily_report",
}


# ---------------------------------------------------------------------------
# TradingRunner
# ---------------------------------------------------------------------------


class TradingRunner:
    """Load and execute a .workflow.md file against income_desk."""

    def __init__(
        self,
        workflow_path: str,
        interactive: bool = False,
        verbose: bool = False,
    ):
        self.workflow_path = Path(workflow_path)
        self.interactive = interactive
        self.verbose = verbose
        self.base_dir = self._find_base_dir()
        self.plan: Any = None
        self.ma: Any = None
        self.ctx: ExecutionContext | None = None
        self.report: ExecutionReport | None = None

    # -- helpers -------------------------------------------------------------

    def _find_base_dir(self) -> Path:
        """Find trader_md base dir from workflow path."""
        p = self.workflow_path.parent
        while p != p.parent:
            if (p / "broker_profiles").exists() or (p / "universes").exists():
                return p
            p = p.parent
        # Fallback: assume workflow is in trader_md/workflows/
        return self.workflow_path.parent.parent

    # -- broker setup --------------------------------------------------------

    def _setup_broker(self, market: str) -> tuple[float | None, float | None]:
        """Connect broker based on plan.broker profile, with fallback."""
        from income_desk import DataService, MarketAnalyzer

        broker_profile = self.plan.broker
        if broker_profile is None or broker_profile.broker_type == "simulated":
            return self._setup_simulated(market)

        # Load .env for credentials
        try:
            from dotenv import load_dotenv

            env_path = self.base_dir / broker_profile.credentials_source
            if env_path.exists():
                load_dotenv(env_path)
            else:
                load_dotenv()  # try default .env
        except ImportError:
            pass

        # Suppress broker connection warnings
        import logging

        logging.getLogger("income_desk").setLevel(logging.ERROR)

        md, mm, acct, wl = None, None, None, None
        data_source = "Simulated"

        try:
            if broker_profile.broker_type == "tastytrade":
                from income_desk.broker.tastytrade import connect_tastytrade

                is_paper = broker_profile.mode == "paper"
                md, mm, acct, wl = connect_tastytrade(is_paper=is_paper)
                data_source = f"tastytrade ({'PAPER' if is_paper else 'LIVE'})"
            elif broker_profile.broker_type == "dhan":
                from income_desk.broker.dhan import connect_dhan

                md, mm, acct, wl = connect_dhan()
                data_source = "dhan (LIVE)"
        except Exception as e:
            print(f"  Broker connection failed: {e}")
            if broker_profile.fallback == "simulated":
                print("  Falling back to simulated data")

        # Check market hours -- fall back to simulated quotes if closed
        from income_desk.trader.support import is_market_open

        if md is not None and not is_market_open(market):
            from income_desk.adapters.simulated import (
                SimulatedMarketData,  # noqa: F811
                SimulatedMetrics,
                create_ideal_income,
                create_india_trading,
            )

            sim = create_india_trading() if market == "India" else create_ideal_income()
            md = sim
            mm = SimulatedMetrics(sim)
            data_source += " (market closed, simulated quotes)"

        if md is None:
            return self._setup_simulated(market)

        # Get account info
        nlv, bp = None, None
        if acct:
            try:
                bal = acct.get_balance()
                nlv = bal.net_liquidating_value
                bp = bal.derivative_buying_power
            except Exception:
                pass

        assert self.report is not None
        self.ma = MarketAnalyzer(
            data_service=DataService(),
            market=market if market == "India" else None,
            market_data=md,
            market_metrics=mm,
            account_provider=acct,
            watchlist_provider=wl,
        )
        self.report.broker = broker_profile.name
        self.report.data_source = data_source
        return nlv, bp

    def _setup_simulated(self, market: str) -> tuple[float | None, float | None]:
        """Set up simulated data (no broker)."""
        from income_desk import DataService, MarketAnalyzer
        from income_desk.adapters.simulated import (
            SimulatedAccount,
            SimulatedMetrics,
            create_ideal_income,
            create_india_trading,
        )

        if market == "India":
            sim = create_india_trading()
        else:
            sim = create_ideal_income()

        mm = SimulatedMetrics(sim)
        acct = SimulatedAccount(
            nlv=sim._account_nlv,
            cash=sim._account_cash,
            bp=sim._account_bp,
        )

        self.ma = MarketAnalyzer(
            data_service=DataService(),
            market=market if market == "India" else None,
            market_data=sim,
            market_metrics=mm,
            account_provider=acct,
            watchlist_provider=None,
        )
        assert self.report is not None
        self.report.broker = "simulated"
        self.report.data_source = "Simulated (preset)"

        nlv = sim._account_nlv
        bp = sim._account_bp
        return nlv, bp

    # -- binding resolution --------------------------------------------------

    def _resolve_binding(self, expr: str, ctx: ExecutionContext) -> Any:
        """Resolve a binding expression like $universe, $capital, $phase1.iv_rank_map."""
        if not isinstance(expr, str):
            return expr
        if not expr.startswith("$"):
            # Parse literal values: "[]", "true", "false", numbers
            if expr == "[]":
                return []
            if expr == "true" or expr == "True":
                return True
            if expr == "false" or expr == "False":
                return False
            if expr == "null" or expr == "None":
                return None
            try:
                return int(expr)
            except ValueError:
                pass
            try:
                return float(expr)
            except ValueError:
                pass
            return expr  # string literal

        path = expr[1:]  # strip $

        if path == "universe":
            return ctx.universe
        if path == "capital":
            return ctx.capital
        if path == "positions":
            return ctx.positions
        if path.startswith("positions["):
            match = re.match(r"positions\[(\d+)\](?:\.(.*))?" , path)
            if match:
                idx = int(match.group(1))
                rest = match.group(2)
                if idx < len(ctx.positions):
                    item = ctx.positions[idx]
                    if rest:
                        return self._get_nested(item, rest)
                    return item
            return None
        if path.startswith("risk."):
            field_name = path.split(".", 1)[1]
            if ctx.risk and hasattr(ctx.risk, field_name):
                return getattr(ctx.risk, field_name)
            return None
        if path.startswith("result."):
            field_path = path.split(".", 1)[1]
            return self._get_nested(ctx.current_step_result, field_path)
        if path.startswith("phase"):
            match = re.match(r"phase(\d+)\.(.*)", path)
            if match:
                phase_key = f"phase{match.group(1)}"
                field_path = match.group(2)
                phase_data = ctx.phases.get(phase_key, {})
                return self._get_nested_or_indexed(phase_data, field_path)
        return expr  # couldn't resolve, return as-is

    def _get_nested(self, obj: Any, path: str) -> Any:
        """Navigate dotted path on an object."""
        parts = path.split(".")
        current = obj
        for part in parts:
            if current is None:
                return None
            if hasattr(current, part):
                current = getattr(current, part)
            elif isinstance(current, dict):
                current = current.get(part)
            else:
                return None
        return current

    def _get_nested_or_indexed(self, data: dict, path: str) -> Any:
        """Handle paths like proposals[0].ticker or just iv_rank_map."""
        match = re.match(r"(\w+)\[(\d+)\](?:\.(.*))?" , path)
        if match:
            key, idx, rest = match.group(1), int(match.group(2)), match.group(3)
            lst = data.get(key)
            if lst and isinstance(lst, list) and idx < len(lst):
                item = lst[idx]
                if rest:
                    return self._get_nested(item, rest)
                return item
            return None
        return data.get(path)

    # -- gate evaluation -----------------------------------------------------

    def _evaluate_gate(self, gate: Any, step_result: Any, ctx: ExecutionContext) -> bool:
        """Evaluate a gate expression against step results."""
        expr = gate.expression.strip()

        # Build evaluation namespace from step result fields
        ns: dict[str, Any] = {}
        if step_result is not None:
            for attr in dir(step_result):
                if not attr.startswith("_"):
                    try:
                        ns[attr] = getattr(step_result, attr)
                    except Exception:
                        pass

        # Also add context outputs for cross-references
        for phase_key, phase_data in ctx.phases.items():
            ns.update(phase_data)

        # Resolve $risk references in the expression
        risk_refs = re.findall(r"\$risk\.(\w+)", expr)
        for ref in risk_refs:
            val = self._resolve_binding(f"$risk.{ref}", ctx)
            expr = expr.replace(f"$risk.{ref}", repr(val))

        try:
            result = eval(
                expr,
                {"__builtins__": {"len": len, "True": True, "False": False, "None": None}},
                ns,
            )
            return bool(result)
        except Exception:
            return True  # if can't evaluate, pass the gate

    # -- workflow invocation -------------------------------------------------

    def _call_workflow(self, step: Any, ctx: ExecutionContext) -> Any:
        """Dynamically call a workflow function by name."""
        import importlib

        import income_desk.workflow as wf_mod

        func = getattr(wf_mod, step.workflow, None)
        if func is None:
            raise ValueError(f"Unknown workflow: {step.workflow}")

        mod_name = _MODULE_MAP.get(step.workflow, step.workflow)
        mod = importlib.import_module(f"income_desk.workflow.{mod_name}")

        # Find the Request class (first class ending in "Request")
        request_cls = None
        for name in dir(mod):
            obj = getattr(mod, name)
            if isinstance(obj, type) and name.endswith("Request"):
                request_cls = obj
                break

        if request_cls is None:
            raise ValueError(f"No Request class found in income_desk.workflow.{mod_name}")

        # Resolve all input bindings
        resolved_inputs: dict[str, Any] = {}
        for field_name, binding in step.inputs.items():
            resolved_inputs[field_name] = self._resolve_binding(binding, ctx)

        # Add market from context if not in inputs and the request class has it
        if "market" not in resolved_inputs and hasattr(request_cls, "model_fields"):
            if "market" in request_cls.model_fields:
                resolved_inputs["market"] = ctx.market

        # Filter to only valid request fields
        if hasattr(request_cls, "model_fields"):
            valid_fields = set(request_cls.model_fields.keys())
            resolved_inputs = {
                k: v for k, v in resolved_inputs.items() if k in valid_fields and v is not None
            }

        # Build and call
        request = request_cls(**resolved_inputs)

        from income_desk.trader.support import print_signature

        print_signature(step.workflow, request)

        return func(request, self.ma)

    # -- result printing -----------------------------------------------------

    def _print_step_result(self, step: Any, result: Any) -> None:
        """Print key fields from workflow response."""
        from income_desk.trader.support import print_table

        if result is None:
            return

        # Extract key scalar fields
        scalars: list[tuple[str, Any]] = []
        lists: list[tuple[str, list]] = []

        for attr in dir(result):
            if attr.startswith("_") or attr == "meta":
                continue
            try:
                val = getattr(result, attr)
            except Exception:
                continue
            if callable(val):
                continue
            if isinstance(val, list):
                lists.append((attr, val))
            elif isinstance(val, dict):
                # Print dict summary
                scalars.append((attr, f"{len(val)} items"))
            else:
                scalars.append((attr, val))

        # Print scalars
        if scalars:
            max_key = max(len(k) for k, _ in scalars) if scalars else 10
            for key, val in scalars[:8]:
                print(f"    {key:<{max_key + 2}} {val}")

        # Print first list as table if it has items
        for list_name, items in lists[:1]:
            if not items:
                continue
            # Try to extract tabular data from Pydantic models or dicts
            if hasattr(items[0], "model_fields"):
                fields = list(items[0].model_fields.keys())[:6]
                headers = fields
                rows = []
                for item in items[:10]:
                    row = []
                    for f in fields:
                        v = getattr(item, f, "")
                        if isinstance(v, float):
                            v = f"{v:.2f}"
                        row.append(v)
                    rows.append(row)
                print_table(list_name, headers, rows)
            elif isinstance(items[0], dict):
                fields = list(items[0].keys())[:6]
                rows = [[item.get(f, "") for f in fields] for item in items[:10]]
                print_table(list_name, fields, rows)

    def _print_summary(self) -> None:
        """Print execution summary table."""
        assert self.report is not None
        from income_desk.trader.support import print_table

        headers = ["Phase", "Step", "Workflow", "Status", "Time(ms)"]
        rows = []
        # Track which phase each step belongs to
        phase_idx = 0
        phases = self.plan.phases if self.plan else []
        step_count = 0

        for sr in self.report.step_results:
            # Find which phase this step belongs to
            phase_label = ""
            cum = 0
            for p in phases:
                cum += len(p.steps)
                if step_count < cum:
                    phase_label = f"Phase {p.number}"
                    break

            rows.append([phase_label, sr.step_name, sr.workflow, sr.status, sr.duration_ms])
            step_count += 1

        print(f"\n{'=' * 60}")
        print("  EXECUTION SUMMARY")
        print_table("", headers, rows)

        ok = sum(1 for r in self.report.step_results if r.status == "OK")
        skipped = sum(1 for r in self.report.step_results if r.status in ("SKIPPED", "WARNED"))
        failed = sum(1 for r in self.report.step_results if r.status == "FAILED")
        total = len(self.report.step_results)
        elapsed = int((datetime.now() - self.report.started_at).total_seconds() * 1000)

        print(f"  Total: {total} | OK: {ok} | Skipped: {skipped} | Failed: {failed}")
        if self.report.halted:
            print(f"  HALTED: {self.report.halt_reason}")
        print(f"  Elapsed: {elapsed}ms")
        print(f"{'=' * 60}\n")

    # -- public API ----------------------------------------------------------

    def run(self) -> ExecutionReport:
        """Execute the complete workflow."""
        from income_desk.trader.support import (
            build_demo_positions,
            print_error,
            wait_for_input,
        )

        # 1. Parse and resolve
        from income_desk.trader_md.parser import parse_workflow, resolve_references

        self.plan = parse_workflow(self.workflow_path)
        self.plan = resolve_references(self.plan, self.base_dir)

        # 2. Initialize report
        market = "India" if (self.plan.broker and self.plan.broker.market == "India") else "US"
        self.report = ExecutionReport(
            plan_name=self.plan.name,
            market=market,
            broker="simulated",
            data_source="simulated",
        )

        # 3. Setup broker
        nlv, bp = self._setup_broker(market)

        # 4. Initialize context
        self.ctx = ExecutionContext(
            universe=self.plan.universe.tickers if self.plan.universe else [],
            capital=nlv or (5_000_000 if market == "India" else 50_000),
            market=market,
            currency="INR" if market == "India" else "USD",
            risk=self.plan.risk,
            positions=build_demo_positions(market),
            interactive=self.interactive,
            verbose=self.verbose,
        )

        # 5. Print banner
        print(f"\n{'=' * 60}")
        print(f"  TRADER MD: {self.plan.name}")
        print(f"  Market: {market} | Broker: {self.report.broker}")
        print(f"  Data: {self.report.data_source}")
        print(f"  Universe: {len(self.ctx.universe)} tickers")
        if self.plan.risk:
            print(
                f"  Risk: {self.plan.risk.name}"
                f" (POP>{self.plan.risk.min_pop}, max {self.plan.risk.max_positions} pos)"
            )
        print(f"{'=' * 60}\n")

        # 6. Execute phases
        for phase in self.plan.phases:
            if self.report.halted:
                break

            print(f"\n{'#' * 60}")
            print(f"  PHASE {phase.number}: {phase.name.upper()}")
            if phase.requires_positions:
                print("  (using demo positions)")
            print(f"{'#' * 60}")

            phase_key = f"phase{phase.number}"
            phase_outputs: dict[str, Any] = {}

            for step in phase.steps:
                if self.report.halted:
                    break

                print(f"\n  --- Step: {step.name} ---")

                # Check requires
                if (
                    step.requires == "live_broker"
                    and "simulated" in self.report.data_source.lower()
                ):
                    if step.on_simulated:
                        print(f"  {step.on_simulated}")
                        self.report.step_results.append(
                            StepResult(
                                step_name=step.name,
                                workflow=step.workflow,
                                status="WARNED",
                                message=step.on_simulated,
                            )
                        )
                        if self.interactive:
                            action = wait_for_input(True)
                            if action == "q":
                                sys.exit(0)
                            if action == "s":
                                break
                        continue

                start = time.time()

                try:
                    result = self._call_workflow(step, self.ctx)
                    self.ctx.current_step_result = result
                    duration = int((time.time() - start) * 1000)

                    # Store outputs
                    for out_name, out_binding in step.outputs.items():
                        value = self._resolve_binding(out_binding, self.ctx)
                        phase_outputs[out_name] = value

                    # Evaluate gates
                    gate_results: list[tuple[str, bool]] = []
                    gate_failed = False
                    for gate in step.gates:
                        passed = self._evaluate_gate(gate, result, self.ctx)
                        gate_results.append((gate.expression, passed))
                        if not passed:
                            gate_failed = True
                            msg = gate.message
                            # Try to format message with result fields
                            try:
                                ns = {
                                    attr: getattr(result, attr)
                                    for attr in dir(result)
                                    if not attr.startswith("_")
                                }
                                msg = msg.format(**ns) if msg else gate.expression
                            except Exception:
                                msg = msg or gate.expression

                            action_word = gate.on_fail.split()[0] if gate.on_fail else "WARN"
                            print(f"  GATE FAILED: {gate.expression}")
                            print(f"  Action: {action_word} -- {msg}")

                            if action_word == "HALT":
                                self.report.halted = True
                                self.report.halt_reason = msg

                            self.report.step_results.append(
                                StepResult(
                                    step_name=step.name,
                                    workflow=step.workflow,
                                    status=action_word,
                                    message=msg,
                                    duration_ms=duration,
                                    gate_results=gate_results,
                                )
                            )
                            break

                    if not gate_failed:
                        self._print_step_result(step, result)
                        self.report.step_results.append(
                            StepResult(
                                step_name=step.name,
                                workflow=step.workflow,
                                status="OK",
                                duration_ms=duration,
                                gate_results=gate_results,
                            )
                        )

                except Exception as e:
                    duration = int((time.time() - start) * 1000)
                    print_error(step.workflow, e)
                    if self.verbose:
                        traceback.print_exc()
                    self.report.step_results.append(
                        StepResult(
                            step_name=step.name,
                            workflow=step.workflow,
                            status="FAILED",
                            message=str(e),
                            duration_ms=duration,
                        )
                    )

                if self.interactive:
                    action = wait_for_input(True)
                    if action == "q":
                        sys.exit(0)
                    if action == "s":
                        break

            # Save phase outputs to context
            self.ctx.phases[phase_key] = phase_outputs

        # 7. Print summary
        self._print_summary()
        return self.report

    def validate(self) -> list[str]:
        """Parse-only validation. Check references, gate syntax, binding validity."""
        issues: list[str] = []
        try:
            from income_desk.trader_md.parser import parse_workflow, resolve_references

            plan = parse_workflow(self.workflow_path)
            plan = resolve_references(plan, self.base_dir)
        except Exception as e:
            return [f"Parse error: {e}"]

        if plan.broker is None:
            issues.append(f"Broker '{plan.broker_ref}' not found in broker_profiles/")
        if plan.universe is None:
            issues.append(f"Universe '{plan.universe_ref}' not found in universes/")
        if plan.risk is None:
            issues.append(f"Risk profile '{plan.risk_ref}' not found in risk_profiles/")

        # Check workflow references
        import income_desk.workflow as wf_mod

        for phase in plan.phases:
            for step in phase.steps:
                if not hasattr(wf_mod, step.workflow):
                    issues.append(f"Unknown workflow: {step.workflow} in {step.name}")
        return issues

    def dry_run(self) -> str:
        """Show what would execute without calling APIs."""
        from income_desk.trader_md.parser import parse_workflow, resolve_references

        plan = parse_workflow(self.workflow_path)
        plan = resolve_references(plan, self.base_dir)

        lines = [f"DRY RUN: {plan.name}", ""]
        lines.append(f"Broker: {plan.broker.name if plan.broker else 'NOT FOUND'}")
        lines.append(f"Universe: {len(plan.universe.tickers) if plan.universe else 0} tickers")
        lines.append(f"Risk: {plan.risk.name if plan.risk else 'NOT FOUND'}")
        lines.append("")

        for phase in plan.phases:
            lines.append(f"Phase {phase.number}: {phase.name}")
            if phase.requires_positions:
                lines.append("  (requires positions)")
            for step in phase.steps:
                gates_str = f" [{len(step.gates)} gates]" if step.gates else ""
                lines.append(f"  -> {step.name}: {step.workflow}{gates_str}")
                for k, v in step.inputs.items():
                    lines.append(f"     {k}: {v}")
        return "\n".join(lines)
