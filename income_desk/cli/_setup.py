"""First-time setup wizard for market_analyzer."""
from __future__ import annotations

import os
from pathlib import Path


def run_setup_wizard() -> None:
    """Interactive setup wizard. Guides through broker selection + credential storage."""

    config_dir = Path.home() / ".income_desk"
    config_dir.mkdir(exist_ok=True)

    print("\n" + "=" * 50)
    print("  market_analyzer — First Time Setup")
    print("=" * 50)
    print()

    # Step 1: Broker selection
    print("Which broker do you use?")
    print("  1. TastyTrade (US options — recommended)")
    print("  2. Zerodha (India NSE/NFO via Kite Connect)")
    print("  3. Dhan (India NSE/NFO — free tier, Greeks included)")
    print("  4. Alpaca (US stocks + options — free tier, no funding required)")
    print("  5. Interactive Brokers (requires TWS/Gateway running locally)")
    print("  6. Schwab (requires OAuth2 setup)")
    print("  7. None — use free data only (yfinance)")
    print()

    choice = input("Enter choice [1-7]: ").strip()

    if choice == "1":
        _setup_tastytrade(config_dir)
    elif choice == "2":
        _setup_zerodha(config_dir)
    elif choice == "3":
        _setup_dhan(config_dir)
    elif choice == "4":
        _setup_alpaca(config_dir)
    elif choice == "5":
        _setup_ibkr(config_dir)
    elif choice == "6":
        _setup_schwab(config_dir)
    elif choice == "7":
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
        from income_desk.cli._broker import connect_broker

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
        print("Credentials saved — you can fix them in ~/.income_desk/broker.yaml")


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


def _setup_dhan(config_dir: Path) -> None:
    """Dhan broker setup — India NSE/NFO with native Greeks."""
    print()
    print("Dhan Setup")
    print("-" * 30)
    print()
    print("Dhan provides option chains with full Greeks (delta/gamma/theta/vega).")
    print("Free API — no monthly charges. 20K requests/day.")
    print("Get credentials at: https://dhanhq.co/")
    print()

    client_id = input("Client ID: ").strip()
    access_token = input("Access Token: ").strip()

    if not client_id or not access_token:
        print("Error: Both Client ID and Access Token are required.")
        return

    # Save to broker.yaml
    yaml_path = config_dir / "broker.yaml"
    try:
        import yaml
    except ImportError:
        print("Warning: PyYAML not installed — saving as env vars fallback")
        _save_env_vars(config_dir, {
            "DHAN_CLIENT_ID": client_id,
            "DHAN_ACCESS_TOKEN": access_token,
        })
        return

    # Load existing config if present
    cfg: dict = {}
    if yaml_path.exists():
        try:
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            pass

    cfg["dhan"] = {
        "client_id": client_id,
        "access_token": access_token,
    }
    cfg["broker_type"] = "dhan"

    with open(yaml_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)

    try:
        yaml_path.chmod(0o600)
    except Exception:
        pass

    print(f"\nSaved to {yaml_path}")

    # Test connection
    print("\nTesting connection...", end=" ", flush=True)
    try:
        from income_desk.broker.dhan import connect_dhan
        md, mm, acct, _ = connect_dhan(client_id, access_token)
        if acct is not None:
            bal = acct.get_balance()
            print(f"Connected! Available: ₹{bal.cash_balance:,.0f}")
        else:
            print("Connected (account info unavailable)")
    except ImportError:
        print("dhanhq not installed.")
        print("Run: pip install dhanhq  or: pip install 'market-analyzer[dhan]'")
    except Exception as e:
        print(f"Failed: {e}")
        print("Credentials saved — check them in ~/.income_desk/broker.yaml")


def _setup_alpaca(config_dir: Path) -> None:
    """Alpaca broker setup — free tier, no funding required."""
    print()
    print("Alpaca Free Setup")
    print("-" * 30)
    print()
    print("Get free API keys at: https://app.alpaca.markets/signup")
    print("(No deposit or funding required for paper trading)")
    print()

    key = input("API Key ID: ").strip()
    secret = input("API Secret: ").strip()

    if not key or not secret:
        print("Error: Both API Key and API Secret are required.")
        return

    paper = input("Use paper trading? [Y/n]: ").strip().lower() != "n"

    # Save to broker.yaml
    yaml_path = config_dir / "broker.yaml"
    try:
        import yaml
    except ImportError:
        print("Warning: PyYAML not installed — saving as env vars fallback")
        _save_env_vars(config_dir, {
            "ALPACA_API_KEY": key,
            "ALPACA_API_SECRET": secret,
        })
        return

    # Load existing config if present
    cfg: dict = {}
    if yaml_path.exists():
        try:
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            pass

    cfg["alpaca"] = {
        "api_key": key,
        "api_secret": secret,
        "paper": paper,
    }

    with open(yaml_path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False)

    try:
        yaml_path.chmod(0o600)
    except Exception:
        pass

    print(f"\nSaved to {yaml_path}")

    # Test connection
    print("\nTesting connection...", end=" ", flush=True)
    try:
        from income_desk.broker.alpaca import connect_alpaca
        md, mm, acct, _ = connect_alpaca(key, secret, paper=paper)
        if acct is not None:
            bal = acct.get_balance()
            print(f"Connected! Account: ${bal.net_liquidating_value:,.2f}")
        else:
            print("Connected (account info unavailable)")
    except ImportError:
        print("alpaca-py not installed.")
        print("Run: pip install 'market-analyzer[alpaca]'")
    except Exception as e:
        print(f"Failed: {e}")
        print("Credentials saved — check them in ~/.income_desk/broker.yaml")


def _setup_ibkr(config_dir: Path) -> None:
    """IBKR broker setup."""
    print()
    print("Interactive Brokers Setup")
    print("-" * 30)
    print()
    print("IBKR requires TWS or IB Gateway running locally.")
    print()
    print("Steps to complete before continuing:")
    print("  1. pip install 'market-analyzer[ibkr]'")
    print("  2. Start TWS or IB Gateway (paper: port 7497, live: port 7496)")
    print("  3. In TWS: File > Global Configuration > API > Settings")
    print("     - Enable 'Enable ActiveX and Socket Clients'")
    print("     - Note the port number")
    print()

    host = input("TWS/Gateway host [127.0.0.1]: ").strip() or "127.0.0.1"
    port_str = input("Port [7497 for paper, 7496 for live]: ").strip() or "7497"
    client_id_str = input("Client ID [1]: ").strip() or "1"

    try:
        port = int(port_str)
        client_id = int(client_id_str)
    except ValueError:
        print("Invalid port or client_id — must be integers.")
        return

    # Save to broker.yaml
    yaml_path = config_dir / "broker.yaml"
    try:
        import yaml
        cfg: dict = {}
        if yaml_path.exists():
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f) or {}
        cfg["ibkr"] = {"host": host, "port": port, "client_id": client_id}
        with open(yaml_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
        try:
            yaml_path.chmod(0o600)
        except Exception:
            pass
        print(f"\nSaved to {yaml_path}")
    except ImportError:
        print("PyYAML not installed — config not saved.")

    # Test connection
    print("\nTesting connection...", end=" ", flush=True)
    try:
        from income_desk.broker.ibkr import connect_ibkr
        md, _, acct, _ = connect_ibkr(host=host, port=port, client_id=client_id)
        if acct is not None:
            bal = acct.get_balance()
            print(f"Connected! NLV: ${bal.net_liquidating_value:,.2f}")
        else:
            print("Connected!")
    except ImportError:
        print("ib_insync not installed.")
        print("Run: pip install 'market-analyzer[ibkr]'")
    except ConnectionError as e:
        print(f"Failed: {e}")
        print("Ensure TWS/IB Gateway is running and API access is enabled.")
    except Exception as e:
        print(f"Failed: {e}")


def _setup_schwab(config_dir: Path) -> None:
    """Schwab broker setup with OAuth2."""
    print()
    print("Charles Schwab Setup")
    print("-" * 30)
    print()
    print("Requirements:")
    print("  1. pip install 'market-analyzer[schwab]'")
    print("  2. Register app at: https://developer.schwab.com/")
    print("     - Create an app to get App Key + App Secret")
    print("     - Set callback URL to: https://127.0.0.1")
    print()

    key = input("App Key: ").strip()
    secret = input("App Secret: ").strip()

    if not key or not secret:
        print("Error: Both App Key and App Secret are required.")
        return

    callback = input("Callback URL [https://127.0.0.1]: ").strip() or "https://127.0.0.1"
    token_path = str(config_dir / "schwab_token.json")

    # Save to broker.yaml
    yaml_path = config_dir / "broker.yaml"
    try:
        import yaml
        cfg: dict = {}
        if yaml_path.exists():
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f) or {}
        cfg["schwab"] = {
            "app_key": key,
            "app_secret": secret,
            "callback_url": callback,
            "token_path": token_path,
        }
        with open(yaml_path, "w") as f:
            yaml.dump(cfg, f, default_flow_style=False)
        try:
            yaml_path.chmod(0o600)
        except Exception:
            pass
        print(f"\nSaved to {yaml_path}")
    except ImportError:
        print("PyYAML not installed — config not saved.")

    # Run OAuth2 flow
    print()
    print("Starting OAuth2 authentication flow...")
    print("(A browser window will open. Log in to Schwab and authorize the app.)")
    print()
    try:
        import schwab  # type: ignore[import]
        schwab.auth.easy_client(
            api_key=key,
            app_secret=secret,
            callback_url=callback,
            token_path=token_path,
        )
        print(f"OAuth token saved to {token_path}")

        # Test connection
        print("\nTesting connection...", end=" ", flush=True)
        from income_desk.broker.schwab import connect_schwab
        md, mm, acct, _ = connect_schwab(key, secret, token_path=token_path)
        if acct is not None:
            bal = acct.get_balance()
            print(f"Connected! NLV: ${bal.net_liquidating_value:,.2f}")
        else:
            print("Connected!")
    except ImportError:
        print("schwab-py not installed.")
        print("Run: pip install 'market-analyzer[schwab]'")
        print()
        print("After installing, run this to complete OAuth setup:")
        print(f"  import schwab")
        print(f"  schwab.auth.easy_client('{key}', '<secret>', '{callback}', '{token_path}')")
    except Exception as e:
        print(f"OAuth setup failed: {e}")
        print("Credentials saved. Re-run setup after fixing the issue.")


# ---------------------------------------------------------------------------
# Backward-compat aliases (old names kept for existing test compatibility)
# ---------------------------------------------------------------------------

def _setup_ibkr_info() -> None:
    """Legacy alias — prints IBKR setup instructions.

    Kept for backward compatibility. New full setup: _setup_ibkr().
    """
    print()
    print("Interactive Brokers")
    print("-" * 30)
    print()
    print("IBKR requires TWS or IB Gateway running locally.")
    print("market_analyzer provides a full broker integration.")
    print()
    print("Steps:")
    print("  1. pip install ib_insync  (or: pip install 'market-analyzer[ibkr]')")
    print("  2. Start TWS or IB Gateway on port 7497 (paper) or 7496 (live)")
    print("  3. Enable API: File > Global Configuration > API > Settings")
    print("     Enable 'Enable ActiveX and Socket Clients'")
    print("  4. Run: analyzer-cli wizard  and choose 'Interactive Brokers'")


def _setup_schwab_info() -> None:
    """Legacy alias — prints Schwab setup instructions.

    Kept for backward compatibility. New full setup: _setup_schwab().
    """
    print()
    print("Charles Schwab")
    print("-" * 30)
    print()
    print("Schwab API uses OAuth2 authentication.")
    print("market_analyzer provides a full broker integration.")
    print()
    print("Steps:")
    print("  1. pip install schwab-py  (or: pip install 'market-analyzer[schwab]')")
    print("  2. Register app at: https://developer.schwab.com/")
    print("  3. Run: analyzer-cli wizard  and choose 'Schwab'")
    print("     (OAuth browser flow will run automatically)")


def _save_env_vars(config_dir: Path, env_vars: dict[str, str]) -> None:
    """Save key=value pairs to ~/.income_desk/.env"""
    env_path = config_dir / ".env"
    lines = list(env_path.read_text().splitlines()) if env_path.exists() else []
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
    print(f"Saved to {env_path}")


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
