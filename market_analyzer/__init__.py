"""Market analysis toolkit: regime detection, technicals, phase detection, and opportunity assessment."""

# Config
from market_analyzer.config import (
    CalendarSettings,
    DiagonalSettings,
    ExitSettings,
    IronButterflySettings,
    IronCondorSettings,
    MarketDef,
    MarketSettings,
    RatioSpreadSettings,
    ScreeningSettings,
    Settings,
    StrategySettings,
    get_settings,
)

# Models
from market_analyzer.models.regime import (
    CrossTickerEntry,
    FeatureZScore,
    HMMModelInfo,
    LabelAlignmentDetail,
    RegimeConfig,
    RegimeDistributionEntry,
    RegimeExplanation,
    RegimeHistoryDay,
    RegimeID,
    RegimeResult,
    RegimeTimeSeries,
    RegimeTimeSeriesEntry,
    ResearchReport,
    StateMeansRow,
    TickerResearch,
    TransitionRow,
    TrendDirection,
)
from market_analyzer.models.phase import PhaseID, PhaseResult
from market_analyzer.models.data import DataType, ProviderType, DataRequest, DataResult
from market_analyzer.models.features import FeatureConfig, FeatureInspection
from market_analyzer.models.technicals import TechnicalSnapshot, TechnicalSignal

# New workflow models
from market_analyzer.models.context import InstrumentAvailability, IntermarketDashboard, IntermarketEntry, MarketContext
from market_analyzer.models.instrument import InstrumentAnalysis
from market_analyzer.models.entry import EntryConfirmation, EntryCondition, EntryTriggerType
from market_analyzer.models.strategy import (
    OptionStructure,
    OptionStructureType,
    PositionSize,
    StrategyParameters,
)
from market_analyzer.models.adjustment import (
    AdjustmentAnalysis,
    AdjustmentDecision,
    AdjustmentOption,
    AdjustmentType,
    PositionStatus,
    TestedSide,
)
from market_analyzer.models.exit_plan import (
    AdjustmentTrigger,
    AdjustmentTriggerType,
    ExitPlan,
    ExitReason,
    ExitTarget,
)

# Services
from market_analyzer.service.analyzer import MarketAnalyzer
from market_analyzer.service.regime_service import RegimeService
from market_analyzer.service.technical import TechnicalService
from market_analyzer.service.phase import PhaseService
from market_analyzer.service.fundamental import FundamentalService
from market_analyzer.service.macro import MacroService
from market_analyzer.service.levels import LevelsService
from market_analyzer.service.opportunity import OpportunityService
from market_analyzer.service.black_swan import BlackSwanService
from market_analyzer.service.ranking import TradeRankingService
from market_analyzer.data.service import DataService

# New workflow services
from market_analyzer.service.context import MarketContextService
from market_analyzer.service.instrument import InstrumentAnalysisService
from market_analyzer.service.screening import ScreeningService, ScreenCandidate, ScreeningResult
from market_analyzer.service.entry import EntryService
from market_analyzer.service.strategy import StrategyService
from market_analyzer.service.exit import ExitService
from market_analyzer.service.adjustment import AdjustmentService
from market_analyzer.service.intraday import IntradayService
from market_analyzer.service.option_quotes import OptionQuoteService

# Phase detection
from market_analyzer.phases.detector import PhaseDetector

# Fundamentals
from market_analyzer.models.fundamentals import FundamentalsSnapshot
from market_analyzer.fundamentals.fetch import fetch_fundamentals

# Macro
from market_analyzer.models.macro import MacroCalendar, MacroEvent, MacroEventType
from market_analyzer.macro.calendar import get_macro_calendar

# Macro indicators (bond market, credit, dollar, inflation)
from market_analyzer.macro_indicators import (
    BondMarketIndicator,
    CreditSpreadIndicator,
    DollarStrengthIndicator,
    InflationExpectationIndicator,
    MacroIndicatorDashboard,
    MacroRiskLevel,
    MacroTrend,
    compute_macro_dashboard,
)

# Macro research (scorecards, correlations, regime, sentiment, economics, reports)
from market_analyzer.macro_research import (
    AssetClass,
    AssetScore,
    CorrelationPair,
    EconomicSnapshot,
    IndiaResearchContext,
    MacroRegime,
    MacroResearchReport,
    RESEARCH_ASSETS,
    RegimeClassification,
    SentimentDashboard,
    TrendSignal,
    classify_macro_regime,
    compute_all_scorecards,
    compute_asset_score,
    compute_correlation_matrix,
    compute_economic_snapshot,
    compute_india_context,
    compute_sentiment,
    generate_research_report,
)

# Equity research (stock selection for core holdings)
from market_analyzer.equity_research import (
    EquityScreenResult,
    FundamentalProfile,
    InvestmentHorizon,
    InvestmentStrategy,
    StockRating,
    StockRecommendation,
    StrategyScore,
    analyze_stock,
    fetch_fundamental_profile,
    screen_stocks,
)

# Wheel strategy state machine (MA = decision engine, eTrading = state machine)
from market_analyzer.wheel_strategy import (
    WheelAction,
    WheelDecision,
    WheelPosition,
    WheelState,
    decide_wheel_action,
)

# Futures analysis
from market_analyzer.futures_analysis import (
    FUTURES_INSTRUMENTS,
    CalendarSpreadAnalysis,
    FuturesBasisAnalysis,
    FuturesMarginEstimate,
    FuturesOptionAnalysis,
    FuturesResearchReport,
    FuturesRollDecision,
    FuturesTermStructureAnalysis,
    RollAction,
    TermStructure,
    analyze_calendar_spread,
    analyze_futures_basis,
    analyze_futures_options,
    analyze_term_structure,
    decide_futures_roll,
    estimate_futures_margin,
    generate_futures_report,
)

# Quotes (broker-agnostic)
from market_analyzer.models.quotes import AccountBalance, MarketMetrics, OptionQuote, QuoteSnapshot

# Broker ABCs
from market_analyzer.broker.base import (
    AccountProvider,
    BrokerSession,
    MarketDataProvider,
    MarketMetricsProvider,
    TokenExpiredError,
    WatchlistProvider,
)

# Vol surface
from market_analyzer.models.vol_surface import (
    SkewSlice,
    TermStructurePoint,
    VolatilitySurface,
)
from market_analyzer.service.vol_surface import VolSurfaceService
from market_analyzer.features.vol_surface import compute_vol_surface

# Vol history (IV percentile layer)
from market_analyzer.vol_history import (
    DailyIVSnapshot,
    IVPercentiles,
    compute_iv_percentiles,
    build_iv_snapshot_from_surface,
)

# Option pricing + arbitrage detection
from market_analyzer.arbitrage import (
    ArbitrageOpportunity,
    ArbitrageScanResult,
    TheoreticalPrice,
    compute_theoretical_price,
    check_put_call_parity,
    scan_arbitrage,
)

# Pre-market scanner
from market_analyzer.premarket_scanner import (
    PremarketAlert,
    PremarketScanResult,
    GapStrategy,
    scan_premarket,
    fetch_premarket_data,
)

# Market registry
from market_analyzer.registry import MarketRegistry, MarketInfo, InstrumentInfo, MarginEstimate

# Universe filtering
from market_analyzer.models.universe import (
    AssetType,
    SortField,
    UniverseCandidate,
    UniverseFilter,
    UniverseScanResult,
    PRESETS as UNIVERSE_PRESETS,
)
from market_analyzer.service.universe import UniverseService

# Trading plan
from market_analyzer.models.trading_plan import (
    DailyTradingPlan,
    DayVerdict,
    PlanHorizon,
    PlanTrade,
    RiskBudget,
)
from market_analyzer.macro.expiry import ExpiryEvent, ExpiryType
from market_analyzer.service.trading_plan import TradingPlanService
from market_analyzer.config import BrokerSettings, TradingPlanSettings

# Opportunity assessment
from market_analyzer.models.levels import (
    LevelRole,
    LevelSource,
    LevelsAnalysis,
    PriceLevel,
    StopLoss,
    Target,
    TradeDirection,
)
from market_analyzer.models.intraday import (
    IntradayMonitorResult,
    IntradaySignal,
    IntradaySignalType,
    IntradaySnapshot,
    IntradayUrgency,
)
from market_analyzer.models.transparency import DataGap
from market_analyzer.models.opportunity import (
    BreakoutOpportunity,
    LEAPOpportunity,
    LegAction,
    LegSpec,
    MomentumOpportunity,
    ORBDecision,
    OrderSide,
    RiskProfile,
    StructureProfile,
    StructureType,
    TradeSpec,
    Verdict,
    ZeroDTEOpportunity,
    ZeroDTEStrategy,
    get_structure_profile,
)
from market_analyzer.opportunity.option_plays.earnings import EarningsOpportunity
from market_analyzer.opportunity.setups.mean_reversion import MeanReversionOpportunity
from market_analyzer.opportunity.option_plays.zero_dte import assess_zero_dte
from market_analyzer.opportunity.option_plays.leap import assess_leap
from market_analyzer.opportunity.option_plays.earnings import assess_earnings_play
from market_analyzer.opportunity.option_plays.calendar import (
    CalendarOpportunity, CalendarStrategy, assess_calendar,
)
from market_analyzer.opportunity.option_plays.diagonal import (
    DiagonalOpportunity, DiagonalStrategy, assess_diagonal,
)
from market_analyzer.opportunity.option_plays.iron_condor import (
    IronCondorOpportunity, IronCondorStrategy, assess_iron_condor,
)
from market_analyzer.opportunity.option_plays.iron_butterfly import (
    IronButterflyOpportunity, IronButterflyStrategy, assess_iron_butterfly,
)
from market_analyzer.opportunity.option_plays.ratio_spread import (
    RatioSpreadOpportunity, RatioSpreadStrategy, assess_ratio_spread,
)
from market_analyzer.opportunity.setups.breakout import assess_breakout
from market_analyzer.opportunity.setups.momentum import assess_momentum
from market_analyzer.opportunity.setups.mean_reversion import assess_mean_reversion
from market_analyzer.opportunity.setups.orb import (
    ORBSetupOpportunity, ORBStrategy, assess_orb,
)

# Black Swan / Tail-Risk
from market_analyzer.models.black_swan import (
    AlertLevel,
    BlackSwanAlert,
    CircuitBreaker,
    IndicatorStatus,
    StressIndicator,
)
from market_analyzer.models.ranking import (
    RankedEntry,
    RankingFeedback,
    ScoreBreakdown,
    StrategyType,
    TradeRankingResult,
)
from market_analyzer.features.black_swan import compute_black_swan_alert

# Performance feedback
from market_analyzer.models.feedback import (
    CalibrationResult,
    DrawdownResult,
    PerformanceReport,
    RegimePerformance,
    SharpeResult,
    StrategyPerformance,
    TradeExitReason,
    TradeOutcome,
    WeightAdjustment,
)
from market_analyzer.models.learning import (
    DriftAlert,
    DriftSeverity,
    StrategyBandit,
    ThresholdConfig,
)
from market_analyzer.performance import (
    build_bandits,
    calibrate_pop_factors,
    calibrate_weights,
    compute_drawdown,
    compute_performance_report,
    compute_regime_performance,
    compute_sharpe,
    compute_strategy_performance,
    detect_drift,
    optimize_thresholds,
    select_strategies,
    update_bandit,
)

# Features
from market_analyzer.features.pipeline import compute_features
from market_analyzer.features.technicals import compute_technicals

# Currency conversion & cross-market exposure
from market_analyzer.currency import (
    CurrencyPair,
    PositionExposure,
    PortfolioExposure,
    CurrencyPnL,
    CurrencyHedgeAssessment,
    convert_amount,
    compute_portfolio_exposure,
    compute_currency_pnl,
    assess_currency_exposure,
)

# Capital deployment engine (long-term systematic investing)
from market_analyzer.capital_deployment import (
    AssetAllocation,
    CoreHolding,
    CorePortfolio,
    DeploymentSchedule,
    LeapVsStockAnalysis,
    MarketValuation,
    MonthlyAllocation,
    RebalanceAction,
    RebalanceCheck,
    RiskTolerance,
    ValuationZone,
    WheelStrategyAnalysis,
    analyze_core_holding_entry,
    analyze_wheel_strategy,
    check_rebalance,
    compare_leap_vs_stock,
    compute_asset_allocation,
    compute_market_valuation,
    plan_deployment,
    recommend_core_portfolio,
)

# Same-ticker hedge assessment
from market_analyzer.hedging import (
    HedgeType,
    HedgeUrgency,
    HedgeRecommendation,
    assess_hedge,
)

# Cross-market correlation
from market_analyzer.cross_market import (
    CrossMarketAnalysis,
    CrossMarketSignal,
    MarketSyncStatus,
    analyze_cross_market,
    compute_cross_market_correlation,
    predict_gap,
)

# Leg execution sequencing (India single-leg markets)
from market_analyzer.leg_execution import (
    ExecutionLeg,
    ExecutionPlan,
    LegRisk,
    plan_leg_execution,
)

# Execution quality validation
from market_analyzer.execution_quality import (
    ExecutionQuality,
    ExecutionVerdict,
    LegQuality,
    validate_execution_quality,
)

# Portfolio risk management
from market_analyzer.risk import (
    CorrelationRisk,
    DirectionalExposure,
    DrawdownStatus,
    ExpectedLossResult,
    GreeksCheckResult,
    GreeksLimits,
    PortfolioGreeks,
    PortfolioPosition,
    RiskDashboard,
    StrategyConcentration,
    VaRResult,  # backward compat alias for ExpectedLossResult
    check_correlation_risk,
    check_directional_concentration,
    check_drawdown_circuit_breaker,
    check_portfolio_greeks,
    check_strategy_concentration,
    compute_portfolio_var,  # backward compat alias for estimate_portfolio_loss
    estimate_portfolio_loss,
    compute_risk_dashboard,
)

# Trade gate framework (BLOCK/SCALE/WARN classification)
from market_analyzer.gate_framework import (
    GateAction,
    GateEffectivenessReport,
    GateResult,
    GateStats,
    RejectedTrade,
    TradeGateReport,
    analyze_gate_effectiveness,
    evaluate_trade_gates,
)

# Stress testing (portfolio scenario analysis)
from market_analyzer.stress_testing import (
    PredefinedScenario,
    PositionImpact,
    ScenarioParams,
    ScenarioType,
    StressTestResult,
    StressTestSuite,
    get_predefined_scenario,
    run_stress_suite,
    run_stress_test,
)

# TradeSpec factory (public API for eTrading)
from market_analyzer.trade_spec_factory import (
    create_trade_spec,
    build_iron_condor,
    build_credit_spread,
    build_debit_spread,
    build_calendar,
    from_dxlink_symbols,
    to_dxlink_symbols,
    parse_dxlink_symbol,
)

# Trade analytics (public API for eTrading)
from market_analyzer.trade_lifecycle import (
    AggregatedGreeks,
    AlignedStrikes,
    Breakevens,
    ExitMonitorResult,
    ExitSignal,
    FilteredTrades,
    IncomeEntryCheck,
    IncomeYield,
    POPEstimate,
    TradeHealthCheck,
    aggregate_greeks,
    align_strikes_to_levels,
    check_income_entry,
    check_trade_health,
    compute_breakevens,
    compute_income_yield,
    estimate_pop,
    filter_trades_by_account,
    filter_trades_with_portfolio,
    OpenPosition,
    RiskLimits,
    PortfolioFilterResult,
    get_adjustment_recommendation,
    monitor_exit_conditions,
    OvernightRisk,
    OvernightRiskLevel,
    assess_overnight_risk,
)

__all__ = [
    # Config
    "Settings",
    "get_settings",
    "MarketDef",
    "MarketSettings",
    "ScreeningSettings",
    "StrategySettings",
    "ExitSettings",
    # Services (facade)
    "MarketAnalyzer",
    # Services (individual — existing)
    "RegimeService",
    "TechnicalService",
    "PhaseService",
    "FundamentalService",
    "MacroService",
    "LevelsService",
    "OpportunityService",
    "BlackSwanService",
    "TradeRankingService",
    "DataService",
    # Services (individual — new workflow)
    "MarketContextService",
    "InstrumentAnalysisService",
    "ScreeningService",
    "EntryService",
    "StrategyService",
    "ExitService",
    "AdjustmentService",
    # Regime models
    "RegimeID",
    "RegimeResult",
    "RegimeConfig",
    "RegimeExplanation",
    "HMMModelInfo",
    "RegimeTimeSeries",
    "RegimeTimeSeriesEntry",
    "TrendDirection",
    # Phase models
    "PhaseID",
    "PhaseResult",
    "PhaseDetector",
    # Research models
    "TickerResearch",
    "CrossTickerEntry",
    "ResearchReport",
    "TransitionRow",
    "StateMeansRow",
    "LabelAlignmentDetail",
    "FeatureZScore",
    "RegimeHistoryDay",
    "RegimeDistributionEntry",
    # Data models
    "DataType",
    "ProviderType",
    "DataRequest",
    "DataResult",
    # Feature models
    "FeatureConfig",
    "FeatureInspection",
    # Technical models
    "TechnicalSnapshot",
    "TechnicalSignal",
    # Context models (new)
    "MarketContext",
    "IntermarketDashboard",
    "IntermarketEntry",
    # Instrument models (new)
    "InstrumentAnalysis",
    # Entry models (new)
    "EntryTriggerType",
    "EntryCondition",
    "EntryConfirmation",
    # Strategy models (new)
    "OptionStructureType",
    "OptionStructure",
    "StrategyParameters",
    "PositionSize",
    # Adjustment models (new)
    "AdjustmentAnalysis",
    "AdjustmentDecision",
    "AdjustmentOption",
    "AdjustmentType",
    "PositionStatus",
    "TestedSide",
    # Exit models (new)
    "ExitPlan",
    "ExitTarget",
    "ExitReason",
    "AdjustmentTrigger",
    "AdjustmentTriggerType",
    # Screening models (new)
    "ScreenCandidate",
    "ScreeningResult",
    # Fundamentals
    "FundamentalsSnapshot",
    "fetch_fundamentals",
    # Macro
    "MacroCalendar",
    "MacroEvent",
    "MacroEventType",
    "get_macro_calendar",
    # Macro indicators (bond market, credit, dollar, inflation)
    "BondMarketIndicator",
    "CreditSpreadIndicator",
    "DollarStrengthIndicator",
    "InflationExpectationIndicator",
    "MacroIndicatorDashboard",
    "MacroRiskLevel",
    "MacroTrend",
    "compute_macro_dashboard",
    # Macro research (scorecards, correlations, regime, sentiment, economics, reports)
    "AssetClass",
    "AssetScore",
    "CorrelationPair",
    "EconomicSnapshot",
    "IndiaResearchContext",
    "MacroRegime",
    "MacroResearchReport",
    "RESEARCH_ASSETS",
    "RegimeClassification",
    "SentimentDashboard",
    "TrendSignal",
    "classify_macro_regime",
    "compute_all_scorecards",
    "compute_asset_score",
    "compute_correlation_matrix",
    "compute_economic_snapshot",
    "compute_india_context",
    "compute_sentiment",
    "generate_research_report",
    # Levels models
    "LevelRole",
    "LevelSource",
    "LevelsAnalysis",
    "PriceLevel",
    "StopLoss",
    "Target",
    "TradeDirection",
    # Vol surface
    "VolSurfaceService",
    "VolatilitySurface",
    "TermStructurePoint",
    "SkewSlice",
    "compute_vol_surface",
    # Vol history (IV percentile layer)
    "DailyIVSnapshot",
    "IVPercentiles",
    "compute_iv_percentiles",
    "build_iv_snapshot_from_surface",
    # Opportunity models
    "LegAction",
    "LegSpec",
    "StructureType",
    "OrderSide",
    "TradeSpec",
    "Verdict",
    "RiskProfile",
    "StructureProfile",
    "get_structure_profile",
    "EarningsOpportunity",
    "MeanReversionOpportunity",
    "ZeroDTEOpportunity",
    "ZeroDTEStrategy",
    "ORBDecision",
    "LEAPOpportunity",
    "BreakoutOpportunity",
    "MomentumOpportunity",
    "CalendarOpportunity",
    "CalendarStrategy",
    "DiagonalOpportunity",
    "DiagonalStrategy",
    "IronCondorOpportunity",
    "IronCondorStrategy",
    "IronButterflyOpportunity",
    "IronButterflyStrategy",
    "RatioSpreadOpportunity",
    "RatioSpreadStrategy",
    "assess_zero_dte",
    "assess_leap",
    "assess_breakout",
    "assess_momentum",
    "assess_mean_reversion",
    "assess_orb",
    "ORBSetupOpportunity",
    "ORBStrategy",
    "assess_earnings_play",
    "assess_calendar",
    "assess_diagonal",
    "assess_iron_condor",
    "assess_iron_butterfly",
    "assess_ratio_spread",
    # Black Swan
    "AlertLevel",
    "BlackSwanAlert",
    "CircuitBreaker",
    "IndicatorStatus",
    "StressIndicator",
    "compute_black_swan_alert",
    # Ranking
    "StrategyType",
    "ScoreBreakdown",
    "RankedEntry",
    "TradeRankingResult",
    "RankingFeedback",
    # Trading plan
    "DailyTradingPlan",
    "DayVerdict",
    "PlanHorizon",
    "PlanTrade",
    "RiskBudget",
    "ExpiryEvent",
    "ExpiryType",
    "TradingPlanService",
    "TradingPlanSettings",
    # Intraday (0DTE management)
    "IntradayService",
    "IntradaySignal",
    "IntradaySignalType",
    "IntradaySnapshot",
    "IntradayMonitorResult",
    "IntradayUrgency",
    # Quotes (broker-agnostic)
    "AccountBalance",
    "OptionQuote",
    "QuoteSnapshot",
    "MarketMetrics",
    "OptionQuoteService",
    # Broker ABCs
    "AccountProvider",
    "BrokerSession",
    "MarketDataProvider",
    "MarketMetricsProvider",
    "TokenExpiredError",
    "WatchlistProvider",
    # Market registry
    "MarketRegistry",
    "MarketInfo",
    "InstrumentInfo",
    "MarginEstimate",
    # Universe filtering
    "AssetType",
    "SortField",
    "UniverseCandidate",
    "UniverseFilter",
    "UniverseScanResult",
    "UNIVERSE_PRESETS",
    "UniverseService",
    # Config
    "BrokerSettings",
    # Functions
    "compute_features",
    "compute_technicals",
    # TradeSpec factory (public API for eTrading)
    "create_trade_spec",
    "build_iron_condor",
    "build_credit_spread",
    "build_debit_spread",
    "build_calendar",
    "from_dxlink_symbols",
    "to_dxlink_symbols",
    "parse_dxlink_symbol",
    # Trade analytics (public API for eTrading)
    "AggregatedGreeks",
    "AlignedStrikes",
    "Breakevens",
    "ExitMonitorResult",
    "ExitSignal",
    "FilteredTrades",
    "IncomeEntryCheck",
    "IncomeYield",
    "POPEstimate",
    "aggregate_greeks",
    "align_strikes_to_levels",
    "check_income_entry",
    "compute_breakevens",
    "compute_income_yield",
    "estimate_pop",
    "filter_trades_by_account",
    "filter_trades_with_portfolio",
    "OpenPosition",
    "RiskLimits",
    "PortfolioFilterResult",
    "monitor_exit_conditions",
    "TradeHealthCheck",
    "check_trade_health",
    "get_adjustment_recommendation",
    "OvernightRisk",
    "OvernightRiskLevel",
    "assess_overnight_risk",
    # Currency conversion & cross-market exposure
    "CurrencyPair",
    "PositionExposure",
    "PortfolioExposure",
    "CurrencyPnL",
    "CurrencyHedgeAssessment",
    "convert_amount",
    "compute_portfolio_exposure",
    "compute_currency_pnl",
    "assess_currency_exposure",
    # Same-ticker hedge assessment
    "HedgeType",
    "HedgeUrgency",
    "HedgeRecommendation",
    "assess_hedge",
    # Leg execution sequencing
    "ExecutionLeg",
    "ExecutionPlan",
    "LegRisk",
    "plan_leg_execution",
    # Execution quality validation
    "ExecutionQuality",
    "ExecutionVerdict",
    "LegQuality",
    "validate_execution_quality",
    # Cross-market correlation
    "CrossMarketAnalysis",
    "CrossMarketSignal",
    "MarketSyncStatus",
    "analyze_cross_market",
    "compute_cross_market_correlation",
    "predict_gap",
    # Portfolio risk management
    "PortfolioPosition",
    "PortfolioGreeks",
    "GreeksLimits",
    "GreeksCheckResult",
    "VaRResult",
    "StrategyConcentration",
    "DirectionalExposure",
    "CorrelationRisk",
    "DrawdownStatus",
    "RiskDashboard",
    "compute_portfolio_var",
    "check_portfolio_greeks",
    "check_strategy_concentration",
    "check_directional_concentration",
    "check_correlation_risk",
    "check_drawdown_circuit_breaker",
    "compute_risk_dashboard",
    # Trade gate framework
    "GateAction",
    "GateEffectivenessReport",
    "GateResult",
    "GateStats",
    "RejectedTrade",
    "TradeGateReport",
    "analyze_gate_effectiveness",
    "evaluate_trade_gates",
    # Stress testing (portfolio scenario analysis)
    "ScenarioType",
    "ScenarioParams",
    "PredefinedScenario",
    "PositionImpact",
    "StressTestResult",
    "StressTestSuite",
    "get_predefined_scenario",
    "run_stress_test",
    "run_stress_suite",
    # Equity research (stock selection)
    "InvestmentHorizon",
    "InvestmentStrategy",
    "StockRating",
    "FundamentalProfile",
    "StrategyScore",
    "StockRecommendation",
    "EquityScreenResult",
    "fetch_fundamental_profile",
    "analyze_stock",
    "screen_stocks",
    # Transparency
    "DataGap",
    # Performance feedback
    "TradeOutcome",
    "TradeExitReason",
    "StrategyPerformance",
    "PerformanceReport",
    "WeightAdjustment",
    "CalibrationResult",
    "SharpeResult",
    "DrawdownResult",
    "RegimePerformance",
    "compute_strategy_performance",
    "compute_performance_report",
    "calibrate_weights",
    "calibrate_pop_factors",
    "compute_sharpe",
    "compute_drawdown",
    "compute_regime_performance",
    # Drift detection
    "DriftAlert",
    "DriftSeverity",
    "detect_drift",
    # Thompson Sampling bandits
    "StrategyBandit",
    "build_bandits",
    "update_bandit",
    "select_strategies",
    # Threshold optimization
    "ThresholdConfig",
    "optimize_thresholds",
    # Capital deployment engine
    "ValuationZone",
    "RiskTolerance",
    "MarketValuation",
    "MonthlyAllocation",
    "DeploymentSchedule",
    "AssetAllocation",
    "CoreHolding",
    "CorePortfolio",
    "RebalanceAction",
    "RebalanceCheck",
    "LeapVsStockAnalysis",
    "WheelStrategyAnalysis",
    "compute_market_valuation",
    "plan_deployment",
    "compute_asset_allocation",
    "recommend_core_portfolio",
    "check_rebalance",
    "compare_leap_vs_stock",
    "analyze_wheel_strategy",
    "analyze_core_holding_entry",
]
