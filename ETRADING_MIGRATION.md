# eTrading Migration Guide: market_analyzer → income_desk

> One-time migration. Replace all imports. No logic changes.

## What Changed

The Python module has been renamed from `market_analyzer` to `income_desk`.

```python
# BEFORE:
from market_analyzer import MarketAnalyzer, DataService
from market_analyzer.broker.tastytrade import connect_tastytrade
from market_analyzer.validation.daily_readiness import run_daily_checks

# AFTER:
from income_desk import MarketAnalyzer, DataService
from income_desk.broker.tastytrade import connect_tastytrade
from income_desk.validation.daily_readiness import run_daily_checks
```

## Migration Steps for eTrading

### Step 1: Find all imports (2 minutes)

```bash
grep -r "from market_analyzer" --include="*.py" -l
grep -r "import market_analyzer" --include="*.py" -l
```

### Step 2: Replace all imports (1 command)

```bash
find . -name "*.py" -not -path "./.venv*" | xargs sed -i 's/from market_analyzer/from income_desk/g'
find . -name "*.py" -not -path "./.venv*" | xargs sed -i 's/import market_analyzer/import income_desk/g'
```

### Step 3: Update hardcoded paths

```bash
find . -name "*.py" -not -path "./.venv*" | xargs sed -i 's/\.market_analyzer/\.income_desk/g'
```

The user config directory changed: `~/.market_analyzer/` → `~/.income_desk/`

### Step 4: Update pip install

```bash
pip install income-desk  # Was: pip install market-analyzer
```

### Step 5: Update any env vars or config referencing old paths

```
# Old paths:
~/.market_analyzer/broker.yaml
~/.market_analyzer/cache/
~/.market_analyzer/models/

# New paths:
~/.income_desk/broker.yaml
~/.income_desk/cache/
~/.income_desk/models/
```

### Step 6: Reinstall

```bash
pip install -e ".[dev]"
```

## What Did NOT Change

- All function signatures: identical
- All model fields: identical
- All CLI commands: identical
- All broker integrations: identical
- All TradeSpec formats: identical
- All 80+ CLI commands: identical

This is a pure rename. Zero logic changes.

## Backward Compatibility

The old `market_analyzer` module no longer exists. There is no compatibility shim. This is a clean break — eTrading should migrate all imports in one PR.
