"""Option strategy recommendations — horizon-specific structure selection."""

from income_desk.opportunity.option_plays.zero_dte import assess_zero_dte
from income_desk.opportunity.option_plays.leap import assess_leap
from income_desk.opportunity.option_plays.earnings import assess_earnings_play
from income_desk.opportunity.option_plays.calendar import assess_calendar
from income_desk.opportunity.option_plays.diagonal import assess_diagonal
from income_desk.opportunity.option_plays.iron_condor import assess_iron_condor
from income_desk.opportunity.option_plays.iron_butterfly import assess_iron_butterfly
from income_desk.opportunity.option_plays.ratio_spread import assess_ratio_spread

__all__ = [
    "assess_zero_dte",
    "assess_leap",
    "assess_earnings_play",
    "assess_calendar",
    "assess_diagonal",
    "assess_iron_condor",
    "assess_iron_butterfly",
    "assess_ratio_spread",
]
