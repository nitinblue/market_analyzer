"""First-time setup wizard for market_analyzer."""
from __future__ import annotations

import os
from pathlib import Path


def run_setup_wizard() -> None:
    """Interactive setup wizard. Guides through broker selection + credential storage."""

    config_dir = Path.home() / ".market_analyzer"
    config_dir.mkdir(exist_ok=True)

    print("\n" + "=" * 50)
    print("  market_analyzer — First Time Setup")
    print("=" * 50)
    print()

    # Step 1: Broker selection
    print("Which broker do you use?")
    print("  1. TastyTrade (US options — recommended)")
    print("  2. Zerodha (India NSE/NFO)")
    print("  3. Interactive Brokers (template — requires manual setup)")
    print("  4. Schwab (template — requires manual setup)")
    print("  5. None — use free data only (yfinance)")
    print()

    choice = input("Enter choice [1-5]: ").strip()

    if choice == "1":
        _setup_tastytrade(config_dir)
    elif choice == "2":
        _setup_zerodha(config_dir)
    elif choice == "3":
        _setup_ibkr_info()
    elif choice == "4":
        _setup_schwab_info()
    elif choice == "5":
        _setup_free(config_dir)
    else:
        print(f"Invalid choice: {choice!r}")
        return

    # Step 2: Default settings
    print()
    _setup_defaults(config_dir)

    print()
    print("=" * 50)
    print("  Setup complete!")
    print("=" * 50)
    print()
    print("Next steps:")
    print("  analyzer-cli --broker     # Start CLI with broker")
    print("  analyzer-cli              # Start CLI (free data only)")
    print()


def _setup_tastytrade(config_dir: Path) -> None:
    """TastyTrade broker setup."""
    print()
    print("TastyTrade Setup")
    print("-" * 30)
    print()
    print("You need a TastyTrade API client secret and refresh token.")
    print("Get these from: https://developer.tastytrade.com/")
    print()

    client_secret = input("Client secret: ").strip()
    refresh_token = input("Refresh token: ").strip()

    if not client_secret or not refresh_token:
        print("Error: Both client secret and refresh token are required.")
        return

    # Ask account type
    acct_type = input("Account type [live/paper]: ").strip().lower()
    if acct_type not in ("live", "paper"):
        acct_type = "live"

    # Save to YAML
    yaml_path = config_dir / "broker.yaml"

    try:
        import yaml
    except ImportError:
        print("Warning: PyYAML not installed — saving as plain text fallback")
        _save_tastytrade_env(config_dir, client_secret, refresh_token, acct_type)
        return

    config = {
        "broker": {
            "live": {
                "client_secret": client_secret,
                "refresh_token": refresh_token if acct_type == "live" else "",
            },
            "paper": {
                "client_secret": client_secret,
                "refresh_token": refresh_token if acct_type == "paper" else "",
            },
            "data": {
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            },
        }
    }

    with open(yaml_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    # Set restrictive permissions
    try:
        yaml_path.chmod(0o600)
    except Exception:
        pass

    print(f"\nSaved to {yaml_path}")

    # Test connection
    print("\nTesting connection...", end=" ", flush=True)
    _test_tastytrade_connection(client_secret, refresh_token, acct_type)


def _save_tastytrade_env(
    config_dir: Path,
    client_secret: str,
    refresh_token: str,
    acct_type: str,
) -> None:
    """Fallback: save TastyTrade creds to .env when yaml not available."""
    env_path = config_dir / ".env"
    lines = list(env_path.read_text().splitlines()) if env_path.exists() else []

    env_vars: dict[str, str] = {
        "TASTYTRADE_CLIENT_SECRET_DATA": client_secret,
        "TASTYTRADE_REFRESH_TOKEN_DATA": refresh_token,
    }
    if acct_type == "paper":
        env_vars["TASTYTRADE_CLIENT_SECRET_PAPER"] = client_secret
        env_vars["TASTYTRADE_REFRESH_TOKEN_PAPER"] = refresh_token
    else:
        env_vars["TASTYTRADE_CLIENT_SECRET_LIVE"] = client_secret
        env_vars["TASTYTRADE_REFRESH_TOKEN_LIVE"] = refresh_token

    for key, val in env_vars.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={val}"
                found = True
                break
        if not found:
            lines.append(f"{key}={val}")

    env_path.write_text("\n".join(lines) + "\n")
    try:
        env_path.chmod(0o600)
    except Exception:
        pass
    print(f"\nSaved to {env_path}")


def _test_tastytrade_connection(
    client_secret: str,
    refresh_token: str,
    acct_type: str,
) -> None:
    """Attempt a live broker connection with the provided credentials."""
    suffix = acct_type.upper()
    os.environ[f"TASTYTRADE_CLIENT_SECRET_{suffix}"] = client_secret
    os.environ[f"TASTYTRADE_REFRESH_TOKEN_{suffix}"] = refresh_token
    os.environ["TASTYTRADE_CLIENT_SECRET_DATA"] = client_secret
    os.environ["TASTYTRADE_REFRESH_TOKEN_DATA"] = refresh_token

    try:
        from market_analyzer.cli._broker import connect_broker

        md, mm, acct, wl = connect_broker(is_paper=(acct_type == "paper"))

        if acct is not None:
            try:
                bal = acct.get_balance()
                print(f"Connected! Account NLV: ${bal.net_liquidating_value:,.2f}")
            except Exception:
                print("Connected! (balance unavailable)")
        else:
            print("Connection failed. Check your credentials.")
    except Exception as e:
        print(f"Failed: {e}")
        print("Credentials saved — you can fix them in ~/.market_analyzer/broker.yaml")


def _setup_zerodha(config_dir: Path) -> None:
    """Zerodha broker setup."""
    print()
    print("Zerodha Setup")
    print("-" * 30)
    print()
    print("You need a Zerodha Kite API key and secret.")
    print("Get these from: https://kite.trade/")
    print()

    api_key = input("API Key: ").strip()
    api_secret = input("API Secret: ").strip()

    if not api_key or not api_secret:
        print("Error: Both API key and secret are required.")
        return

    # Save to env file
    env_path = config_dir / ".env"
    lines = list(env_path.read_text().splitlines()) if env_path.exists() else []

    env_vars = {
        "ZERODHA_API_KEY": api_key,
        "ZERODHA_API_SECRET": api_secret,
    }

    for key, val in env_vars.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={val}"
                found = True
                break
        if not found:
            lines.append(f"{key}={val}")

    env_path.write_text("\n".join(lines) + "\n")

    try:
        env_path.chmod(0o600)
    except Exception:
        pass

    print(f"\nSaved to {env_path}")
    print("Note: Zerodha requires daily login. Run 'analyzer-cli --broker' to connect.")


def _setup_ibkr_info() -> None:
    """IBKR info — not automated."""
    print()
    print("Interactive Brokers")
    print("-" * 30)
    print()
    print("IBKR requires TWS or IB Gateway running locally.")
    print("MA provides a template adapter — you'll need to customize it.")
    print()
    print("Steps:")
    print("  1. pip install ib_insync")
    print("  2. Start TWS or IB Gateway on port 7497")
    print("  3. Copy and customize: market_analyzer/adapters/ibkr_adapter.py")
    print("  4. Wire into MarketAnalyzer via Python code")
    print()
    print("See: docs/DATA_INTERFACES.md for full guide")


def _setup_schwab_info() -> None:
    """Schwab info — not automated."""
    print()
    print("Charles Schwab")
    print("-" * 30)
    print()
    print("Schwab API uses OAuth2 authentication.")
    print("MA provides a template adapter — you'll need to customize it.")
    print()
    print("Steps:")
    print("  1. pip install schwab-py")
    print("  2. Register at https://developer.schwab.com/")
    print("  3. Copy and customize: market_analyzer/adapters/schwab_adapter.py")
    print("  4. Wire into MarketAnalyzer via Python code")
    print()
    print("See: docs/DATA_INTERFACES.md for full guide")


def _setup_free(config_dir: Path) -> None:
    """No broker — free data only."""
    print()
    print("Free Data Mode")
    print("-" * 30)
    print()
    print("market_analyzer works without any broker using yfinance (free).")
    print("You get: regime detection, technicals, screening, ranking.")
    print("You don't get: real-time quotes, Greeks, IV rank, execution quality.")
    print()
    print("Trust level: LOW-MEDIUM (fit for research and screening)")
    print("To upgrade: run 'wizard' again and choose a broker.")


def _setup_defaults(config_dir: Path) -> None:
    """Write default settings.yaml if absent (or on user request)."""
    settings_path = config_dir / "settings.yaml"

    if settings_path.exists():
        print(f"Settings already exist at {settings_path}")
        overwrite = input("Overwrite with defaults? [y/N]: ").strip().lower()
        if overwrite != "y":
            return

    try:
        import yaml
    except ImportError:
        print("Warning: PyYAML not installed — skipping settings.yaml creation")
        return

    defaults = {
        "cache": {
            "staleness_hours": 18.0,
        },
        "trading": {
            "default_tickers": ["SPY", "QQQ", "IWM", "GLD", "TLT"],
            "account_size": 35000,
            "max_positions": 5,
            "max_risk_pct": 0.25,
            "drawdown_halt_pct": 0.10,
        },
    }

    with open(settings_path, "w") as f:
        yaml.dump(defaults, f, default_flow_style=False)

    print(f"Default settings saved to {settings_path}")
