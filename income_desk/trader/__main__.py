"""Run the income_desk trader.

Usage:
    python -m income_desk.trader                        # Interactive
    python -m income_desk.trader --all --market=US      # Non-interactive
    python -m income_desk.trader --phase=2 --market=India
"""
from income_desk.trader.trader import main

if __name__ == "__main__":
    main()
