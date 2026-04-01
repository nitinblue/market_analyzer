"""Trace RELIANCE iron butterfly through every code function.

Simulates the exact code path with verified inputs.
Prints every intermediate value. Compares to ground truth.
"""
import math
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta

# ═══════════════════════════════════════════════════════════════════════
# GROUND TRUTH (from verify_reliance.py)
# ═══════════════════════════════════════════════════════════════════════
TRUTH = {
    "lot_size": 500,
    "wing_width": 40,
    "credit_mid": 32.11,
    "max_profit_lot": 16055.0,
    "max_loss_lot": 3945.0,
    "be_low": 1337.89,
    "be_high": 1402.11,
    "pop": 0.236,  # ~23.6%
    "capital": 500_000,
    "contracts": 1,  # margin constrained
}

def check(label, got, expected, tolerance=0.05):
    """Compare got vs expected, flag if off by more than tolerance."""
    if expected == 0:
        ok = abs(got) < 1
    else:
        pct_off = abs(got - expected) / abs(expected)
        ok = pct_off <= tolerance
    status = "OK" if ok else "WRONG"
    print(f"  [{status}] {label}: got={got}  expected={expected}")
    return ok


print("=" * 70)
print("  TRACE: RELIANCE Iron Butterfly through income_desk code")
print("=" * 70)

# ── 1. Registry: lot_size ──
print("\n── 1. REGISTRY LOT SIZE ──")
from income_desk.registry import MarketRegistry
reg = MarketRegistry()
inst = reg.get_instrument("RELIANCE", "INDIA")
print(f"  registry.get_instrument('RELIANCE').lot_size = {inst.lot_size}")
check("lot_size", inst.lot_size, TRUTH["lot_size"], tolerance=0)

# ── 2. TradeSpec construction ──
print("\n── 2. TRADE SPEC CONSTRUCTION ──")
from income_desk.models.opportunity import TradeSpec, LegSpec, LegAction
from income_desk.opportunity.option_plays._trade_spec_helpers import _populate_market_fields

mkt = _populate_market_fields("RELIANCE")
print(f"  _populate_market_fields('RELIANCE') = {mkt}")
check("trade_spec.lot_size", mkt.get("lot_size", 100), TRUTH["lot_size"], tolerance=0)

# Build the actual trade spec matching the user's live trade
exp_date = date(2026, 4, 30)  # last Thu of April
dte = (exp_date - date.today()).days
print(f"  DTE: {dte}")

ts = TradeSpec(
    ticker="RELIANCE",
    legs=[
        LegSpec(role="short_put", action=LegAction.SELL_TO_OPEN, option_type="put",
                strike=1370, strike_label="SP", expiration=exp_date, days_to_expiry=dte, atm_iv_at_expiry=0.293),
        LegSpec(role="long_put", action=LegAction.BUY_TO_OPEN, option_type="put",
                strike=1330, strike_label="LP", expiration=exp_date, days_to_expiry=dte, atm_iv_at_expiry=0.314),
        LegSpec(role="short_call", action=LegAction.SELL_TO_OPEN, option_type="call",
                strike=1370, strike_label="SC", expiration=exp_date, days_to_expiry=dte, atm_iv_at_expiry=0.252),
        LegSpec(role="long_call", action=LegAction.BUY_TO_OPEN, option_type="call",
                strike=1410, strike_label="LC", expiration=exp_date, days_to_expiry=dte, atm_iv_at_expiry=0.247),
    ],
    underlying_price=1374.0,
    target_dte=dte,
    target_expiration=exp_date,
    spec_rationale="test",
    structure_type="iron_condor",  # code may classify as IC even though short strikes match
    order_side="credit",
    **mkt,
)
print(f"  trade_spec.lot_size = {ts.lot_size}")
print(f"  trade_spec.wing_width_points = {ts.wing_width_points}")
print(f"  trade_spec.currency = {ts.currency}")
check("ts.lot_size", ts.lot_size, TRUTH["lot_size"], tolerance=0)

# ── 3. Breakevens ──
print("\n── 3. BREAKEVENS ──")
from income_desk.trade_lifecycle import _compute_breakevens
entry_credit = 32.11  # mid price credit per share
be_low, be_high = _compute_breakevens(ts, entry_credit)
print(f"  _compute_breakevens(ts, {entry_credit}) = ({be_low}, {be_high})")
check("be_low", be_low, TRUTH["be_low"], tolerance=0.01)
check("be_high", be_high, TRUTH["be_high"], tolerance=0.01)

# ── 4. POP estimate ──
print("\n── 4. POP ESTIMATE ──")
from income_desk.trade_lifecycle import estimate_pop

# What atr_pct does the code use? Let's get it from technicals
try:
    from income_desk import DataService
    ds = DataService()
    ohlcv = ds.get_ohlcv("RELIANCE.NS")
    if ohlcv is not None and len(ohlcv) > 0:
        close = ohlcv["Close"]
        high = ohlcv["High"]
        low = ohlcv["Low"]
        # ATR calculation (14-period)
        tr = []
        for i in range(1, len(ohlcv)):
            tr.append(max(
                float(high.iloc[i]) - float(low.iloc[i]),
                abs(float(high.iloc[i]) - float(close.iloc[i-1])),
                abs(float(low.iloc[i]) - float(close.iloc[i-1])),
            ))
        atr_14 = sum(tr[-14:]) / 14
        last_close = float(close.iloc[-1])
        atr_pct = (atr_14 / last_close) * 100
        print(f"  ATR(14) from yfinance: {atr_14:.2f}")
        print(f"  Last close: {last_close:.2f}")
        print(f"  atr_pct: {atr_pct:.4f}%")
    else:
        atr_pct = 1.5  # fallback
        print(f"  No OHLCV data, using fallback atr_pct={atr_pct}")
except Exception as e:
    atr_pct = 1.5
    print(f"  Error getting OHLCV: {e}, using fallback atr_pct={atr_pct}")

# Now run estimate_pop with regime_id=1 (what the harness would use)
for regime_id in [1, 2]:
    pop_result = estimate_pop(
        trade_spec=ts,
        entry_price=entry_credit,
        regime_id=regime_id,
        atr_pct=atr_pct,
        current_price=1374.0,
    )
    if pop_result:
        print(f"\n  R{regime_id}: POP={pop_result.pop_pct:.4f} ({pop_result.pop_pct*100:.1f}%)")
        print(f"       EV={pop_result.expected_value:.2f}")
        print(f"       max_profit={pop_result.max_profit:.2f}")
        print(f"       max_loss={pop_result.max_loss:.2f}")
        print(f"       trade_quality={pop_result.trade_quality}")
        check(f"R{regime_id} max_profit", pop_result.max_profit, TRUTH["max_profit_lot"])
        check(f"R{regime_id} max_loss", pop_result.max_loss, TRUTH["max_loss_lot"])
    else:
        print(f"  R{regime_id}: POP returned None!")

# ── 5. IV-based POP for comparison ──
print("\n── 5. IV-BASED POP (ground truth method) ──")
avg_iv = (0.293 + 0.314 + 0.252 + 0.247) / 4
sigma_iv = 1374.0 * avg_iv * math.sqrt(dte / 365)
dist_low_iv = (1374.0 - TRUTH["be_low"]) / sigma_iv
dist_high_iv = (TRUTH["be_high"] - 1374.0) / sigma_iv
pop_iv = (0.5 * (1 + math.erf(dist_low_iv / math.sqrt(2)))) + \
         (0.5 * (1 + math.erf(dist_high_iv / math.sqrt(2)))) - 1.0
print(f"  IV-based sigma: {sigma_iv:.2f}")
print(f"  IV-based POP:   {pop_iv:.4f} ({pop_iv*100:.1f}%)")

# ── 6. Kelly fraction ──
print("\n── 6. KELLY FRACTION ──")
from income_desk.features.position_sizing import compute_kelly_fraction
kf = compute_kelly_fraction(
    pop_pct=pop_iv,
    max_profit=TRUTH["max_profit_lot"],
    max_loss=TRUTH["max_loss_lot"],
)
print(f"  Kelly fraction (IV-based POP): {kf:.4f}")
print(f"  Interpretation: bet {kf*100:.1f}% of capital per trade")

# ── 7. Position sizing ──
print("\n── 7. POSITION SIZING ──")
from income_desk.features.position_sizing import compute_position_size
capital = TRUTH["capital"]
risk_per = TRUTH["max_loss_lot"]

sz = compute_position_size(
    pop_pct=pop_iv,
    max_profit=TRUTH["max_profit_lot"],
    max_loss=TRUTH["max_loss_lot"],
    capital=capital,
    risk_per_contract=risk_per,
    regime_id=1,
    wing_width=TRUTH["wing_width"],
    safety_factor=0.5,
    max_contracts=20,
)
print(f"  recommended_contracts: {sz.recommended_contracts}")
print(f"  kelly_fraction: {sz.portfolio_adjusted_fraction:.4f}")
print(f"  max_contracts_by_risk: {sz.max_contracts_by_risk}")
print(f"  rationale: {sz.rationale}")

# ── 8. What rank_opportunities does with these ──
print("\n── 8. RANK_OPPORTUNITIES MAX PROFIT/LOSS CALC ──")
lot_size = TRUTH["lot_size"]
wing_width = TRUTH["wing_width"]
repriced_entry_credit = entry_credit  # from repricing

# Simulating rank_opportunities.py lines 229-234
max_profit_per = repriced_entry_credit * lot_size
max_loss_per = (wing_width * lot_size) - max_profit_per

print(f"  entry_credit={repriced_entry_credit}, lot_size={lot_size}, wing_width={wing_width}")
print(f"  max_profit_per = {repriced_entry_credit} * {lot_size} = {max_profit_per:.2f}")
print(f"  max_loss_per = ({wing_width} * {lot_size}) - {max_profit_per:.2f} = {max_loss_per:.2f}")
check("max_profit_per", max_profit_per, TRUTH["max_profit_lot"])
check("max_loss_per", max_loss_per, TRUTH["max_loss_lot"])

# Margin: now uses max_loss_per (no hardcoded SPAN %)
margin_per_lot = max_loss_per
print(f"\n  margin_per_lot (= max_loss_per) = INR {margin_per_lot:,.0f}")

max_risk_per_trade = capital * 0.04
max_contracts_by_margin = max(1, int(max_risk_per_trade / margin_per_lot))
print(f"  max_risk_per_trade = {capital} * 0.04 = INR {max_risk_per_trade:,.0f}")
print(f"  max_contracts_by_margin = {max_risk_per_trade:,.0f} / {margin_per_lot:,.0f} = {max_contracts_by_margin}")

# Final max_risk on proposal
final_contracts = min(sz.recommended_contracts, max_contracts_by_margin)
final_max_risk = max_loss_per * final_contracts
final_max_profit = max_profit_per * final_contracts
print(f"\n  FINAL contracts: {final_contracts}")
print(f"  FINAL max_risk:   INR {final_max_risk:,.2f}")
print(f"  FINAL max_profit: INR {final_max_profit:,.2f}")

# ═══════════════════════════════════════════════════════════════════════
print("\n" + "=" * 70)
print("  SUMMARY: Code vs Ground Truth")
print("=" * 70)
all_ok = True
all_ok &= check("lot_size", inst.lot_size, 500, 0)
all_ok &= check("max_profit/lot", max_profit_per, 16055.0)
all_ok &= check("max_loss/lot", max_loss_per, 3945.0)
all_ok &= check("breakeven_low", be_low, 1337.89, 0.01)
all_ok &= check("breakeven_high", be_high, 1402.11, 0.01)
if pop_result:
    all_ok &= check("POP (ATR-based)", pop_result.pop_pct, 0.236, 0.15)
all_ok &= check("POP (IV-based)", pop_iv, 0.236, 0.05)
all_ok &= check("contracts", final_contracts, 1, 0)

if all_ok:
    print("\n  ALL CHECKS PASSED")
else:
    print("\n  SOME CHECKS FAILED — fix required")
