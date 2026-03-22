"""Price-based setup detection — directional pattern recognition."""

from income_desk.opportunity.setups.breakout import assess_breakout
from income_desk.opportunity.setups.momentum import assess_momentum
from income_desk.opportunity.setups.mean_reversion import assess_mean_reversion
from income_desk.opportunity.setups.orb import assess_orb

__all__ = [
    "assess_breakout",
    "assess_momentum",
    "assess_mean_reversion",
    "assess_orb",
]
