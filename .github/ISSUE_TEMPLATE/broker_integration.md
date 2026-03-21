---
name: Broker Integration Request
about: Request support for a new broker
title: "[BROKER] "
labels: broker-integration
assignees: ''
---

**Broker name**
[e.g., Webull, E*Trade, Fidelity]

**Market**
- [ ] US
- [ ] India
- [ ] Other: ___

**Does it have a public API?**
Link to documentation.

**Python SDK available?**
Link to PyPI package or GitHub.

**What data does the API provide?**
- [ ] Option chains (strikes, expirations)
- [ ] Real-time quotes (bid/ask)
- [ ] Greeks (delta, gamma, theta, vega)
- [ ] IV rank / IV percentile
- [ ] Account balance / buying power
- [ ] Order placement

**Estimated integration effort**
MA needs ~170 lines of field mapping per broker. If you can provide sample API responses, we can estimate more precisely.
