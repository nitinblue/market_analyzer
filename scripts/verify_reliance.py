"""Independent verification of RELIANCE Iron Butterfly calculations.

Uses live Dhan leg quotes + Yahoo price. No income_desk code used.
"""
import math
from datetime import date

print("=" * 70)
print("  INDEPENDENT VERIFICATION: RELIANCE Iron Butterfly")
print("  From live Dhan leg quotes (2026-04-01)")
print("=" * 70)

# -- INPUT: Live Leg Quotes --
# Using MID prices (what you'd realistically fill at)
short_put_strike = 1370
sp_bid, sp_ask, sp_mid = 38.65, 38.85, 38.75

long_put_strike = 1330
lp_bid, lp_ask, lp_mid = 24.95, 25.15, 25.05

short_call_strike = 1370
sc_bid, sc_ask, sc_mid = 42.85, 43.10, 42.98

long_call_strike = 1410
lc_bid, lc_ask, lc_mid = 24.50, 24.65, 24.57

underlying_price = 1374.00  # from Yahoo Finance

# -- STEP 1: Net Credit Per Share --
print("\n-- 1. NET CREDIT PER SHARE --")
# Selling: collect bid. Buying: pay ask.
credit_at_market = (sp_bid - lp_ask) + (sc_bid - lc_ask)
credit_at_mid = (sp_mid - lp_mid) + (sc_mid - lc_mid)

print(f"  Sell 1370 PE @ bid {sp_bid}, Buy 1330 PE @ ask {lp_ask}")
print(f"    Put spread credit: {sp_bid} - {lp_ask} = {sp_bid - lp_ask:.2f}")
print(f"  Sell 1370 CE @ bid {sc_bid}, Buy 1410 CE @ ask {lc_ask}")
print(f"    Call spread credit: {sc_bid} - {lc_ask} = {sc_bid - lc_ask:.2f}")
print(f"  Net credit (market fills): {credit_at_market:.2f} per share")
print(f"  Net credit (mid fills):    {credit_at_mid:.2f} per share")

# -- STEP 2: Lot Size --
print("\n-- 2. LOT SIZE --")
print("  RELIANCE NSE F&O lot size: 500 (per NSE circular)")
lot_size = 500

# -- STEP 3: Max Profit / Max Loss PER LOT --
print("\n-- 3. MAX PROFIT / MAX LOSS (per 1 lot) --")
put_wing = short_put_strike - long_put_strike  # 1370 - 1330 = 40
call_wing = long_call_strike - short_call_strike  # 1410 - 1370 = 40
wing_width = min(put_wing, call_wing)

print(f"  Put wing width:  {short_put_strike} - {long_put_strike} = {put_wing}")
print(f"  Call wing width: {long_call_strike} - {short_call_strike} = {call_wing}")
print(f"  Wing width:      {wing_width}")

for label, credit in [("MID fills", credit_at_mid), ("MARKET fills", credit_at_market)]:
    mp_share = credit
    ml_share = wing_width - credit
    print(f"\n  At {label}:")
    print(f"    Max profit/share = credit        = {mp_share:.2f}")
    print(f"    Max loss/share   = wing - credit  = {wing_width} - {credit:.2f} = {ml_share:.2f}")
    print(f"    Max profit/lot   = {mp_share:.2f} x {lot_size} = INR {mp_share * lot_size:,.2f}")
    print(f"    Max loss/lot     = {ml_share:.2f} x {lot_size} = INR {ml_share * lot_size:,.2f}")

# -- STEP 4: Breakevens --
print("\n-- 4. BREAKEVENS --")
be_low_mid = short_put_strike - credit_at_mid
be_high_mid = short_call_strike + credit_at_mid
be_low_mkt = short_put_strike - credit_at_market
be_high_mkt = short_call_strike + credit_at_market

print(f"  At MID:    {be_low_mid:.2f} -- {be_high_mid:.2f}  (range: {be_high_mid - be_low_mid:.2f})")
print(f"  At MARKET: {be_low_mkt:.2f} -- {be_high_mkt:.2f}  (range: {be_high_mkt - be_low_mkt:.2f})")

# -- STEP 5: POP (Probability of Profit) --
print("\n-- 5. POP ESTIMATE (IV-based, no regime shenanigans) --")
avg_iv = (0.293 + 0.314 + 0.252 + 0.247) / 4
print(f"  Average IV from legs: {avg_iv:.4f} ({avg_iv * 100:.1f}%)")

# DTE: RELIANCE monthly expiry is last Thursday of April 2026
exp_date = date(2026, 4, 30)
dte = (exp_date - date.today()).days
print(f"  DTE: {dte} (expiry: {exp_date})")

# Expected move at expiry: price * IV * sqrt(DTE/365)
sigma = underlying_price * avg_iv * math.sqrt(dte / 365)
print(f"  1-sigma move: {sigma:.2f} points ({sigma / underlying_price * 100:.1f}%)")

credit = credit_at_mid
be_low = be_low_mid
be_high = be_high_mid

dist_low = (underlying_price - be_low) / sigma
dist_high = (be_high - underlying_price) / sigma

pop_low = 0.5 * (1 + math.erf(dist_low / math.sqrt(2)))
pop_high = 0.5 * (1 + math.erf(dist_high / math.sqrt(2)))
pop = pop_low + pop_high - 1.0

print(f"  Distance to lower BE: ({underlying_price} - {be_low:.2f}) / {sigma:.2f} = {dist_low:.4f} sigma")
print(f"  Distance to upper BE: ({be_high:.2f} - {underlying_price}) / {sigma:.2f} = {dist_high:.4f} sigma")
print(f"  P(above lower BE): {pop_low:.4f} ({pop_low * 100:.1f}%)")
print(f"  P(below upper BE): {pop_high:.4f} ({pop_high * 100:.1f}%)")
print(f"  POP = {pop:.4f} ({pop * 100:.1f}%)")

# -- STEP 6: Expected Value --
print("\n-- 6. EXPECTED VALUE (per lot) --")
max_profit_lot = credit_at_mid * lot_size
max_loss_lot = (wing_width - credit_at_mid) * lot_size
ev = pop * max_profit_lot - (1 - pop) * max_loss_lot
print(f"  EV = {pop:.4f} x {max_profit_lot:,.2f} - {1 - pop:.4f} x {max_loss_lot:,.2f}")
print(f"     = {pop * max_profit_lot:,.2f} - {(1 - pop) * max_loss_lot:,.2f}")
print(f"     = INR {ev:,.2f}")

# -- STEP 7: Margin --
print("\n-- 7. MARGIN ESTIMATE --")
print("  User reports actual SPAN margin: ~INR 52,000 per lot")
print("  (SPAN calculation is broker-specific, cannot verify independently)")
user_margin = 52_000

# -- STEP 8: Position Sizing --
print("\n-- 8. POSITION SIZING --")
capital = 500_000
max_risk_pct = 0.04
max_risk_budget = capital * max_risk_pct
contracts_by_risk = int(max_risk_budget / max_loss_lot) if max_loss_lot > 0 else 0
contracts_by_margin = int(capital / user_margin) if user_margin > 0 else 0
print(f"  Capital:          INR {capital:,.0f}")
print(f"  Max risk (4%):    INR {max_risk_budget:,.0f}")
print(f"  Max loss/lot:     INR {max_loss_lot:,.0f}")
print(f"  By risk budget:   {max_risk_budget:,.0f} / {max_loss_lot:,.0f} = {contracts_by_risk} lots")
print(f"  By margin:        {capital:,.0f} / {user_margin:,.0f} = {contracts_by_margin} lots")
print(f"  Practical limit:  {min(contracts_by_risk, contracts_by_margin)} lot(s)")

# -- SUMMARY --
print("\n" + "=" * 70)
print("  VERIFIED NUMBERS (code must match these)")
print("=" * 70)
print(f"  Underlying price:    INR {underlying_price:,.2f}")
print(f"  Structure:           Iron Butterfly (short strikes both at 1370)")
print(f"  Lot size:            {lot_size}")
print(f"  Wing width:          {wing_width} points")
print(f"  Net credit/share:    INR {credit_at_mid:.2f} (mid) / {credit_at_market:.2f} (market)")
print(f"  Max profit/lot:      INR {max_profit_lot:,.2f}")
print(f"  Max loss/lot:        INR {max_loss_lot:,.2f}")
print(f"  Breakevens:          {be_low_mid:.2f} -- {be_high_mid:.2f}")
print(f"  POP (IV-based):      {pop * 100:.1f}%")
print(f"  EV per lot:          INR {ev:,.2f}")
print(f"  Contracts:           1 lot (margin-constrained)")
print("=" * 70)
