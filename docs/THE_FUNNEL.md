# income-desk — Revenue Streams

> The library is free. The intelligence is the product.
> India is the primary market opportunity — 10M+ retail F&O traders, zero institutional-grade tools accessible to them.

---

## The Core Insight

income-desk has something no other retail tool has: **decision intelligence that says NO.** Every Wall Street desk has risk managers, compliance checks, and sizing models. Indian retail traders have Zerodha Varsity and YouTube. The gap is enormous.

You're not selling software. You're selling **a professional trading desk experience** to people who've never had one.

---

## Service 1: Monthly Portfolio Review (₹999-2999/month)

**What:** Clients upload their broker CSV (Fidelity, Zerodha, Dhan, any broker). You run the full income-desk analysis and send them a report.

**The report includes:**
- Current portfolio trust score (are they trading blind?)
- Regime analysis on every position (is their NIFTY IC in the right regime?)
- Position stress test (which positions are at risk?)
- Assignment risk check (any options about to be exercised?)
- Desk allocation review (are they over-concentrated?)
- Rebalancing recommendations (move capital from desk A to desk B)
- Next month's suggested trades (top 3 opportunities with full audit scores)

**Pricing tiers:**

| Tier | Price | What they get | Target |
|------|-------|---------------|--------|
| Basic | ₹999/month | Monthly CSV review + report PDF | Small retail (₹1-5L portfolio) |
| Standard | ₹1999/month | Monthly review + weekly regime alerts + email support | Active retail (₹5-25L) |
| Premium | ₹2999/month | Monthly review + weekly alerts + 1 call/month + custom desks | Serious retail (₹25L+) |

**How it works:**
```
Client uploads CSV → income-desk processes →
  regime scan → validation gates → stress test → desk health →
    → PDF report generated → email to client
```

**What income-desk already supports:**
- `import_trades_csv()` — parse any broker's export
- `audit_decision()` — 4-level scoring on every position
- `run_position_stress()` — ongoing stress test
- `assess_assignment_risk()` — European/American exercise
- `assess_crash_sentinel()` — market health signal
- `rebalance_desks()` — capital reallocation recommendations
- `evaluate_desk_health()` — is each desk performing?

**What to build:**
- PDF report generator (from TraderReport → formatted PDF)
- Client onboarding form (risk tolerance, capital, goals)
- Monthly batch processing script

**India market size:** 10M+ active F&O traders in India. Even 0.01% = 1,000 clients. At ₹1999/month = ₹20L/month recurring.

---

## Service 2: Overnight Risk Service for India Desks (₹4999-14999/month)

**The problem:** India market closes at 3:30 PM IST. US market opens at 7:00 PM IST and runs until 1:30 AM IST. India traders go to sleep while US is trading. By morning, NIFTY can gap 2-3% based on US overnight action.

**No Indian retail trader monitors this.** Institutional desks have overnight teams in New York. Retail traders wake up to surprises.

**What you offer:**
- US close analysis (4:00 PM ET / 1:30 AM IST) — regime, VIX, key moves
- India opening gap prediction (from cross-market analysis)
- Position impact assessment — "your NIFTY IC is at risk, here's what to do at open"
- Pre-market alert (8:00 AM IST) — action plan before India opens
- Emergency alert — if US crashes overnight, SMS/WhatsApp before India opens

**Pricing:**

| Tier | Price | What | Target |
|------|-------|------|--------|
| Alerts Only | ₹4999/month | Daily pre-market email + emergency SMS | Retail F&O (₹5-25L) |
| Full Service | ₹9999/month | Alerts + position-specific analysis + action plan | Active retail (₹25L-1Cr) |
| Desk Service | ₹14999/month | Full service + weekly call + custom regime thresholds | Prop desks / HNI (₹1Cr+) |

**What income-desk already supports:**
- `analyze_cross_market("SPY", "NIFTY")` — gap prediction
- `assess_crash_sentinel()` — RED/ORANGE signals
- `compute_monitoring_action()` — closing TradeSpec for at-risk positions
- `assess_overnight_risk()` — position-level overnight assessment
- `run_position_stress()` — what happens if NIFTY gaps 2%?
- `compute_regime_stop()` — regime-appropriate stop levels

**What to build:**
- Automated US close scan (run at 1:30 AM IST)
- India pre-market report generator (run at 8:00 AM IST)
- SMS/WhatsApp alert integration (Twilio)
- Client position database (link to their Dhan/Zerodha account or CSV upload)

**India market size:** 1M+ active NIFTY/BANKNIFTY traders. Even the alerts-only tier at ₹4999/month with 500 clients = ₹25L/month.

---

## Service 3: Regime Intelligence Feed (₹999-4999/month)

**What:** Daily regime classification for all major instruments, delivered as data feed.

**Clients:** Algo traders, small prop desks, financial advisors who need regime data but can't build their own HMM.

**The feed:**
```json
{
  "date": "2026-03-22",
  "regimes": {
    "NIFTY": {"regime": 1, "confidence": 0.95, "r4_prob": 0.02},
    "BANKNIFTY": {"regime": 2, "confidence": 0.88, "r4_prob": 0.08},
    "RELIANCE": {"regime": 3, "confidence": 0.72, "r4_prob": 0.05},
    ...
  },
  "sentinel": "YELLOW",
  "recommended_structures": {
    "NIFTY": ["iron_condor", "calendar"],
    "BANKNIFTY": ["credit_spread", "iron_butterfly"]
  }
}
```

**Pricing:**

| Tier | Price | Coverage | Delivery |
|------|-------|----------|----------|
| Index | ₹999/month | NIFTY, BANKNIFTY, FINNIFTY | Daily email/API |
| FnO Universe | ₹2999/month | All NSE F&O stocks (150+) | Daily API endpoint |
| Global | ₹4999/month | US + India + regime transitions + sentinel | Real-time API |

**What income-desk already supports:**
- `ma.regime.detect()` — per-instrument regime
- `assess_crash_sentinel()` — market health
- `ma.ranking.rank()` — strategy recommendations
- All data serializes to JSON via Pydantic `model_dump()`

**What to build:**
- Daily batch regime scan (cron job)
- API endpoint (FastAPI wrapper around income-desk)
- Client API key management

---

## Service 4: Crash Response Service (Event-Based Pricing)

**What:** When the sentinel turns RED, you activate a response service for clients.

**Think of it like insurance:** Clients pay a small monthly fee (₹499/month) for "crash coverage." When a crash happens, they get:
- Immediate alert with specific actions
- Position-by-position close/hold/adjust recommendation
- Post-crash recovery plan (when to re-enter, which desks, what sizing)
- Weekly guidance during recovery phase

**Pricing:**
- Monthly standby: ₹499/month (just the sentinel monitoring)
- Crash activation: ₹4999 one-time (when RED triggers, full response service for 30 days)
- Recovery guidance: ₹2999/month (during BLUE phase, deployment assistance)

**Why this works:** Most retail traders panic during crashes. They sell at the bottom. A systematic response plan — with specific TradeSpecs — is worth thousands in prevented losses.

**What income-desk already supports:**
- `assess_crash_sentinel()` — GREEN → RED detection
- `docs/CRASH_PLAYBOOK.md` — the 4-phase protocol
- `compute_position_size(safety_factor=0.25)` — quarter Kelly for recovery
- `compute_monitoring_action()` — closing specs for at-risk positions

---

## Service 5: Professional Onboarding for New Traders (One-Time ₹4999-14999)

**What:** First-time options traders who want to start RIGHT. You set up their entire trading infrastructure.

**Package includes:**
- Risk profile assessment (conservative/moderate/aggressive)
- Desk structure designed for their capital and goals
- Broker setup (help them connect Dhan/Zerodha/TastyTrade)
- income-desk configured with their watchlist
- First month of guided trading (3-5 supervised trades)
- Exit rules and circuit breakers defined
- 30-day follow-up review

**Pricing:**

| Package | Price | Capital Range | What |
|---------|-------|---------------|------|
| Starter | ₹4999 | ₹1-5L | Setup + 1 month guidance |
| Professional | ₹9999 | ₹5-25L | Setup + 3 months + weekly reviews |
| Desk Build | ₹14999 | ₹25L+ | Full desk design + 3 months + custom regime thresholds |

**Why this works:** New traders lose money in their first year because they start wrong. A proper setup — desks, risk limits, circuit breakers, regime awareness — from day one is worth the entire fee in prevented losses.

---

## Service 6: API-as-a-Service for Fintech/Advisors (B2B)

**What:** Financial advisors and small fintechs who want regime intelligence + validation gates in their own product.

**Pricing:** Usage-based
- 1,000 API calls/month: free (developer tier)
- 10,000 calls/month: ₹9999/month
- 100,000 calls/month: ₹29999/month
- Unlimited: custom pricing

**Endpoints:**
- `/regime/{ticker}` — regime classification
- `/validate` — 10-check profitability gate
- `/sentinel` — crash sentinel signal
- `/audit` — 4-level decision audit
- `/desk/recommend` — desk allocation recommendation

**What income-desk already supports:** Everything. Just needs a FastAPI wrapper.

---

## Revenue Projection — India Focus

### Year 1 (conservative)

| Service | Clients | MRR | Annual |
|---------|---------|-----|--------|
| Monthly Review (₹1999 avg) | 100 | ₹2.0L | ₹24L |
| Overnight Risk (₹7499 avg) | 50 | ₹3.75L | ₹45L |
| Regime Feed (₹2499 avg) | 30 | ₹0.75L | ₹9L |
| Crash Response (₹499 standby) | 200 | ₹1.0L | ₹12L |
| Onboarding (₹9999 avg) | 20/month | ₹2.0L | ₹24L |
| **Total** | | **₹9.5L/month** | **₹1.14Cr** |

### Year 2 (with growth)

| Service | Clients | MRR | Annual |
|---------|---------|-----|--------|
| Monthly Review | 500 | ₹10L | ₹1.2Cr |
| Overnight Risk | 200 | ₹15L | ₹1.8Cr |
| Regime Feed | 100 | ₹2.5L | ₹30L |
| API Service | 10 B2B | ₹3L | ₹36L |
| **Total** | | **₹30.5L/month** | **₹3.66Cr** |

---

## India Market Opportunity — Why This Works

1. **10M+ retail F&O traders** — largest options market in the world by volume (NSE)
2. **Zero institutional tools at retail price** — Bloomberg costs ₹15L/year. income-desk costs ₹999/month.
3. **Regulatory tailwind** — SEBI pushing for investor education and risk management
4. **Overnight gap problem is REAL** — US market moves overnight, India opens with 1-3% gaps. Nobody helps retail manage this.
5. **Language of money** — Indian retail traders spend ₹5000-50000/month on "tips" and "paid groups" that have zero systematic methodology. income-desk is the systematic alternative.
6. **WhatsApp distribution** — India's primary communication channel. Regime alerts via WhatsApp is a natural fit.

---

## What to Build Next (Prioritized)

| Priority | What | Enables | Effort |
|----------|------|---------|--------|
| **P0** | PDF report generator from TraderReport | Monthly Review service | Medium |
| **P0** | Client onboarding form + risk profile storage | All services | Small |
| **P0** | SMS/WhatsApp alert via Twilio | Overnight Risk service | Small |
| **P1** | FastAPI wrapper for income-desk | API-as-a-Service | Medium |
| **P1** | Daily batch regime scan (cron) | Regime Feed | Small |
| **P1** | US close → India pre-market automated pipeline | Overnight Risk | Medium |
| **P2** | Payment gateway (Razorpay) | All paid services | Small |
| **P2** | Client dashboard (simple web app) | All services | Large |
| **P2** | WhatsApp bot for alerts | Overnight Risk, crash response | Medium |
