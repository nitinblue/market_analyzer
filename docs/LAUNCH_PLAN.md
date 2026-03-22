# income-desk — Launch & Discovery Plan

> Package: https://pypi.org/project/income-desk/
> Repo: https://github.com/nitinblue/income-desk
> Goal: Get income-desk in front of the right traders and developers

---

## Milestone 1: Foundation (Do This Week)

**Status: 90% complete**

- [x] Package published on PyPI (v0.3.0)
- [x] GitHub repo public with README, LICENSE, CONTRIBUTING
- [x] GitHub topics set (10 topics)
- [x] Issue templates + labels created
- [x] Discussions enabled
- [x] Branch protection on main
- [x] CI/CD workflow (GitHub Actions)
- [ ] **Publish v0.3.1** with keywords/classifiers (need new PyPI token)
- [ ] **Test `pip install income-desk` on a clean machine** — verify the install-to-first-analysis experience works
- [ ] **Scan git history for secrets** — `git log --all -p | findstr "client_secret refresh_token api_key"`
- [ ] **Record a 2-minute terminal demo** — install → `income-desk --demo` → regime → rank → validate → audit (use asciinema or screen recording)

---

## Milestone 2: Launch Posts (Week 1-2)

One post per platform, spaced 2-3 days apart. Each post is standalone — different angle for different audience.

### Post 1: r/thetagang (your core audience)
- [ ] **Draft and post**
- Title: "I built an open-source income desk that says NO to 90% of trades — here's why that's the point"
- Content: Show the live session where everything was blocked on a bad day. The GLD IC that passed ranking but Kelly vetoed. The crash sentinel showing ORANGE. "The most valuable thing the system did was say no."
- Include: `pip install income-desk` + terminal screenshot
- Tone: Trader talking to traders, not developer talking to developers

### Post 2: r/options (broader options audience)
- [ ] **Draft and post**
- Title: "Free tool: Does your iron condor actually make money after fees? 10-check profitability gate for small accounts"
- Content: Focus on the validation gate — commission drag, fill quality, POP, margin efficiency. Show how a $0.50 credit IC on a $35K account is a guaranteed loser after fees.
- Include: Validation output screenshot

### Post 3: r/algotrading (developer audience)
- [ ] **Draft and post**
- Title: "Open-source options trading intelligence with HMM regime detection, Kelly sizing, and 6 broker integrations"
- Content: Technical angle — HMM for regime, pure functions, pluggable broker ABCs, trust framework. Architecture diagram. 2300+ tests.
- Include: Code sample showing the full pipeline

### Post 4: Hacker News — Show HN
- [ ] **Draft and post**
- Title: "Show HN: income-desk — systematic options trading for $30K accounts (no backtesting)"
- Content: 1 paragraph pitch + link to repo. HN loves "no backtesting" contrarian takes.
- Best time: Tuesday-Thursday, 9-11 AM ET

### Post 5: Twitter/X thread
- [ ] **Draft and post**
- Thread (5-7 tweets):
  1. "I built a trading system that says NO to 90% of trades. Here's why that's the most important feature."
  2. Show regime detection output (QQQ R4 = NO TRADE)
  3. Show validation gate (10 checks, BLOCKED)
  4. Show Kelly vetoing despite GO verdict
  5. "The system learned from real outcomes, not backtests. pip install income-desk"
  6. Link to repo
- Tag: #fintwit #thetagang #python #algotrading

---

## Milestone 3: Awesome Lists & Directories (Week 2-3)

Submit PRs to get listed in curated directories:

- [ ] **awesome-quant** — https://github.com/wilsonfreitas/awesome-quant — PR to add under "Trading / Options"
- [ ] **awesome-python** — https://github.com/vinta/awesome-python — PR under "Finance"
- [ ] **awesome-algorithmic-trading** — search GitHub for relevant lists, submit PRs
- [ ] **PythonRepo.com** — submit package for listing
- [ ] **LibHunt** — https://python.libhunt.com/ — submit for indexing

---

## Milestone 4: Content & SEO (Month 1-2)

Long-form content that ranks on Google and drives ongoing traffic:

### Blog Posts (publish on Medium + Dev.to + personal blog)

- [ ] **"Why I Don't Backtest — And Why You Shouldn't Either"**
  - Contrarian angle drives discussion and shares
  - Explain forward testing philosophy
  - Show the calibrate_weights() learning loop
  - CTA: `pip install income-desk --demo`

- [ ] **"The Trust Problem in Trading Tools"**
  - Every tool says "POP 72%" — but how much should you trust that number?
  - Introduce the 3-dimensional trust framework
  - Show UNRELIABLE vs HIGH trust outputs
  - Unique angle nobody else has written about

- [ ] **"How a $35K Account Survived the March 2026 Selloff"**
  - Real story using income-desk crash sentinel
  - Show ORANGE signal, 100% cash decision, recovery deployment
  - This is the kind of content that gets bookmarked and shared

- [ ] **"6 Brokers, 1 Interface: How income-desk Standardizes Options Trading"**
  - For the developer audience
  - Show the MarketDataProvider ABC, field mapping pattern
  - "170 lines to add any broker"
  - CTA: contribute a broker integration

### Video (YouTube)

- [ ] **5-minute demo: "From Install to First Trade"**
  - `pip install income-desk` → `income-desk --demo` → full workflow
  - Show regime detection, validation, Kelly, audit
  - Keep it fast, no fluff

- [ ] **10-minute deep dive: "The Crash Playbook"**
  - Walk through docs/CRASH_PLAYBOOK.md with real data
  - Show sentinel ORANGE → RED → BLUE transition
  - How the system scales sizing during recovery

---

## Milestone 5: Community Building (Month 2-3)

- [ ] **GitHub Discussions** — answer questions, post weekly "What did income-desk say today?" regime scan
- [ ] **Create "good first issue" tickets** — broker integrations (Webull, E*Trade) are perfect for contributors
- [ ] **Weekly regime report** — post on Twitter/Reddit: "income-desk regime scan: SPY R2, QQQ R4, GLD R1. System says: sit on hands."
- [ ] **Discord/Slack** — create if Discussions grows beyond 50 active users
- [ ] **Newsletter** — weekly "Income Desk Brief" — 3 bullets: regime status, best candidate, trust score

---

## Milestone 6: Partnerships & Integrations (Month 3-6)

- [ ] **TastyTrade community** — they love third-party tools built on their API
- [ ] **Alpaca community** — income-desk is one of few options-focused tools on Alpaca
- [ ] **QuantConnect** — mention income-desk as complementary (regime detection → strategy selection)
- [ ] **Trading podcasts** — pitch the "no backtesting" angle to Options Action, Theta Gang podcast
- [ ] **Financial Python newsletter** — get featured

---

## Tracking Metrics

| Metric | Week 1 | Month 1 | Month 3 | Month 6 |
|--------|--------|---------|---------|---------|
| PyPI downloads/week | 10 | 100 | 500 | 2000 |
| GitHub stars | 5 | 50 | 200 | 500 |
| GitHub forks | 0 | 5 | 20 | 50 |
| Contributors | 1 | 2 | 5 | 10 |
| Discord/Discussion users | 0 | 10 | 50 | 200 |
| Blog post views | 0 | 500 | 5000 | 20000 |

Track weekly: `pip` download stats at https://pypistats.org/packages/income-desk

---

## Quick Reference: Key Links

| What | URL |
|------|-----|
| PyPI | https://pypi.org/project/income-desk/ |
| GitHub | https://github.com/nitinblue/income-desk |
| Discussions | https://github.com/nitinblue/income-desk/discussions |
| Issues | https://github.com/nitinblue/income-desk/issues |
| Download stats | https://pypistats.org/packages/income-desk |
| Trust Framework doc | docs/TRUST_FRAMEWORK.md |
| Crash Playbook | docs/CRASH_PLAYBOOK.md |
| Data Interfaces | docs/DATA_INTERFACES.md |
