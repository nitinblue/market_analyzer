"""Demo portfolio for learning market_analyzer."""
from market_analyzer.demo.portfolio import (
    DemoPortfolio, DemoPosition,
    create_demo_portfolio, load_demo_portfolio, save_demo_portfolio,
    add_demo_position, close_demo_position, get_demo_summary,
    DEMO_CAPITAL,
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
]
