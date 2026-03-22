"""Demo portfolio for learning market_analyzer."""
from income_desk.demo.portfolio import (
    DemoPortfolio, DemoPosition,
    create_demo_portfolio, load_demo_portfolio, save_demo_portfolio,
    add_demo_position, close_demo_position, get_demo_summary,
    DEMO_CAPITAL,
)
from income_desk.demo.trader import (
    TraderReport,
    run_trader,
    run_us_trader,
    run_india_trader,
    print_trader_report,
)

__all__ = [
    "DemoPortfolio",
    "DemoPosition",
    "create_demo_portfolio",
    "load_demo_portfolio",
    "save_demo_portfolio",
    "add_demo_position",
    "close_demo_position",
    "get_demo_summary",
    "DEMO_CAPITAL",
    "TraderReport",
    "run_trader",
    "run_us_trader",
    "run_india_trader",
    "print_trader_report",
]
