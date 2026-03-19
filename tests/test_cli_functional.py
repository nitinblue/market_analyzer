"""Smoke tests for the do_validate CLI command."""
import pytest


def test_do_validate_no_args_prints_usage(capsys) -> None:
    """do_validate with no args prints usage without crashing."""
    from market_analyzer.cli.interactive import AnalyzerCLI
    shell = AnalyzerCLI.__new__(AnalyzerCLI)
    shell.do_validate("")
    out = capsys.readouterr().out
    assert "Usage" in out or "validate" in out.lower()


def test_do_validate_invalid_suite_prints_error(capsys) -> None:
    """--suite with unknown value prints error without crashing."""
    from market_analyzer.cli.interactive import AnalyzerCLI
    shell = AnalyzerCLI.__new__(AnalyzerCLI)
    shell.do_validate("SPY --suite bad_value")
    out = capsys.readouterr().out
    assert out  # something printed, did not crash
