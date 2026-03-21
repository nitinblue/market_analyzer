"""Tests for setup wizard components (non-interactive)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


class TestSetupImport:
    def test_import_setup_module(self):
        """Setup module imports cleanly."""
        from market_analyzer.cli._setup import run_setup_wizard
        assert callable(run_setup_wizard)

    def test_all_public_functions_importable(self):
        """All exported helpers import without error."""
        from market_analyzer.cli._setup import (
            run_setup_wizard,
            _setup_free,
            _setup_defaults,
            _setup_ibkr_info,
            _setup_schwab_info,
            _setup_tastytrade,
            _setup_zerodha,
        )
        for fn in (
            run_setup_wizard,
            _setup_free,
            _setup_defaults,
            _setup_ibkr_info,
            _setup_schwab_info,
            _setup_tastytrade,
            _setup_zerodha,
        ):
            assert callable(fn)


class TestSetupFree:
    def test_setup_free_prints_no_broker_message(self, tmp_path, capsys):
        """_setup_free prints info about free data mode."""
        from market_analyzer.cli._setup import _setup_free
        _setup_free(tmp_path)
        out = capsys.readouterr().out
        assert "yfinance" in out
        assert "Free Data Mode" in out

    def test_setup_free_does_not_create_files(self, tmp_path):
        """_setup_free does not write any files."""
        from market_analyzer.cli._setup import _setup_free
        _setup_free(tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestSetupDefaults:
    def test_creates_settings_yaml_when_absent(self, tmp_path):
        """_setup_defaults creates settings.yaml in a fresh config dir."""
        from market_analyzer.cli._setup import _setup_defaults
        _setup_defaults(tmp_path)
        settings = tmp_path / "settings.yaml"
        assert settings.exists()

    def test_settings_yaml_has_expected_keys(self, tmp_path):
        """Created settings.yaml contains trading and cache sections."""
        import yaml
        from market_analyzer.cli._setup import _setup_defaults
        _setup_defaults(tmp_path)
        data = yaml.safe_load((tmp_path / "settings.yaml").read_text())
        assert "trading" in data
        assert "cache" in data
        assert "default_tickers" in data["trading"]

    def test_skips_overwrite_on_no_input(self, tmp_path, monkeypatch):
        """_setup_defaults keeps existing file when user declines overwrite."""
        import yaml
        from market_analyzer.cli._setup import _setup_defaults

        # Create an existing settings file with custom content
        settings = tmp_path / "settings.yaml"
        original = {"my_key": "original_value"}
        settings.write_text(yaml.dump(original))

        monkeypatch.setattr("builtins.input", lambda _: "n")
        _setup_defaults(tmp_path)

        data = yaml.safe_load(settings.read_text())
        assert data == original

    def test_overwrites_on_yes_input(self, tmp_path, monkeypatch):
        """_setup_defaults overwrites existing file when user confirms."""
        import yaml
        from market_analyzer.cli._setup import _setup_defaults

        settings = tmp_path / "settings.yaml"
        settings.write_text(yaml.dump({"old": True}))

        monkeypatch.setattr("builtins.input", lambda _: "y")
        _setup_defaults(tmp_path)

        data = yaml.safe_load(settings.read_text())
        assert "trading" in data


class TestSetupIBKRSchwabInfo:
    def test_ibkr_info_prints_steps(self, capsys):
        """_setup_ibkr_info prints install/setup steps."""
        from market_analyzer.cli._setup import _setup_ibkr_info
        _setup_ibkr_info()
        out = capsys.readouterr().out
        assert "ib_insync" in out
        assert "TWS" in out

    def test_schwab_info_prints_steps(self, capsys):
        """_setup_schwab_info prints install/setup steps."""
        from market_analyzer.cli._setup import _setup_schwab_info
        _setup_schwab_info()
        out = capsys.readouterr().out
        assert "schwab-py" in out
        assert "OAuth" in out


class TestSetupZerodha:
    def test_zerodha_saves_env_file(self, tmp_path, monkeypatch):
        """_setup_zerodha writes Zerodha keys to .env file."""
        from market_analyzer.cli._setup import _setup_zerodha

        answers = iter(["MY_API_KEY", "MY_API_SECRET"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))

        _setup_zerodha(tmp_path)

        env_path = tmp_path / ".env"
        assert env_path.exists()
        content = env_path.read_text()
        assert "ZERODHA_API_KEY=MY_API_KEY" in content
        assert "ZERODHA_API_SECRET=MY_API_SECRET" in content

    def test_zerodha_aborts_on_empty_input(self, tmp_path, monkeypatch, capsys):
        """_setup_zerodha prints error when fields are empty."""
        from market_analyzer.cli._setup import _setup_zerodha

        answers = iter(["", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))

        _setup_zerodha(tmp_path)

        out = capsys.readouterr().out
        assert "Error" in out
        assert not (tmp_path / ".env").exists()

    def test_zerodha_updates_existing_env(self, tmp_path, monkeypatch):
        """_setup_zerodha updates existing keys without duplicates."""
        from market_analyzer.cli._setup import _setup_zerodha

        env_path = tmp_path / ".env"
        env_path.write_text("ZERODHA_API_KEY=OLD_KEY\nOTHER_VAR=keep\n")

        answers = iter(["NEW_KEY", "NEW_SECRET"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))

        _setup_zerodha(tmp_path)

        content = env_path.read_text()
        assert "ZERODHA_API_KEY=NEW_KEY" in content
        assert "ZERODHA_API_KEY=OLD_KEY" not in content
        assert "OTHER_VAR=keep" in content


class TestSetupTastyTradeYaml:
    def test_tastytrade_saves_yaml(self, tmp_path, monkeypatch):
        """_setup_tastytrade writes broker.yaml with credentials."""
        import yaml
        from market_analyzer.cli._setup import _setup_tastytrade

        # Provide: client_secret, refresh_token, account_type, skip connection test
        answers = iter(["MY_SECRET", "MY_TOKEN", "live"])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))

        # Mock connection test so it doesn't actually try to connect
        with patch("market_analyzer.cli._setup._test_tastytrade_connection"):
            _setup_tastytrade(tmp_path)

        yaml_path = tmp_path / "broker.yaml"
        assert yaml_path.exists()
        data = yaml.safe_load(yaml_path.read_text())
        assert data["broker"]["live"]["client_secret"] == "MY_SECRET"
        assert data["broker"]["data"]["client_secret"] == "MY_SECRET"

    def test_tastytrade_aborts_on_empty_credentials(self, tmp_path, monkeypatch, capsys):
        """_setup_tastytrade prints error when credentials are empty."""
        from market_analyzer.cli._setup import _setup_tastytrade

        answers = iter(["", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))

        _setup_tastytrade(tmp_path)

        out = capsys.readouterr().out
        assert "Error" in out
        assert not (tmp_path / "broker.yaml").exists()


class TestSessionFindsWizardYaml:
    def test_find_config_file_finds_broker_yaml(self, tmp_path, monkeypatch):
        """_find_config_file picks up broker.yaml written by the setup wizard."""
        from market_analyzer.broker.tastytrade.session import TastyTradeBrokerSession

        # Simulate ~/.market_analyzer/broker.yaml
        ma_dir = tmp_path / ".market_analyzer"
        ma_dir.mkdir()
        broker_yaml = ma_dir / "broker.yaml"
        broker_yaml.write_text("broker:\n  live:\n    client_secret: x\n    refresh_token: y\n")

        # Patch Path.home() to return tmp_path
        monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

        session = TastyTradeBrokerSession(config_path="nonexistent_file.yaml")
        found = session._find_config_file()
        assert found is not None
        assert found == broker_yaml


class TestWizardCLICommand:
    def test_do_wizard_calls_run_setup_wizard(self, monkeypatch):
        """do_wizard delegates to run_setup_wizard."""
        called = []

        def fake_wizard():
            called.append(True)

        monkeypatch.setattr(
            "market_analyzer.cli._setup.run_setup_wizard", fake_wizard
        )
        from market_analyzer.cli.interactive import AnalyzerCLI
        cli = AnalyzerCLI()
        cli.do_wizard("")
        assert called


class TestMainSetupFlag:
    def test_setup_flag_runs_wizard_and_returns(self, monkeypatch):
        """--setup flag runs wizard then exits without starting REPL."""
        called = []

        def fake_wizard():
            called.append(True)

        monkeypatch.setattr(
            "market_analyzer.cli._setup.run_setup_wizard", fake_wizard
        )
        monkeypatch.setattr("sys.argv", ["analyzer-cli", "--setup"])

        from market_analyzer.cli import interactive
        # Reload to pick up monkeypatched argv
        with patch("market_analyzer.cli._setup.run_setup_wizard", fake_wizard):
            with patch("market_analyzer.cli.interactive.AnalyzerCLI") as mock_cli:
                import importlib
                # Call main directly — it should call wizard and return before cmdloop
                interactive.main()
                # If wizard ran and returned, cmdloop should NOT have been called
                mock_cli.return_value.cmdloop.assert_not_called()
