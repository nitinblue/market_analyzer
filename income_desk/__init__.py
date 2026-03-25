"""Market analysis toolkit: regime detection, technicals, phase detection, and opportunity assessment."""

__version__ = "1.0.0"

# Config
from income_desk.config import (
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
from income_desk.models.regime import (
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
from income_desk.models.phase import PhaseID, PhaseResult
from income_desk.models.data import DataType, ProviderType, DataRequest, DataResult
from income_desk.models.features import FeatureConfig, FeatureInspection
from income_desk.models.technicals import TechnicalSnapshot, TechnicalSignal

# New workflow models
from income_desk.models.context import InstrumentAvailability, IntermarketDashboard, IntermarketEntry, MarketContext
from income_desk.models.instrument import InstrumentAnalysis
from income_desk.models.entry import (
    ConditionalEntry,
    EntryConfirmation,
    EntryCondition,
    EntryLevelScore,
    EntryTriggerType,
    PullbackAlert,
    SkewOptimalStrike,
    StrikeProximityLeg,
    StrikeProximityResult,
)
from income_desk.features.entry_levels import (
    compute_limit_entry_price,
    compute_pullback_levels,
    compute_strike_support_proximity,
    score_entry_level,
    select_skew_optimal_strike,
)
from income_desk.models.strategy import (
    OptionStructure,
    OptionStructureType,
    PositionSize,
    StrategyParameters,
)
from income_desk.models.adjustment import (
    AdjustmentAnalysis,
    AdjustmentDecision,
    AdjustmentOption,
    AdjustmentType,
    PositionStatus,
    TestedSide,
)
from income_desk.models.assignment import (
    AssignmentAction,
    AssignmentAnalysis,
    AssignmentRisk,
    AssignmentRiskResult,
    AssignmentType,
    CSPIntent,
    CSPAnalysis,
    CoveredCallAnalysis,
)
from income_desk.features.assignment_handler import (
    handle_assignment,
    assess_assignment_risk,
    analyze_cash_secured_put,
    analyze_covered_call,
)
from income_desk.models.exit_plan import (
    AdjustmentTrigger,
    AdjustmentTriggerType,
    ExitPlan,
    ExitReason,
    ExitTarget,
)

# Services
from income_desk.service.analyzer import MarketAnalyzer
from income_desk.service.regime_service import RegimeService
from income_desk.service.technical import TechnicalService
from income_desk.service.phase import PhaseService
from income_desk.service.fundamental import FundamentalService
from income_desk.service.macro import MacroService
from income_desk.service.levels import LevelsService
from income_desk.service.opportunity import OpportunityService
from income_desk.service.black_swan import BlackSwanService
from income_desk.service.ranking import TradeRankingService
from income_desk.data.service import DataService

# New workflow services
from income_desk.service.context import MarketContextService
from income_desk.service.instrument import InstrumentAnalysisService
from income_desk.service.screening import ScreeningService, ScreenCandidate, ScreeningResult
from income_desk.service.entry import EntryService
from income_desk.service.strategy import StrategyService
from income_desk.service.exit import ExitService
from income_desk.service.adjustment import AdjustmentService
from income_desk.service.intraday import IntradayService
from income_desk.service.option_quotes import OptionQuoteService

# Phase detection
from income_desk.phases.detector import PhaseDetector

# Fundamentals
from income_desk.models.fundamentals import FundamentalsSnapshot
from income_desk.fundamentals.fetch import fetch_fundamentals

# Macro
from income_desk.models.macro import MacroCalendar, MacroEvent, MacroEventType
from income_desk.macro.calendar import get_macro_calendar

# Macro indicators (bond market, credit, dollar, inflation)
from income_desk.macro_indicators import (
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
from income_desk.macro_research import (
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
from income_desk.equity_research import (
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
from income_desk.wheel_strategy import (
    WheelAction,
    WheelDecision,
    WheelPosition,
    WheelState,
    decide_wheel_action,
)

# Futures analysis
from income_desk.futures_analysis import (
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
from income_desk.models.quotes import AccountBalance, MarketMetrics, OptionQuote, QuoteSnapshot

# Broker ABCs
from income_desk.broker.base import (
    AccountProvider,
    BrokerSession,
    MarketDataProvider,
    MarketMetricsProvider,
    TokenExpiredError,
    WatchlistProvider,
)

# Broker connectors (top-level convenience imports for eTrading)
from income_desk.broker.tastytrade import connect_tastytrade, connect_from_sessions
from income_desk.broker.dhan import connect_dhan, connect_dhan_from_session
from income_desk.broker.alpaca import connect_alpaca
from income_desk.broker.schwab import connect_schwab
from income_desk.broker.ibkr import connect_ibkr
from income_desk.broker.zerodha import connect_zerodha

# Vol surface
from income_desk.models.vol_surface import (
    SkewSlice,
    TermStructurePoint,
    VolatilitySurface,
)
from income_desk.service.vol_surface import VolSurfaceService
from income_desk.features.vol_surface import compute_vol_surface

# Vol history (IV percentile layer)
from income_desk.vol_history import (
    DailyIVSnapshot,
    IVPercentiles,
    compute_iv_percentiles,
    build_iv_snapshot_from_surface,
)

# Option pricing + arbitrage detection
from income_desk.arbitrage import (
    ArbitrageOpportunity,
    ArbitrageScanResult,
    TheoreticalPrice,
    compute_theoretical_price,
    check_put_call_parity,
    scan_arbitrage,
)

# BYOD adapters — ready-made provider implementations users can plug in
from income_desk.adapters.csv_provider import CSVProvider
from income_desk.adapters.dict_quotes import DictQuoteProvider, DictMetricsProvider
from income_desk.adapters.csv_trades import (
    ImportedPosition,
    ImportResult,
    detect_broker_format,
    import_trades_csv,
)
from income_desk.adapters.simulated import (
    SimulatedMarketData,
    SimulatedMetrics,
    SimulatedAccount,
    create_calm_market,
    create_volatile_market,
    create_crash_scenario,
    create_india_market,
    create_ideal_income,
    create_post_crash_recovery,
    create_wheel_opportunity,
    create_india_trading,
    refresh_simulation_data,
    create_from_snapshot,
    get_snapshot_info,
)

# Pre-market scanner
from income_desk.premarket_scanner import (
    PremarketAlert,
    PremarketScanResult,
    GapStrategy,
    scan_premarket,
    fetch_premarket_data,
)

# Market registry
from income_desk.registry import MarketRegistry, MarketInfo, InstrumentInfo, MarginEstimate

# Universe filtering
from income_desk.models.universe import (
    AssetType,
    SortField,
    UniverseCandidate,
    UniverseFilter,
    UniverseScanResult,
    PRESETS as UNIVERSE_PRESETS,
)
from income_desk.service.universe import UniverseService

# Trading plan
from income_desk.models.trading_plan import (
    DailyTradingPlan,
    DayVerdict,
    PlanHorizon,
    PlanTrade,
    RiskBudget,
)
from income_desk.macro.expiry import ExpiryEvent, ExpiryType
from income_desk.service.trading_plan import TradingPlanService
from income_desk.config import BrokerSettings, TradingPlanSettings

# Opportunity assessment
from income_desk.models.levels import (
    LevelRole,
    LevelSource,
    LevelsAnalysis,
    PriceLevel,
    StopLoss,
    Target,
    TradeDirection,
)
from income_desk.models.intraday import (
    IntradayMonitorResult,
    IntradaySignal,
    IntradaySignalType,
    IntradaySnapshot,
    IntradayUrgency,
)
from income_desk.models.transparency import (
    CalculationMode,
    ContextGap,
    DataGap,
    DataSource,
    DataTrust,
    DegradedField,
    FitnessCategory,
    TrustLevel,
    TrustReport,
)
from income_desk.features.data_trust import (
    compute_context_quality,
    compute_data_trust,
    compute_trust_report,
)
from income_desk.models.opportunity import (
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
    ALL_OPTION_STRUCTURES,
    INCOME_STRUCTURES,
    TradeSpec,
    Verdict,
    ZeroDTEOpportunity,
    ZeroDTEStrategy,
    get_structure_profile,
)
from income_desk.opportunity.option_plays.earnings import EarningsOpportunity
from income_desk.opportunity.setups.mean_reversion import MeanReversionOpportunity
from income_desk.opportunity.option_plays.zero_dte import assess_zero_dte
from income_desk.opportunity.option_plays.leap import assess_leap
from income_desk.opportunity.option_plays.earnings import assess_earnings_play
from income_desk.opportunity.option_plays.calendar import (
    CalendarOpportunity, CalendarStrategy, assess_calendar,
)
from income_desk.opportunity.option_plays.diagonal import (
    DiagonalOpportunity, DiagonalStrategy, assess_diagonal,
)
from income_desk.opportunity.option_plays.iron_condor import (
    IronCondorOpportunity, IronCondorStrategy, assess_iron_condor,
)
from income_desk.opportunity.option_plays.iron_butterfly import (
    IronButterflyOpportunity, IronButterflyStrategy, assess_iron_butterfly,
)
from income_desk.opportunity.option_plays.ratio_spread import (
    RatioSpreadOpportunity, RatioSpreadStrategy, assess_ratio_spread,
)
from income_desk.opportunity.setups.breakout import assess_breakout
from income_desk.opportunity.setups.momentum import assess_momentum
from income_desk.opportunity.setups.mean_reversion import assess_mean_reversion
from income_desk.opportunity.setups.orb import (
    ORBSetupOpportunity, ORBStrategy, assess_orb,
)

# Black Swan / Tail-Risk
from income_desk.models.black_swan import (
    AlertLevel,
    BlackSwanAlert,
    CircuitBreaker,
    IndicatorStatus,
    StressIndicator,
)
from income_desk.models.ranking import (
    RankedEntry,
    RankingFeedback,
    ScoreBreakdown,
    StrategyType,
    TradeRankingResult,
    WatchItem,
)
from income_desk.features.black_swan import compute_black_swan_alert

# Performance feedback
from income_desk.models.feedback import (
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
from income_desk.models.learning import (
    DriftAlert,
    DriftSeverity,
    StrategyBandit,
    ThresholdConfig,
)
from income_desk.performance import (
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
from income_desk.features.pipeline import compute_features
from income_desk.features.technicals import compute_technicals

# Currency conversion & cross-market exposure
from income_desk.currency import (
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

# Kelly criterion position sizing
from income_desk.features.position_sizing import (
    KellyResult,
    PortfolioExposure as KellyPortfolioExposure,
    compute_kelly_fraction,
    compute_kelly_position_size,
)

# Portfolio desk management
from income_desk.models.portfolio import (
    DeskAdjustment,
    DeskHealth,
    DeskHealthReport,
    DeskRecommendation,
    DeskRiskLimits,
    DeskSpec,
    InstrumentRisk,
    PortfolioAllocation,
    PortfolioAssetAllocation,
    PortfolioAssetClass,
    PortfolioRiskType,
    RebalanceRecommendation,
    RiskTolerance,
)
from income_desk.features.desk_management import (
    compute_desk_risk_limits,
    compute_instrument_risk,
    evaluate_desk_health,
    rebalance_desks,
    recommend_desk_structure,
    suggest_desk_for_trade,
)

# Capital deployment engine (long-term systematic investing)
from income_desk.capital_deployment import (
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

# Same-ticker hedge assessment (legacy) + hedging domain package
from income_desk.hedging import (
    HedgeType,
    HedgeUrgency,
    HedgeRecommendation,
    assess_hedge,
    # New hedging domain
    resolve_hedge_strategy,
    compare_hedge_methods,
    analyze_portfolio_hedge,
    build_protective_put,
    build_collar,
    build_futures_hedge,
    build_index_hedge,
    HedgeTier,
    HedgeResult,
    PortfolioHedgeAnalysis,
)

# Exit intelligence (regime stops, time-adjusted targets, theta decay, monitoring)
from income_desk.models.exit import (
    MonitoringAction,
    RegimeStop,
    TimeAdjustedTarget,
    ThetaDecayResult,
)
from income_desk.features.exit_intelligence import (
    compute_monitoring_action,
    compute_regime_stop,
    compute_time_adjusted_target,
    compute_remaining_theta_value,
)
from income_desk.opportunity.option_plays._trade_spec_helpers import (
    build_closing_trade_spec,
)

# DTE optimizer
from income_desk.features.dte_optimizer import (
    DTERecommendation,
    select_optimal_dte,
)

# IV rank quality (entry gating)
from income_desk.models.entry import IVRankQuality
from income_desk.features.entry_levels import compute_iv_rank_quality

# Adjustment outcome tracking
from income_desk.models.adjustment import (
    AdjustmentOutcome,
    AdjustmentEffectiveness,
)

# Extended position sizing (correlation + regime margin + cash/margin analytics)
from income_desk.features.position_sizing import (
    CorrelationAdjustment,
    MarginAnalysis,
    MarginBuffer,
    RegimeMarginEstimate,
    compute_pairwise_correlation,
    adjust_kelly_for_correlation,
    compute_margin_analysis,
    compute_margin_buffer,
    compute_regime_adjusted_bp,
    compute_position_size,
    analyze_adjustment_effectiveness,
)

# Interest rate risk
from income_desk.features.rate_risk import (
    PortfolioRateRisk,
    RateRiskAssessment,
    RateRiskLevel,
    assess_portfolio_rate_risk,
    assess_rate_risk,
)

# Cross-market correlation
from income_desk.cross_market import (
    CrossMarketAnalysis,
    CrossMarketSignal,
    MarketSyncStatus,
    analyze_cross_market,
    compute_cross_market_correlation,
    predict_gap,
)

# Leg execution sequencing (India single-leg markets)
from income_desk.leg_execution import (
    ExecutionLeg,
    ExecutionPlan,
    LegRisk,
    plan_leg_execution,
)

# Execution quality validation
from income_desk.execution_quality import (
    ExecutionQuality,
    ExecutionVerdict,
    LegQuality,
    validate_execution_quality,
)

# Portfolio risk management
from income_desk.risk import (
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
    ExpectedLossResult,
    check_correlation_risk,
    check_directional_concentration,
    check_drawdown_circuit_breaker,
    check_portfolio_greeks,
    check_strategy_concentration,
    estimate_portfolio_loss,
    compute_risk_dashboard,
)

# Trade gate framework (BLOCK/SCALE/WARN classification)
from income_desk.gate_framework import (
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
from income_desk.stress_testing import (
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
from income_desk.trade_spec_factory import (
    create_trade_spec,
    build_iron_condor,
    build_credit_spread,
    build_debit_spread,
    build_calendar,
    from_dxlink_symbols,
    to_dxlink_symbols,
    parse_dxlink_symbol,
)

# Trade analytics — P&L, structure risk, portfolio, performance, circuit breakers
from income_desk.trade_analytics import (
    BreakerTripped,
    CircuitBreakerConfig,
    CircuitBreakerResult,
    LegPnL,
    LegPnLInput,
    PerformanceLedger,
    PnLAttribution,
    PortfolioAnalytics,
    PositionSnapshot,
    StructureRisk,
    TradePnL,
    UnderlyingExposure,
    compute_performance_ledger,
    compute_pnl_attribution,
    compute_portfolio_analytics,
    compute_structure_risk,
    compute_trade_pnl,
    evaluate_circuit_breakers,
)

# Trade analytics (public API for eTrading)
from income_desk.trade_lifecycle import (
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

# Position stress monitoring (ongoing adversarial checks)
from income_desk.validation.stress_scenarios import run_position_stress

# Crash sentinel (market health monitoring)
from income_desk.models.sentinel import SentinelReport, SentinelSignal, SentinelTicker
from income_desk.features.crash_sentinel import assess_crash_sentinel

# Decision audit framework
from income_desk.models.decision_audit import (
    DecisionReport,
    GradedCheck,
    LegAudit,
    TradeAudit,
    PortfolioAudit,
    RiskAudit,
)
from income_desk.features.decision_audit import (
    audit_decision,
    audit_legs,
    audit_trade,
    audit_portfolio,
    audit_risk,
)

# Operations reporting — business ops dashboards
# Back-office operations reporting (moved to income_desk.backoffice)
from income_desk.backoffice import (
    BookedRecord,
    BrokerAccountStatus,
    CapitalUtilization,
    ClosedTradeRecord,
    DailyOpsSummary,
    DeskUtilization,
    OpsDecisionRecord,
    PeriodPnL,
    PlatformMetrics,
    PnLRollup,
    RejectionBreakdown,
    ShadowRecord,
    StrategyAttribution,
    TickerAttribution,
    compute_capital_utilization,
    compute_daily_ops_summary,
    compute_margin_requirements,
    compute_platform_metrics,
    compute_pnl_rollup,
    MarginRequirements,
)
# Backwards compat: eTrading imports DecisionRecord from income_desk directly
from income_desk.backoffice.ops_reporting import DecisionRecord

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
    "ConditionalEntry",
    "EntryLevelScore",
    "PullbackAlert",
    "SkewOptimalStrike",
    "StrikeProximityLeg",
    "StrikeProximityResult",
    # Entry level functions
    "compute_limit_entry_price",
    "compute_pullback_levels",
    "compute_strike_support_proximity",
    "score_entry_level",
    "select_skew_optimal_strike",
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
    # Broker connectors
    "connect_tastytrade",
    "connect_from_sessions",
    "connect_dhan",
    "connect_dhan_from_session",
    "connect_alpaca",
    "connect_schwab",
    "connect_ibkr",
    "connect_zerodha",
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
    "run_position_stress",
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
    # Same-ticker hedge assessment (legacy)
    "HedgeType",
    "HedgeUrgency",
    "HedgeRecommendation",
    "assess_hedge",
    # Hedging domain package
    "resolve_hedge_strategy",
    "compare_hedge_methods",
    "analyze_portfolio_hedge",
    "build_protective_put",
    "build_collar",
    "build_futures_hedge",
    "build_index_hedge",
    "HedgeTier",
    "HedgeResult",
    "PortfolioHedgeAnalysis",
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
    "ExpectedLossResult",
    "StrategyConcentration",
    "DirectionalExposure",
    "CorrelationRisk",
    "DrawdownStatus",
    "RiskDashboard",
    "estimate_portfolio_loss",
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
    # Crash sentinel (market health monitoring)
    "SentinelSignal",
    "SentinelTicker",
    "SentinelReport",
    "assess_crash_sentinel",
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
    # Kelly criterion position sizing
    "KellyResult",
    "KellyPortfolioExposure",
    "compute_kelly_fraction",
    "compute_kelly_position_size",
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
    # Exit intelligence (reform)
    "MonitoringAction",
    "RegimeStop",
    "TimeAdjustedTarget",
    "ThetaDecayResult",
    "compute_monitoring_action",
    "compute_regime_stop",
    "compute_time_adjusted_target",
    "compute_remaining_theta_value",
    "build_closing_trade_spec",
    # DTE optimizer (reform)
    "DTERecommendation",
    "select_optimal_dte",
    # IV rank quality (reform)
    "IVRankQuality",
    "compute_iv_rank_quality",
    # Adjustment outcome tracking (reform)
    "AdjustmentOutcome",
    "AdjustmentEffectiveness",
    # Extended position sizing (reform)
    "CorrelationAdjustment",
    "MarginAnalysis",
    "MarginBuffer",
    "RegimeMarginEstimate",
    "compute_pairwise_correlation",
    "adjust_kelly_for_correlation",
    "compute_margin_analysis",
    "compute_margin_buffer",
    "compute_regime_adjusted_bp",
    "compute_position_size",
    "analyze_adjustment_effectiveness",
    # Assignment risk warning (BEFORE assignment)
    "AssignmentRisk",
    "AssignmentRiskResult",
    "assess_assignment_risk",
    # CSP / Covered Call workflow (intentional assignment / wheel)
    "CSPIntent",
    "CSPAnalysis",
    "CoveredCallAnalysis",
    "analyze_cash_secured_put",
    "analyze_covered_call",
    # Interest rate risk
    "RateRiskLevel",
    "RateRiskAssessment",
    "PortfolioRateRisk",
    "assess_rate_risk",
    "assess_portfolio_rate_risk",
    # Trade analytics — P&L, structure risk, portfolio, performance, circuit breakers
    "BreakerTripped",
    "CircuitBreakerConfig",
    "CircuitBreakerResult",
    "LegPnL",
    "LegPnLInput",
    "PerformanceLedger",
    "PnLAttribution",
    "PortfolioAnalytics",
    "PositionSnapshot",
    "StructureRisk",
    "TradePnL",
    "UnderlyingExposure",
    "compute_performance_ledger",
    "compute_pnl_attribution",
    "compute_portfolio_analytics",
    "compute_structure_risk",
    "compute_trade_pnl",
    "evaluate_circuit_breakers",
    # Operations reporting — business ops dashboards
    "BookedRecord",
    "BrokerAccountStatus",
    "CapitalUtilization",
    "ClosedTradeRecord",
    "DailyOpsSummary",
    "DecisionRecord",
    "DeskUtilization",
    "PeriodPnL",
    "PlatformMetrics",
    "PnLRollup",
    "RejectionBreakdown",
    "ShadowRecord",
    "StrategyAttribution",
    "TickerAttribution",
    "compute_capital_utilization",
    "compute_daily_ops_summary",
    "compute_margin_requirements",
    "compute_platform_metrics",
    "compute_pnl_rollup",
    # Margin requirements (broker-specific)
    "MarginRequirements",
]
