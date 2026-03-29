---
name: benchmarking_report
description: Generate calibration report from trade prediction/outcome data
broker: simulated
universe: us_large_cap
risk_profile: moderate
---

# Benchmarking Report

## Phase 1: Calibration

### Step: Run Benchmark
workflow: run_benchmark
inputs:
  predictions_source: file
  predictions_path: data/predictions.json
  outcomes_source: file
  outcomes_path: data/outcomes.json
  period: 2026-Q1
