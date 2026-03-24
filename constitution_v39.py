# Trading Constitution v50.0 – Lawson Tyrone Robinson (@lakeside407)
# Date locked: March 2026
# Core rule: ZERO manual actions except final Yes/No to enter a trade.
# All other logic, calculations, monitoring, executions, exits, hedges = fully scripted/automated.

# =====================================================================
# PREAMBLE — THREE-BUSINESS CONSTITUTIONAL FRAMEWORK (est. v32.0)
# =====================================================================
# This constitution governs THREE independent business divisions.
# Constitutional intent: SEPARATION. A drawdown in the markets
# (Trading Division) does not affect your content income or physical
# fleet revenue — and vice versa. Each division operates under its
# own rules, risk parameters, and revenue model.
#
# ┌─────────────────────────────────────────────────────────────────┐
# │  DIVISION 1: TRADING DIVISION                                  │
# │  Type: Digital Asset Management                                │
# │  Revenue Model: MSTR LEAP options via v2.8+ Trend Adder        │
# │  Constitutional Relationship: Governed by ALL risk parameters,  │
# │    kill switches, trailing stops, entry/exit filters, auditor,  │
# │    and safety infrastructure defined in this constitution.      │
# │  Status: ACTIVE — v2.8+ LIVE on IBKR U15746102                │
# ├─────────────────────────────────────────────────────────────────┤
# │  DIVISION 2: NOMAD PUBLIC BUSINESS                             │
# │  Type: Content & Social Monetization                           │
# │  Revenue Model: Uncorrelated income stream — content creation,  │
# │    social media, brand partnerships, digital products           │
# │  Constitutional Relationship: INDEPENDENT. No trading rules     │
# │    apply. Not subject to drawdown halts, kill switches, or      │
# │    position sizing. Operates outside Rudy's automation layer.   │
# │  Purpose: Provide stable cash flow uncorrelated to markets.     │
# │    Market crashes do not affect this revenue. This division     │
# │    generates income regardless of BTC cycle or MSTR price.      │
# │  Status: ACTIVE                                                │
# ├─────────────────────────────────────────────────────────────────┤
# │  DIVISION 3: CYBERCAB FLEET DIVISION                           │
# │  Type: Physical Autonomous Revenue Nodes                       │
# │  Revenue Model: Tesla Cybercab fleet — Robotaxi network        │
# │    revenue with exponential reinvestment compounding            │
# │  Constitutional Relationship: INDEPENDENT of Trading Division.  │
# │    Physical assets, not correlated to market drawdowns.         │
# │    Seed capital may come from Trading Division profits          │
# │    (MSTR LEAP gains → Cybercab down payments), but once         │
# │    deployed, fleet operates independently.                      │
# │  Status: RESEARCH / PRE-LAUNCH — monitoring Tesla Robotaxi     │
# │    launch timeline                                              │
# └─────────────────────────────────────────────────────────────────┘
#
# SUMMARY TABLE:
# ┌──────────────────┬─────────────────────┬────────────────────────┬───────────────────────────┐
# │ Division         │ Type                │ Revenue Model          │ Constitutional Rules      │
# ├──────────────────┼─────────────────────┼────────────────────────┼───────────────────────────┤
# │ Trading          │ Digital Assets      │ MSTR LEAPs (v2.8+)     │ ALL (71+ variables)       │
# │ Nomad Public     │ Content/Social      │ Content monetization   │ NONE (independent)        │
# │ CyberCab Fleet   │ Physical Assets     │ Robotaxi network       │ NONE (independent)        │
# └──────────────────┴─────────────────────┴────────────────────────┴───────────────────────────┘
#
# SEPARATION PRINCIPLE:
# Each division is a firewall. Trading losses cannot consume content
# income. Fleet maintenance costs cannot trigger trading kill switches.
# The portfolio is THREE businesses, not one — diversified across
# digital, creative, and physical revenue streams.

# =====================================================================
# CAPITAL DEPLOYMENT PLAN — v2.8+ MSTR BULL CYCLE (March 2026)
# =====================================================================
# Three-phase deployment. All capital converges into ONE v2.8+ position.
# Goal: $10K → $350-500K via MSTR LEAP cycle-low entry.
#
# PHASE 1: EARLY SIGNAL (Now → October 2026)
#   Source: Current IBKR account balance (~$7,900)
#   Trigger: v2.8+ entry signal fires (200W dip+reclaim, BTC>200W, StochRSI<70)
#   Action: Enter immediately with available capital — do NOT wait for full $130K
#   Rationale: Missing the cycle-low buy window is worse than entering light.
#              The 50/50 scale-in is designed exactly for this scenario.
#
# PHASE 2: PUT PROCEEDS → v2.8+ SCALE-IN
#   Source: MSTR $50P Jan28 (cost $1,253) + SPY $430P Jan27 (cost $495)
#   Trigger: Trailing ladder stop-outs close the put positions
#   Action: Proceeds stay in IBKR account, rolled into v2.8+ position
#   Rule: Do NOT withdraw put proceeds. Do NOT open new put positions.
#         All closed put capital feeds the v2.8+ MSTR entry.
#
# PHASE 3: FULL DEPLOYMENT (August–October 2026)
#   Source: $130,000 external capital injection
#   Trigger: Capital arrives in IBKR account
#   Action: Scale into v2.8+ position via trend adder / second entry
#   Rationale: This is the bulk of the position for the rest of the bull run.
#              If Phase 1 already entered, this becomes the scale-in.
#              If signal hasn't fired yet, this becomes the full first entry.
#
# CAPITAL FLOW:
#   Phase 1: ~$7,900 (current) ──┐
#   Phase 2: ~$1,750 (puts)   ───┼──→ v2.8+ MSTR LEAP Position
#   Phase 3: $130,000 (inject) ──┘
#   Total potential deployment: ~$139,650
#
# CRITICAL RULES:
#   - All three phases feed ONE strategy: v2.8+ MSTR Cycle-Low LEAP
#   - Put proceeds are NOT for new hedges — they are v2.8+ fuel
#   - If signal fires before $130K arrives, enter with what's available
#   - Never let the buy window close because "we're waiting for more capital"
V28_CAPITAL_PHASE1 = 7900                         # Current IBKR balance
V28_CAPITAL_PHASE2_PUTS = 1750                    # Estimated put proceeds at close
V28_CAPITAL_PHASE3_INJECTION = 130000             # External capital (Aug-Oct 2026)
V28_TOTAL_DEPLOYMENT = 139650                     # All phases combined

TOTAL_EXPERIMENTAL_ALLOCATION = 170000          # $170k – S1-S4 $140k + S6 $15k + S7 $10k pre + S8 $10k ($25k S7 post reserved)
TREASURY_LOCK_PERCENTAGE = 0.75                 # 75% of total portfolio remains protected
LOTTERY_CAPITAL = 100000                        # System 1 quarterly deployment
CONSERVATIVE_CAPITAL = 10000                    # System 2 running balance
TAIL_HEDGE_QUARTERLY = 1500                     # 1.5% of lottery capital
SURVIVAL_BREAKER_LOTTERY = 75000                # -25% drawdown halt ($100k → $75k floor)
SURVIVAL_BREAKER_CONSERVATIVE = 7500            # -25% drawdown halt ($10k → $7.5k floor)

# =====================================================================
# SYSTEM 1 – MSTR LOTTERY (Aggressive BTC Supercycle Bet)
# =====================================================================
SYSTEM_1_NAME = "MSTR Lottery"
SYSTEM_1_PRIMARY_UNDERLYING = "MSTR"
SYSTEM_1_FALLBACK_UNDERLYING = "IBIT"           # Only if MSTR liquidity fails critical threshold
SYSTEM_1_CADENCE = "Quarterly"                  # First trading day after signal window
SYSTEM_1_POSITION_TYPE = "Deep OTM Calls"
SYSTEM_1_STRIKES = 3                            # Three staggered OTM strikes
SYSTEM_1_RULE = "10× Rule: At 10× premium, auto-sell 50%, lock profits, let remainder ride free"
SYSTEM_1_TAIL_HEDGE = True                      # Auto-buy $1500 premium protective structure concurrent with main buys
SYSTEM_1_OVERLAP_RULE = "MSTR/IBIT exclusive to System 1 – rejected by System 2 scanner"

# =====================================================================
# SYSTEM 2 – CONSERVATIVE DIAGONAL SYSTEM
# =====================================================================
SYSTEM_2_NAME = "Conservative Diagonal"
SYSTEM_2_UNIVERSE = "Full (small/mid/large caps)"
SYSTEM_2_EXCLUSIONS = ["MSTR", "IBIT"]          # Immediate pre-flight rejection
SYSTEM_2_POSITION_TYPES = ["Pure LEAP", "Diagonal"]  # Chosen by IV + pattern
SYSTEM_2_SIZING = "50–250 per trade"            # Disciplined, skill-building
SYSTEM_2_CONFIRMATION = "10-layer pattern stack"
SYSTEM_2_CADENCE = "Continuous / daily scan"

# =====================================================================
# GLOBAL RULES & INFRASTRUCTURE
# =====================================================================
HUMAN_TOUCHPOINTS_ONLY = [
    "System 1 quarterly: single Yes/No to execute 4 orders",
    "System 2 per setup: single Yes/No to enter trade"
]
NO_MANUAL_ACTIONS = [
    "Strike selection",
    "Sizing calculations",
    "Order preparation/typing",
    "10x rule monitoring & execution",
    "Tail hedge placement",
    "Exits / profit taking",
    "Drawdown tracking / halts",
    "Overlap prevention"
]

# =====================================================================
# RESEARCH & STRATEGY – DEEPSEEK COMPUTATIONAL BRAIN
# =====================================================================
# DeepSeek serves as the analytical/computational engine alongside
# Claude Code as the execution layer. DeepSeek handles:
#   1. Pre-trade analysis and second-opinion scoring
#   2. Market regime detection and classification
#   3. Weekly strategy optimization and parameter tuning
#   4. Gronk X/Twitter intelligence analysis

DEEPSEEK_ROLE = "Computational Analyst"
DEEPSEEK_PRE_TRADE = True                         # Every trade gets DeepSeek approval score
DEEPSEEK_REJECT_THRESHOLD = 30                    # Auto-reject trades scoring below 30/100
DEEPSEEK_CAUTION_THRESHOLD = 50                   # Flag trades scoring 30-50 for manual review
DEEPSEEK_REGIME_CHECK = "Daily"                   # Market regime classification frequency
DEEPSEEK_STRATEGY_REVIEW = "Weekly"               # Closed trade analysis frequency
DEEPSEEK_GRONK_SCAN = "Hourly"                    # X/Twitter intelligence scan frequency

# Regime-based position sizing multipliers
REGIME_SIZING = {
    "BULL_STRONG": 1.5,                           # Full aggression
    "BULL_WEAK": 1.0,                             # Normal sizing
    "SIDEWAYS": 0.75,                             # Reduced exposure
    "BEAR_WEAK": 0.5,                             # Defensive
    "BEAR_STRONG": 0.25,                          # Minimal exposure
    "CRASH": 0.0,                                 # No new entries, hedge only
}

# =====================================================================
# SYSTEM 6 – METALS MOMENTUM (Gold, Silver, Rare Earth)
# =====================================================================
SYSTEM_6_NAME = "Metals Momentum"
SYSTEM_6_CAPITAL = 15000                              # $15k allocation
SYSTEM_6_UNIVERSE = ["GLD", "GDX", "NEM", "GOLD", "SLV", "PAAS", "AG", "HL", "MP", "REMX", "LAC"]
SYSTEM_6_POSITION_TYPE = "ATM/OTM Calls"
SYSTEM_6_ENTRY = "Golden Cross (EMA50 > EMA200) + MACD bullish + RSI confirmation"
SYSTEM_6_DTE = "45-90 DTE"
SYSTEM_6_PROFIT_TARGET = 0.60                         # +60%
SYSTEM_6_LOSS_STOP = -0.40                            # -40%
SYSTEM_6_MAX_POSITIONS = 5
SYSTEM_6_POSITION_SIZE = 600                          # ~$600 per options position
SURVIVAL_BREAKER_METALS = 9000                        # -40% drawdown halt ($15k → $9k floor)

# =====================================================================
# SYSTEM 7 – SPACEX IPO (Pre-IPO Proxies + Post-IPO Direct)
# =====================================================================
SYSTEM_7_NAME = "SpaceX IPO"
SYSTEM_7_CAPITAL_PRE = 10000                          # $10k pre-IPO proxy plays
SYSTEM_7_CAPITAL_POST = 25000                         # $25k post-IPO direct options
SYSTEM_7_PRE_IPO_UNIVERSE = ["RKLB", "ASTS", "BKSY", "LUNR", "MNTS", "GOOGL", "LMT", "NOC", "RTX"]
SYSTEM_7_POSITION_TYPE = "ATM/OTM Calls"
SYSTEM_7_ENTRY = "EMA20 > EMA50 + MACD bullish + Volume spike"
SYSTEM_7_DTE = "60-90 DTE"
SYSTEM_7_PROFIT_TARGET = 0.50                         # +50%
SYSTEM_7_LOSS_STOP = -0.30                            # -30%
SYSTEM_7_MAX_POSITIONS_PRE = 4
SYSTEM_7_MAX_POSITIONS_POST = 3
SYSTEM_7_POSITION_SIZE = 500                          # ~$500 per options position
SURVIVAL_BREAKER_SPACEX = 6000                        # -40% halt on pre-IPO ($10k → $6k floor)

# =====================================================================
# SYSTEM 8 – 10X MOONSHOT (High-Growth Multi-Bagger Plays)
# =====================================================================
SYSTEM_8_NAME = "10X Moonshot"
SYSTEM_8_CAPITAL = 10000                              # $10k allocation — lottery ticket sizing
SYSTEM_8_UNIVERSE = {
    "eVTOL": ["JOBY", "ACHR", "LILM"],
    "quantum": ["IONQ", "RGTI", "QUBT"],
    "nuclear": ["SMR", "OKLO"],
    "space": ["RKLB", "LUNR", "ASTS"],
    "biotech": ["DNA", "CRSP", "BEAM"],
    "AI_smallcap": ["BBAI", "SOUN", "BFLY"],
}
SYSTEM_8_POSITION_TYPE = "OTM Calls + Puts"           # 5% OTM for max leverage
SYSTEM_8_ENTRY = "EMA stack (10>21>50) + MACD + Volume explosion + Momentum"
SYSTEM_8_DTE = "60-120 DTE"
SYSTEM_8_PROFIT_TARGET = 1.50                         # +150% (let winners run)
SYSTEM_8_LOSS_STOP = -0.50                            # -50%
SYSTEM_8_TRAIL = "Activates at +80%, trails 30% from peak"
SYSTEM_8_MAX_POSITIONS = 6
SYSTEM_8_POSITION_SIZE = 300                          # ~$300 per position (lottery ticket)
SURVIVAL_BREAKER_MOONSHOT = 5000                      # -50% halt ($10k → $5k floor)
# Backtest: $10k → $34k (+240%) Sharpe 1.71, 16% DD, 134 moonshot trades

# =====================================================================
# SYSTEM 9 – SCHD INCOME WHEEL (Conservative Income)
# =====================================================================
SYSTEM_9_NAME = "SCHD Income PMCC"
SYSTEM_9_CAPITAL = 25000
SYSTEM_9_UNIVERSE = ["SCHD"]
SYSTEM_9_STRATEGY = "Buy 80-delta LEAP call, sell 25-delta monthly calls (PMCC)"
SYSTEM_9_DTE = "LEAP 12+ months, short 30-45 DTE, roll at 50% profit"
SYSTEM_9_TARGET_MONTHLY = 0.015                             # 1.5% monthly income
SYSTEM_9_MAX_POSITIONS = 3
SYSTEM_9_LEAP_STOP = -0.30
SURVIVAL_BREAKER_SCHD = 17500                               # -30% halt

# =====================================================================
# SYSTEM 10 – SPY PMCC (Poor Man's Covered Call)
# =====================================================================
SYSTEM_10_NAME = "SPY PMCC"
SYSTEM_10_CAPITAL = 20000
SYSTEM_10_UNIVERSE = ["SPY"]
SYSTEM_10_STRATEGY = "Buy 80-delta LEAP, sell 25-delta monthly calls"
SYSTEM_10_LEAP_DTE = "12+ months"
SYSTEM_10_SHORT_DTE = "30-45 DTE"
SYSTEM_10_TARGET_MONTHLY = 0.015
SYSTEM_10_MAX_POSITIONS = 2
SYSTEM_10_LEAP_STOP = -0.30                                 # Close if LEAP drops 30%
SURVIVAL_BREAKER_PMCC = 14000                               # -30% halt

# =====================================================================
# SYSTEM 11 – QQQ GROWTH COLLAR (Protected Growth)
# =====================================================================
SYSTEM_11_NAME = "QQQ Growth Collar"
SYSTEM_11_CAPITAL = 15000
SYSTEM_11_UNIVERSE = ["QQQ"]
SYSTEM_11_STRATEGY = "Buy 70-delta LEAP + sell 25-delta calls + buy 15-delta puts"
SYSTEM_11_DTE = "LEAP 12+ months, short legs 30-45 DTE"
SYSTEM_11_MAX_POSITIONS = 2
SURVIVAL_BREAKER_COLLAR = 10500                             # -30% halt

# =====================================================================
# SYSTEM 12 – TQQQ MOMENTUM (Leveraged Momentum)
# =====================================================================
SYSTEM_12_NAME = "TQQQ Momentum"
SYSTEM_12_CAPITAL = 10000
SYSTEM_12_UNIVERSE = ["TQQQ"]
SYSTEM_12_STRATEGY = "Momentum calls/puts + VCA position sizing"
SYSTEM_12_DTE = "30-60 DTE"
SYSTEM_12_PROFIT_TARGET = 0.60
SYSTEM_12_LOSS_STOP = -0.40
SYSTEM_12_VCA_ADD = 200                                     # Add $200 on 20% drawdown
SYSTEM_12_MAX_POSITIONS = 3
SYSTEM_12_POSITION_SIZE = 500
SURVIVAL_BREAKER_TQQQ = 5000                                # -50% halt

# =====================================================================
# SYSTEM 13 — NEURAL REGIME CLASSIFIER (March 21, 2026)
# =====================================================================
# Machine learning regime classifier using calibrated ensemble.
# DOES NOT TRADE. DOES NOT MODIFY v2.8+ ENTRY/EXIT LOGIC.
# Pure awareness layer — classifies BTC market regime and feeds context
# to trader1 alerts, dashboard, Telegram updates, and seasonality table.
SYSTEM_13_NAME = "Neural Regime Classifier"
SYSTEM_13_TYPE = "regime_classification"
SYSTEM_13_MODEL = "CalibratedEnsemble(RandomForest300 + GradientBoosting200)"
SYSTEM_13_CV_ACCURACY = 95.6                                  # 5-fold stratified CV
SYSTEM_13_FEATURES = 65                                       # 13 base × 5 lags (LSTM-inspired lookback)
SYSTEM_13_BASE_FEATURES = [
    "rsi_14", "sma_20_ratio", "sma_50_ratio", "sma_200_ratio",
    "roc_4w", "roc_12w", "roc_26w", "volatility_20w",
    "volume_proxy", "mvrv_like", "ath_ratio", "sma_20_slope", "rsi_momentum"
]
SYSTEM_13_REGIMES = ["ACCUMULATION", "MARKUP", "DISTRIBUTION", "MARKDOWN"]
SYSTEM_13_CURRENT = "DISTRIBUTION"
SYSTEM_13_CONFIDENCE = 82.2
SYSTEM_13_MARKDOWN_PRESSURE = 17.8                            # Rising — transition building
SYSTEM_13_PURPOSE = "Regime classification only — awareness layer, NOT a trading signal"
SYSTEM_13_FEEDS_INTO = [
    "phase_aware_seasonality",                                # Which seasonality column to read
    "trader1_alert_context",                                  # Regime context in Telegram alerts
    "dashboard_cycle_indicator",                              # Dashboard regime card
    "telegram_updates",                                       # Regime change notifications
    "weekend_btc_sentinel",                                   # Sentinel uses regime for alert severity
]
SYSTEM_13_SCRIPT = "regime_classifier.py"
SYSTEM_13_DATA = "regime_state.json"
SYSTEM_13_MODEL_FILE = "regime_model.pkl"

# ── System 13 Integration — ALL Traders (March 21, 2026) ──
# Every trader reads regime_state.json and adapts behavior.
# Trader1 (v2.8+): Logs regime at eval, regime context in Telegram, Monday early eval
# Trader2 (MSTR Put): Regime-adaptive trail width
# Trader3 (SPY Put): Regime-adaptive trail width
# Puts BENEFIT from market drops — trail adjusts accordingly:
SYSTEM_13_TRADER_TRAIL_ADJUST = {
    "MARKDOWN": +5,      # Widen trail 5% — market falling = puts printing, let it ride
    "DISTRIBUTION": +2,  # Slightly wider — late bull, puts have tailwind
    "ACCUMULATION": 0,   # Neutral — no adjustment
    "MARKUP": -3,         # Tighten trail 3% — market rising = puts losing, protect fast
}
# Floor: Trail never goes below 5% regardless of regime adjustment

# ── Reinforcement Learning Layer (March 21, 2026) ──
# The supervised model classifies regimes based on static historical labels.
# The RL layer makes System 13 LEARN FROM ITS OWN PREDICTIONS:
#   1. Every prediction recorded in experience replay buffer
#   2. Outcomes evaluated 4 weeks later (did the regime call match reality?)
#   3. Per-regime confidence adjusted based on real-world accuracy
#   4. Model retrained with experience-weighted samples when accuracy drops
#   5. Telegram alert when rolling accuracy drops below 60%
SYSTEM_13_RL_ENABLED = True
SYSTEM_13_RL_LOOKBACK = 4                                    # Weeks before evaluating outcome
SYSTEM_13_RL_RETRAIN_TRIGGER = 50                            # Retrain after 50 new experiences
SYSTEM_13_RL_DECAY = 0.95                                    # Older experiences decay
SYSTEM_13_RL_ACCURACY_ALERT = 0.60                           # Alert if accuracy drops below 60%
SYSTEM_13_RL_DATA = "rl_experience.json"                     # Experience replay buffer

# ── Phase-Aware Seasonality (Month × Cycle Phase) ──
# Source: Morgan Stanley Four Seasons + historical BTC cycle data (2015-2026)
# The SAME month behaves differently depending on bull vs bear regime.
# System 13 determines which column is active.
PHASE_AWARE_SEASONALITY = {
    "BULL": {
        "January":   {"direction": "green",   "desc": "Reversal start; green but volatile"},
        "February":  {"direction": "green",   "desc": "Strong recovery rally"},
        "March":     {"direction": "green",   "desc": "Very bullish; strong close"},
        "April":     {"direction": "green",   "desc": "Continuation; steady gains"},
        "May":       {"direction": "neutral", "desc": "Pause before summer"},
        "June":      {"direction": "red",     "desc": "Shallow pullback — BUY opportunity"},
        "July":      {"direction": "green",   "desc": "Summer bounce; strong recovery"},
        "August":    {"direction": "neutral", "desc": "Neutral to weak"},
        "September": {"direction": "red",     "desc": "Weakest month — BEST buy opportunity"},
        "October":   {"direction": "green",   "desc": "UPTOBER — strongest month, rally ignition"},
        "November":  {"direction": "green",   "desc": "Massive gains; parabolic top territory"},
        "December":  {"direction": "neutral", "desc": "Topping out; profit-taking"},
    },
    "BEAR": {
        "January":   {"direction": "red",     "desc": "Deep red; continuation of sell-off"},
        "February":  {"direction": "green",   "desc": "Sucker's rally; fades quickly"},
        "March":     {"direction": "red",     "desc": "High volatility; bounce then drop"},
        "April":     {"direction": "neutral", "desc": "Relief rally trap"},
        "May":       {"direction": "red",     "desc": "Bearish; often starts major downtrend"},
        "June":      {"direction": "red",     "desc": "BRUTAL — long liquidations, cascading"},
        "July":      {"direction": "green",   "desc": "Minor consolidation; pause before more pain"},
        "August":    {"direction": "red",     "desc": "Consistently bearish; heavy outflows"},
        "September": {"direction": "red",     "desc": "WORST month — devastating drops"},
        "October":   {"direction": "neutral", "desc": "Dead cat trap; traps bulls (e.g., 2018)"},
        "November":  {"direction": "red",     "desc": "Cycle bottom; capitulation (e.g., FTX 2022)"},
        "December":  {"direction": "neutral", "desc": "Tax-loss selling; low volume"},
    },
    "DISTRIBUTION": {
        "January":   {"direction": "green",   "desc": "Final push higher; retail FOMO at peak"},
        "February":  {"direction": "neutral", "desc": "First signs of exhaustion; divergences"},
        "March":     {"direction": "red",     "desc": "Correction from overextension"},
        "April":     {"direction": "green",   "desc": "Dead cat bounce; double top setup"},
        "May":       {"direction": "red",     "desc": "Sharp reversal; distribution climax"},
        "June":      {"direction": "red",     "desc": "Cascading sells; support breaking"},
        "July":      {"direction": "neutral", "desc": "Relief rally; hopium"},
        "August":    {"direction": "red",     "desc": "Lower highs confirming; trend change"},
        "September": {"direction": "red",     "desc": "Acceleration of selling"},
        "October":   {"direction": "neutral", "desc": "False hope; failed rallies → markdown"},
        "November":  {"direction": "red",     "desc": "Full transition to markdown"},
        "December":  {"direction": "red",     "desc": "Tax-loss selling amplifies decline"},
    },
    "ACCUMULATION": {
        "January":   {"direction": "green",   "desc": "Post-bear optimism begins"},
        "February":  {"direction": "green",   "desc": "Smart money positioning intensifies"},
        "March":     {"direction": "neutral", "desc": "Consolidation; testing support"},
        "April":     {"direction": "green",   "desc": "Breakout attempts; first big moves"},
        "May":       {"direction": "neutral", "desc": "Healthy pullback after April"},
        "June":      {"direction": "neutral", "desc": "Range-bound; building base"},
        "July":      {"direction": "green",   "desc": "Summer breakout setup"},
        "August":    {"direction": "neutral", "desc": "Low volatility; coiling"},
        "September": {"direction": "red",     "desc": "Seasonal dip; shaking weak hands"},
        "October":   {"direction": "green",   "desc": "Breakout month; transition to markup"},
        "November":  {"direction": "green",   "desc": "Confirmation of new uptrend"},
        "December":  {"direction": "green",   "desc": "Year-end positioning for new cycle"},
    },
}

# =====================================================================
# MANDATORY TRAILING STOP LOSS — ALL POSITIONS (v45.0)
# =====================================================================
# EVERY position opened by ANY trader system MUST have a trailing stop
# placed on IBKR at time of entry. NO EXCEPTIONS.
# Two stop types: FLAT (fixed %) and LADDERED (tightens as gains grow).
TRAILING_STOP_MANDATORY = True
TRAILING_STOP_DEFAULT_PCT = 30                              # 30% trailing stop from high water mark
TRAILING_STOP_TYPE = "TRAIL"                                # IBKR order type: TRAIL (trailing stop market)
TRAILING_STOP_TIF = "GTC"                                   # Good til cancelled — persists until filled or expiry
TRAILING_STOP_ADJUSTABLE = True                             # Can be tightened (never loosened) as position profits

# Per-system trailing stop overrides (tighter for shorter-dated, wider for moonshots)
TRAILING_STOP_OVERRIDES = {
    "system1": 30,      # MSTR Lottery — 30% (deep OTM, let it ride)
    "trader3": 30,      # Energy Momentum — 30%
    "trader4": 30,      # Short Squeeze — 30%
    "trader5": None,     # Spreads — managed as unit, no individual leg stops
    "trader6": 30,      # Metals — 30%
    "trader7": 30,      # SpaceX — 30%
    "trader8": 30,      # 10x Moonshot — 30% (floor)
    "trader9": 25,      # SCHD Income — 25% (tighter, conservative)
    "trader10": 25,     # SPY PMCC — 25%
    "trader11": 25,     # QQQ Collar — 25%
    "trader12": 30,     # TQQQ — 30%
}

# =====================================================================
# LADDERED TRAILING STOP — MOONSHOT/LOTTERY STRATEGIES (v45.0)
# =====================================================================
# For pure lottery strategies (MSTR BTC Moonshot), a flat trailing stop
# would kill the position on normal volatility. Instead, the trail
# TIGHTENS as gains increase — letting small moves breathe while
# locking the bag on massive runs.
#
# LADDERED STOP TIERS (mstr_moonshot):
#   0-100% gain (1-2x):    NO STOP — pure lottery, let it breathe
#   100-500% gain (2-5x):  30% trailing stop from high water mark (FLOOR)
#   500-1000% gain (5-10x): 30% trailing stop from high water mark
#   1000-2000% gain (10-20x): 25% trailing stop from high water mark
#   2000%+ gain (20x+):    20% trailing stop — LOCK THE BAG
#
# Implementation: Software stop monitor (stop_monitor.py) checks every
# 5 minutes. No IBKR native stop at entry (would trigger on normal swings).
# Trail is from HIGH WATER MARK — never from entry price.
#
# Exit rules (separate from trailing stop):
#   20x entry cost → sell 50% of position
#   50x entry cost → sell 25% more
#   Remainder rides with 20% trail until expiration or stop trigger
LADDERED_STOP_SYSTEMS = "ALL"  # Every system uses laddered trailing stops
LADDERED_STOP_TIERS = {
    # MSTR Moonshot: NO trail until +300% — deep OTM LEAPs need room to breathe
    "mstr_moonshot": [
        {"min_gain_pct": 0, "trail_pct": None},       # No stop (lottery mode)
        {"min_gain_pct": 300, "trail_pct": 30},        # 3x: 30% trail from peak
        {"min_gain_pct": 500, "trail_pct": 25},        # 5x: 25% trail + sell 25%
        {"min_gain_pct": 1000, "trail_pct": 20},       # 10x: 20% trail + sell 25%
        {"min_gain_pct": 2000, "trail_pct": 15},       # 20x: 15% trail + sell 25%
        {"min_gain_pct": 5000, "trail_pct": 10},       # 50x: 10% trail + sell final 25%
    ],
    # 10x Moonshot strategies: earlier activation, tighter trail
    "10x_momentum": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 50, "trail_pct": 25},
        {"min_gain_pct": 100, "trail_pct": 20},
        {"min_gain_pct": 200, "trail_pct": 15},
    ],
    "10x_runner_v2": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 50, "trail_pct": 25},
        {"min_gain_pct": 100, "trail_pct": 20},
        {"min_gain_pct": 200, "trail_pct": 15},
    ],
    # Daily momentum strategies: trail at +30%, tighten at 50/100%
    "energy_momentum": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 30, "trail_pct": 20},
        {"min_gain_pct": 50, "trail_pct": 15},
        {"min_gain_pct": 100, "trail_pct": 12},
    ],
    "short_squeeze": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 30, "trail_pct": 20},
        {"min_gain_pct": 50, "trail_pct": 15},
        {"min_gain_pct": 100, "trail_pct": 12},
    ],
    "breakout_momentum": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 30, "trail_pct": 20},
        {"min_gain_pct": 50, "trail_pct": 15},
        {"min_gain_pct": 100, "trail_pct": 12},
    ],
    "tqqq_momentum": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 30, "trail_pct": 20},
        {"min_gain_pct": 50, "trail_pct": 15},
        {"min_gain_pct": 100, "trail_pct": 12},
    ],
    "ntr_ag_momentum": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 30, "trail_pct": 20},
        {"min_gain_pct": 50, "trail_pct": 15},
        {"min_gain_pct": 100, "trail_pct": 12},
    ],
    # MSTR Lottery: tighter tiers (position-HWM based)
    "mstr_lottery": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 15, "trail_pct": 15},
        {"min_gain_pct": 30, "trail_pct": 12},
        {"min_gain_pct": 50, "trail_pct": 10},
    ],
    # Mean reversion / intraday: tightest tiers
    "sideways_condor": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 15, "trail_pct": 15},
        {"min_gain_pct": 30, "trail_pct": 12},
        {"min_gain_pct": 50, "trail_pct": 10},
    ],
    "fence_bar": [
        {"min_gain_pct": 0, "trail_pct": None},
        {"min_gain_pct": 15, "trail_pct": 15},
        {"min_gain_pct": 30, "trail_pct": 12},
        {"min_gain_pct": 50, "trail_pct": 10},
    ],
}

# =====================================================================
# MSTR BTC MOONSHOT — SYSTEM PARAMETERS (v45.0)
# =====================================================================
MOONSHOT_NAME = "MSTR BTC Moonshot"
MOONSHOT_CAPITAL = 100000                                   # $100k all-in, no leverage
MOONSHOT_SYMBOL = "MSTR"
MOONSHOT_STRIKE_LOW = 3.0                                   # 3x spot minimum
MOONSHOT_STRIKE_HIGH = 6.0                                  # 6x spot maximum
MOONSHOT_STRIKE_SWEET = 4.8                                 # 4.8x spot sweet spot
MOONSHOT_MIN_DTE = 365                                      # 12 month minimum (LEAPs)
MOONSHOT_MAX_DTE = 550                                      # 18 month maximum
MOONSHOT_ENTRY_TIMING = "Q4 post-halving (October-November)"
MOONSHOT_20X_SELL = 0.50                                    # Sell 50% at 20x
MOONSHOT_50X_SELL = 0.25                                    # Sell 25% more at 50x
MOONSHOT_BACKTEST = "$100k → $2.2M (22.4x) on 2023 Q4 entry"
SURVIVAL_BREAKER_MOONSHOT_LEAP = 0                          # No survival breaker — this is a lottery

# =====================================================================
# SPREAD POSITION MANAGEMENT (v44.0)
# =====================================================================
# IBKR REGULATION: Cannot place opposite-side stop orders on individual
# spread legs (SEC rule — only market makers can be on both sides).
# IBKR also rejects "riskless combination" combo close orders.
#
# SOLUTION: Two-tier stop system:
#   Tier 1 — IBKR native TRAIL stops on all single-leg positions (calls, puts)
#   Tier 2 — Software stop monitor (stop_monitor.py) for:
#     a) Spread positions (put spreads, call spreads, iron condors)
#     b) Any position where IBKR rejects native stop orders (permissions)
#
# SPREAD CLOSE RULES:
#   - Monitor spread net value every 5 minutes during market hours
#   - Track high water mark of spread value
#   - If spread value drops 30% from high water mark → close BOTH legs via market orders
#   - Close order: SELL long leg + BUY short leg simultaneously (two separate market orders)
#   - Max loss on a $5-wide spread is always capped at ($5 × 100 - credit received)
#   - Spreads expiring within 5 DTE: auto-close to avoid assignment risk
#
# SPREAD TYPES AND HANDLING:
#   Put Credit Spread (Trader5): Short higher strike, long lower strike
#     → Max loss = (width × 100) - credit. Monitor net debit value.
#   Call Credit Spread: Short lower strike, long higher strike
#     → Same as above, inverted.
#   Iron Condor: Two credit spreads — monitor each wing independently
#   Diagonal/Calendar: Monitor net value, close at 30% loss from peak
#
# ASSIGNMENT RISK:
#   Short leg ITM within 5 DTE → auto-close entire spread
#   Short leg ITM by more than $2 at any time → alert via Telegram
SPREAD_MONITOR_INTERVAL = 300                               # Check spread P&L every 5 minutes
SPREAD_TRAIL_PCT = 0.30                                     # 30% trailing from high water
SPREAD_DTE_AUTO_CLOSE = 5                                   # Close spreads within 5 DTE
SPREAD_ITM_ALERT_THRESHOLD = 2.00                           # Alert if short leg ITM by $2+

# ENFORCEMENT: Auditor checks every 30 minutes that all open positions
# have corresponding trailing stop orders on IBKR. Any position missing
# a stop triggers an immediate Telegram alert + auto-places the stop.
STOP_AUDIT_ENABLED = True
STOP_AUDIT_INTERVAL = 1800                                  # 30 minutes

# =====================================================================
# MSTR TREASURY DATA — Updated March 22, 2026
# =====================================================================
# Source: MSTR 8-K filings, The Wealth Continuum analysis, SEC filings
# MSTR = "Bitcoin treasury machine" — leveraged BTC proxy via reflexivity loop:
#   BTC up → MSTR up → cheaper capital raises → more BTC buys → loop accelerates
#
# Holdings: 761,000+ BTC (~3.5% of total BTC supply)
# Average cost: ~$75,696/coin ($57.6B total acquisition cost)
# Diluted shares: ~390M (post preferred stock offerings)
# Wall Street consensus: 14 analysts, "Strong Buy", $349 avg target (+157%)
#
# Scenario projections (from current ~$135 MSTR):
#   BTC $80K  (+16%) → MSTR ~$185-$210  (+32-50%)
#   BTC $100K (+45%) → MSTR ~$280-$330  (+100-135%)
#   BTC $126K (ATH)  → MSTR parabolic   (3x+ multiplier)
#
# mNAV premium at 1.007x (March 2026) = trading near NAV = historically cheap
# This is the optimal v2.8+ entry zone — accumulation phase pricing
# AUTO-UPDATED weekly by mstr_treasury_updater.py → mstr_treasury.json
# These constants are FALLBACK only — trader_v28.py reads live data first.
# Sources: bitbo.io (holdings), stockanalysis.com (shares)
MSTR_BTC_HOLDINGS = 761068                        # BTC held by MSTR (auto-updated)
MSTR_AVG_COST_PER_BTC = 66384.56                  # Average acquisition cost (from SEC filings)
MSTR_DILUTED_SHARES = 293157000                   # Diluted share count (TTM)
MSTR_WALL_ST_TARGET = 349                         # Analyst consensus target

# =====================================================================
# INSTRUMENT RULES
# =====================================================================
PRIMARY_INSTRUMENTS = ["OPTIONS", "FUTURES"]                # Default instruments for all strategies
# Stocks, shares, ETF holdings are allowed BUT require Commander approval first
# Nothing is prohibited — everything requires Yes/No from Lawson before execution

TOTAL_EXPERIMENTAL_ALLOCATION = 240000                      # $240k total (prev $170k + $70k ETF income)

BROKER_API_TARGET = "Interactive Brokers TWS API"
NOTIFICATION_CHANNEL = "Telegram"
SCRIPT_OWNER = "Rudy v2.0 + execution layer"
# =====================================================================
# MANDATORY PROFIT-TAKING TIERS — ALL POSITIONS (v46.0)
# =====================================================================
# Every position takes PARTIAL profits at milestones. No all-or-nothing.
# Profits are locked incrementally while letting winners ride.
#
# REGULAR STRATEGIES (trader3, 4, 5, 6, 7, 12):
#   +50% gain:  Sell 33% of original position (lock initial profits)
#   +100% gain: Sell 33% more (66% total sold)
#   Remaining 34% rides with trailing stop until stop or expiry
#
# AGGRESSIVE STRATEGIES (trader8 — 10X Moonshot):
#   +100% gain: Sell 25%
#   +300% gain: Sell 25% more
#   +500% gain: Sell 25% more
#   Remaining 25% rides with 30% trailing stop
#
# LOTTERY STRATEGIES (system1_v8 — MSTR Lottery):
#   +1000% (10x): Sell 50% (existing 10x rule)
#   +2000% (20x): Sell 25% more
#   Remainder rides free
#
# MOONSHOT STRATEGIES (trader_moonshot — MSTR BTC Moonshot):
#   +2000% (20x): Sell 50%
#   +5000% (50x): Sell 25% more
#   Remainder rides with 20% laddered trail
#
# IMPLEMENTATION:
#   - Partial sells via MarketOrder with tif="GTC"
#   - Each tier tracked in position JSON (profit_take_50, profit_take_100, etc.)
#   - original_qty preserved for percentage calculations
#   - Telegram notification on each partial sell
#   - accountant.record_trade() called for each partial sell
PROFIT_TAKING_MANDATORY = True
PROFIT_TAKING_REGULAR = {
    "tier1": {"gain_pct": 50, "sell_pct": 33},
    "tier2": {"gain_pct": 100, "sell_pct": 33},
}
PROFIT_TAKING_AGGRESSIVE = {
    "tier1": {"gain_pct": 100, "sell_pct": 25},
    "tier2": {"gain_pct": 300, "sell_pct": 25},
    "tier3": {"gain_pct": 500, "sell_pct": 25},
}
PROFIT_TAKING_LOTTERY = {
    "tier1": {"gain_pct": 1000, "sell_pct": 50},
    "tier2": {"gain_pct": 2000, "sell_pct": 25},
}
PROFIT_TAKING_MOONSHOT = {
    "tier1": {"gain_pct": 2000, "sell_pct": 50},
    "tier2": {"gain_pct": 5000, "sell_pct": 25},
}

# =====================================================================
# v2.2 PRODUCTION PARAMETERS — MSTR Cycle-Low LEAP Strategy
# =====================================================================
# Validated via QuantConnect backtest: +31.2% net profit (Daily, 2016-2026)
# These are the LOCKED production settings for live deployment.
V22_TRADE_RESOLUTION = "daily"                    # Daily evaluation (not weekly/monthly)
V22_LEAP_MULTIPLIER_BASE = 10.0                   # 10x LEAP multiplier (stock proxy)
V22_SLIPPAGE_STOCK_PCT = 0.005                    # 0.5% stock slippage → ~5% LEAP equiv
V22_PREMIUM_CAP = 1.5                             # Max mNAV premium for entry (1.5x)
V22_PANIC_FLOOR_ENABLED = True                    # -25% LEAP P&L panic exit on losers
V22_PANIC_FLOOR_PCT = -25.0                       # Panic floor threshold
V22_SMA_PERIOD = 200                              # 200-week SMA for dip+reclaim
V22_STOCH_RSI_THRESHOLD = 70                      # StochRSI entry filter (< 70)
V22_INITIAL_FLOOR_PCT = 30                        # 30% initial floor (entry × 0.70)
V22_SCALE_IN = "50/50"                            # Two-tranche entry on qualifying signals
V22_MAX_ENTRIES_PER_CYCLE = 1                     # One entry per BTC cycle
V22_EUPHORIA_SELL_PREMIUM = 3.5                   # Sell 25% at mNAV > 3.5x
V22_BACKTEST_RESULT = "+31.2% net (Daily, 10x LEAP, 0.5% slippage, panic floor ON)"

# v2.2 Laddered Trail (LEAP-equivalent gains)
V22_TRAIL_TIERS = [
    {"min_gain_pct": 0, "trail_pct": None},       # No stop initially
    {"min_gain_pct": 200, "trail_pct": 30},        # 3x: 30% trail
    {"min_gain_pct": 400, "trail_pct": 25},        # 5x: 25% trail + sell 25%
    {"min_gain_pct": 900, "trail_pct": 20},        # 10x: 20% trail + sell 25%
    {"min_gain_pct": 1900, "trail_pct": 15},       # 20x: 15% trail + sell 25%
    {"min_gain_pct": 4900, "trail_pct": 10},       # 50x: 10% trail + sell final 25%
]

# =====================================================================
# v2.8 PRODUCTION PARAMETERS — MSTR Cycle-Low LEAP Dynamic Blend
# =====================================================================
# Walk-Forward Validated: WFE=1.20 (OOS > IS), +692.2% stitched OOS return
# Parameter stability: tight_conservative_tight won 5/7 OOS windows
# Backtested: +74.3% Daily, +58.3% Weekly (2016-2025)
# Supersedes v2.2 — this is the ACTIVE live strategy.

V28_TRADE_RESOLUTION = "weekly"                    # Weekly evaluation (daily also validated)
V28_SLIPPAGE_STOCK_PCT = 0.005                     # 0.5% stock slippage → ~5% LEAP equiv

# ── Dynamic Premium-Based LEAP Blend ──
# The LEAP multiplier adjusts automatically based on MSTR's NAV premium.
# Lower premium = more aggressive leverage; higher premium = conservative.
# This is the core v2.8 innovation over v2.2's fixed 10x multiplier.
V28_DYNAMIC_BLEND = {
    # Walk-forward optimal: tight_conservative_tight (won 5/7 OOS windows)
    # Tighter premium bands + conservative multipliers = less exposure at high premiums
    "LOW": {                                       # Premium < 0.7x mNAV (tight band)
        "multiplier": 7.2,                         # Conservative: less leverage even at discount
        "threshold": 0.7,
    },
    "FAIR": {                                      # Premium 0.7x–1.0x mNAV (tight band)
        "multiplier": 6.5,                         # Conservative: moderate leverage at fair value
        "threshold": 1.0,
    },
    "ELEVATED": {                                  # Premium 1.0x–1.3x mNAV (tight band)
        "multiplier": 4.8,                         # Conservative: reduced leverage at premium
        "threshold": 1.3,
    },
    "EUPHORIC": {                                  # Premium > 1.3x mNAV (tight band)
        "multiplier": 3.3,                         # Conservative: minimal leverage in euphoria
        "threshold": 999,
    },
}

# ── v2.8 Laddered Trailing Stops ──
# Trail width tightens as LEAP-equivalent gains increase.
# Wider trails at lower gains let winners breathe; tighter at high gains lock profits.
V28_LADDER_TIERS = [
    # Walk-forward optimal: TIGHT trails (won 7/7 OOS windows — unanimous)
    # Tighter trails lock profits faster, reducing drawdown at the cost of
    # occasionally being stopped out early. WFE 1.20 proves this is optimal.
    {"min_leap_gain_pct": 500,   "trail_pct": 35},   # 5x+   → 35% trail (tight, lock gains early)
    {"min_leap_gain_pct": 1000,  "trail_pct": 30},   # 10x+  → 30% trail
    {"min_leap_gain_pct": 2000,  "trail_pct": 25},   # 20x+  → 25% trail
    {"min_leap_gain_pct": 5000,  "trail_pct": 20},   # 50x+  → 20% trail
    {"min_leap_gain_pct": 10000, "trail_pct": 12},   # 100x+ → 12% trail (tightest, lock the bag)
]

# ── v2.8 Profit-Taking Tiers ──
# Diamond Hands: only 10% at each milestone — let the position compound.
V28_PROFIT_TIERS = [
    {"min_leap_gain_pct": 1000,  "sell_pct": 10},    # 10x  → sell 10%
    {"min_leap_gain_pct": 2000,  "sell_pct": 10},    # 20x  → sell 10%
    {"min_leap_gain_pct": 5000,  "sell_pct": 10},    # 50x  → sell 10%
    {"min_leap_gain_pct": 10000, "sell_pct": 10},    # 100x → sell 10%
]

# ── v2.8 35% Original Floor ──
# Hard floor at 35% below entry price. If MSTR drops below entry × 0.65,
# exit immediately. Deactivates once LEAP gains exceed 500% (5x) to avoid
# killing a winner on a pullback.
V28_INITIAL_FLOOR_PCT = 0.65                         # Exit if price < entry × 0.65 (35% floor)
V28_FLOOR_DEACTIVATE_AT = 500                        # Floor off once LEAP gain > 500%

# ── v2.8 Other Risk Parameters ──
V28_PANIC_FLOOR_PCT = -35.0                          # Exit losers at -35% LEAP P&L
V28_EUPHORIA_SELL_PREMIUM = 3.5                      # Sell 25% at mNAV > 3.5x
V28_SMA_PERIOD = 200                                 # 200-week SMA for dip+reclaim
V28_BTC_250W_MA = "watch_level"                      # 250W MA (~$56K) — capitulation zone, cycle bottoms
V28_BTC_300W_MA = "watch_level"                      # 300W MA (~$50K) — absolute floor, worst-case wick
# When BTC approaches 250W MA, the 200W SMA dip (v2.8+ arm trigger) is IMMINENT.
# 250W and 300W are awareness levels, NOT entry/exit filters. They tell the Commander
# how close we are to the trigger zone and how deep the capitulation has gone.
V28_STOCH_RSI_THRESHOLD = 70                         # StochRSI entry filter (< 70)
V28_MAX_HOLD_BARS = 567                              # ~27 months daily
V28_TARGET_MULT = 200.0                              # 200x target (aspirational)
V28_RISK_CAPITAL_PCT = 0.25                           # 25% of portfolio per position
V28_MAX_ENTRIES_PER_CYCLE = 1                         # One entry per BTC cycle

# ── v2.8 Entry Filters (all must pass) ──
# 1. MSTR dip below 200W SMA then reclaim (arms the trigger)
# 2. BTC > 200-week MA
# 3. StochRSI < 70 (not overbought)
# 4. BTC not in death cross (50D < 200D)
# 5. No existing position open
# 6. Optional: TradingView webhook confluence (double confirmation)

# ── v2.8 Exit Conditions ──
# 1. BTC Death Cross (50D < 200D EMA)
# 2. Max Hold (567 bars)
# 3. Target Hit (200x LEAP gain)
# 4. Below EMA50 + Losing (MSTR < EMA50 and stock P&L negative)
# 5. BTC < 200W MA (full exit if LEAP gain < 100%, partial 50% if > 100%)
# 6. Premium Compression (mNAV < 0.5 and stock P&L negative)
# 7. Initial Floor (price < entry × 0.65, deactivates at 5x)
# 8. Laddered Trail Stop (tightening trail from peak)
# 9. Panic Floor (-35% LEAP P&L on losers)
# 10. Euphoria Premium (mNAV > 3.5 → sell 25%)

# Walk-Forward Analysis Results (7 anchored windows, 27-combo grid):
V28_WFE = 1.20                                      # WFE > 0.5 = robust; 1.20 = OOS beats IS
V28_STITCHED_OOS_RETURN = 692.2                      # +692.2% cumulative OOS return
V28_BEST_PARAMS = "tight_conservative_tight"         # Won 5/7 OOS windows
V28_BACKTEST_RESULT = "+74.3% Daily, +58.3% Weekly (2016-2025, QC backtest)"

# =====================================================================
# SAFETY INFRASTRUCTURE — MANDATORY (v50.0)
# ── CORE RULE: IBKR IS THE SINGLE SOURCE OF TRUTH FOR ALL PRICES ──
# ALL price data (BTC, MSTR, SPY, options, account values) MUST come
# from IBKR TWS via ib_insync. No exceptions.
# - Never hardcode prices (ATH, 200W SMA, bull/bear thresholds) as display values
# - GBTC proxy is for INTERNAL 200W SMA calculation only — never displayed as "BTC price"
# - ATH is tracked dynamically in trader state (btc_ath), not frozen
# - If IBKR is unavailable: show "—" or "Connecting..." — never stale/proxy data
# - Applies to: dashboard, trader1, trader2, trader3, regime classifier, sentinel, Telegram
IBKR_IS_PRICE_TRUTH = True
IBKR_PORT_LIVE = 7496
IBKR_ACCOUNT = "U15746102"

# =====================================================================
# INSTITUTIONAL EXECUTION INTELLIGENCE (v50.0)
# =====================================================================
# Based on algorithm engineering research: institutional VWAP/TWAP algos
# exploit predictable retail stop placement and order patterns.
# Rudy's execution layer defends against this:
#
# 1. STEALTH ORDERS: All orders use LimitOrder with adaptive pricing
#    instead of raw MarketOrder. Price set from live bid/ask mid with
#    random offset and penny jitter to avoid round number detection.
# 2. NO ROUND NUMBERS: Prices ending in .00 or .50 get +$0.03 offset
# 3. ODD LOT JITTER: Avoid predictable round lot sizes where possible
# 4. INTERNAL STOPS: All trailing stops and floors are evaluated in code,
#    NOT placed as exchange stop orders. No algo can see our stop levels.
# 5. FALLBACK: If bid/ask unavailable, falls back to MarketOrder (GTC)
# 6. ALL TRADERS: Stealth execution on trader1, trader2, and trader3
STEALTH_EXECUTION_ENABLED = True
STEALTH_OPTION_OFFSET_RANGE = (0.05, 0.15)       # Random offset for options
STEALTH_STOCK_OFFSET_RANGE = (0.01, 0.05)         # Random offset for stocks
STEALTH_PENNY_JITTER_RANGE = (0.01, 0.04)         # Jitter to break patterns
STEALTH_AVOID_ROUND_PRICES = True                  # No .00 or .50 prices

# =====================================================================
# Built after the March 2026 incident where 22 orphan positions were
# discovered after a "successful" closeout. NEVER trust fire-and-forget.
# Every order must be VERIFIED. Every position must be RECONCILED.

# ── Kill Switch (kill_switch.py) ──
# Emergency flatten: cancels ALL orders, closes ALL positions, verifies zero.
# Steps: 1) reqGlobalCancel  2) BUY-TO-CLOSE all shorts, SELL-TO-CLOSE all longs
#         3) Poll for fills (60s timeout, 3 retries)  4) Verify zero positions
#         5) Telegram alert with results
KILL_SWITCH_ENABLED = True
KILL_SWITCH_SCRIPT = "kill_switch.py"
KILL_SWITCH_MAX_RETRIES = 3
KILL_SWITCH_POLL_INTERVAL = 2                            # Seconds between fill checks
KILL_SWITCH_POLL_TIMEOUT = 60                            # Max seconds to wait per retry
KILL_SWITCH_TELEGRAM_ON_ACTIVATE = True                  # 🚨 alert on activation
KILL_SWITCH_TELEGRAM_ON_FAIL = True                      # ⚠️ alert if positions remain

# ── Order Fill Confirmation ──
# NO fire-and-forget orders. Every order placed must be polled until filled,
# cancelled, or timed out. If cancelled/inactive, retry up to 2 times.
ORDER_CONFIRM_MANDATORY = True
ORDER_CONFIRM_POLL_INTERVAL = 2                          # Seconds between status checks
ORDER_CONFIRM_TIMEOUT = 120                              # Max seconds to wait for fill
ORDER_CONFIRM_MAX_RETRIES = 2                            # Retry cancelled/inactive orders
ORDER_CONFIRM_CLEANUP_BEFORE = True                      # Cancel stale orders on same contract before placing new

# ── Position Reconciliation ──
# After EVERY trade (entry or exit), verify IBKR actual position matches expected.
# Mismatch triggers immediate Telegram alert.
RECONCILIATION_MANDATORY = True
RECONCILIATION_AFTER_ENTRY = True                        # Verify position exists after buy
RECONCILIATION_AFTER_EXIT = True                         # Verify position closed after sell
RECONCILIATION_MISMATCH_ACTION = "TELEGRAM_ALERT"        # Alert Commander on any discrepancy

# ── Daily Position Audit (position_audit.py) ──
# Cron job compares IBKR reality vs Rudy's JSON state files.
# Catches: ORPHAN (in IBKR, not in Rudy), GHOST (in Rudy, not in IBKR),
# QUANTITY mismatch between IBKR and Rudy state.
AUDIT_ENABLED = True
AUDIT_SCRIPT = "position_audit.py"
AUDIT_SCHEDULE = "Daily 8:00 AM ET"                      # Before market open
AUDIT_TELEGRAM_ON_MISMATCH = True                        # Alert on any discrepancy
AUDIT_TELEGRAM_QUIET = True                              # Only alert on problems (not clean audits)
AUDIT_LOG_DIR = "logs/"                                  # audit_YYYY-MM-DD.json saved daily

# ── Dashboard Truth Layer ──
# Dashboard /positions page shows IBKR actual positions, NOT JSON files.
# Includes real-time unrealized P&L, open orders, and kill switch button.
DASHBOARD_LIVE_POSITIONS = True
DASHBOARD_KILL_SWITCH_BUTTON = True                      # Big red button on /positions page
DASHBOARD_REFRESH_INTERVAL = 30                          # Auto-refresh every 30 seconds

# ── Pre-Trade Safety Checklist ──
# Before ANY order placement, the system MUST:
PRE_TRADE_CHECKLIST = [
    "1. Cancel stale orders on same contract (cleanup_stale_orders)",
    "2. Verify TWS connection is active",
    "3. Confirm account has sufficient buying power",
    "4. Place order with execute_with_confirmation() — NOT fire-and-forget",
    "5. Poll until fill confirmed or max retries exhausted",
    "6. Reconcile IBKR position vs expected state",
    "7. Update position JSON with actual fill price and quantity",
    "8. Send Telegram confirmation with fill details",
]

# ── Post-Trade Verification ──
# After ANY position close, the system MUST:
POST_TRADE_CHECKLIST = [
    "1. Verify position is gone from IBKR (verify_flat for MSTR)",
    "2. Update position JSON to closed status with actual fill price",
    "3. Record trade in accountant ledger",
    "4. Send Telegram exit confirmation",
]

# =====================================================================
# ACTIVE STRATEGY STATUS (v50.0)
# =====================================================================
# ONLY v2.8+ Trend Adder is active. LIVE TRADING on account U15746102.
# All other systems (1-12) are DISABLED.
# All non-v2.8+ cron jobs disabled March 2026.
# All non-v2.8+ positions closed out March 2026.
ACTIVE_STRATEGIES = ["v2.8+"]
DISABLED_STRATEGIES = ["system1", "system2", "trader3", "trader4", "trader5",
                       "trader6", "trader7", "trader8", "trader9", "trader10",
                       "trader11", "trader12", "moonshot"]
DISABLE_REASON = "Commander ordered v2.8+ live-only — March 2026"

# ── v2.8+ Walk-Forward & Stress Test Results ──
V28PLUS_VALIDATION = {
    # ── Walk-Forward (March 2026) ──
    "wfe": 1.18,
    "oos_return": "+6,750.6%",
    "parameter_stability": "standard_tight_minimal won 7/7 windows",
    # ── Regime Stress Tests ──
    "regime_stress": "0/5 false positives in adverse regimes",
    "regimes_tested": [
        "2018 Crypto Winter (BTC $20K→$3K) — CLEAN: 0 orders",
        "2021 Post-Top Distribution (BTC $69K→$17K) — OK: adder fired but +27.4% alpha",
        "2022 Bear Rally Traps — OK: no false reclaims",
        "2022 Full Bear — OK: adder contained",
        "2020 COVID Flash Crash — CLEAN: V-recovery, no false signals",
    ],
    # ── Execution Stress Tests ──
    "execution_realism": "Survives 200bps slippage (Sharpe 0.171)",
    "slippage_ladder": {
        "25bps": {"net": 138.5, "sharpe": 0.279, "survival": 1.09},
        "50bps": {"net": 126.5, "sharpe": 0.258, "survival": 1.00},
        "100bps": {"net": 113.5, "sharpe": 0.236, "survival": 0.90},
        "200bps": {"net": 89.7, "sharpe": 0.171, "survival": 0.71},
    },
    "worst_case_scenario": "75bps slip + 2% gap-through = still profitable (ratio 0.91)",
    # ── Robustness Tests ──
    "capital_scaling": "Convex — more capital = better Sharpe",
    "not_curve_fit": "75% avg survival under ±20% random perturbation",
    "path_independent": "History-seeded 200W SMA — CV=0% across all start dates",
    # ── Cross-Ticker Validation (March 2026) ──
    "avgo_v28plus": "+501.5%, Sharpe 0.888, 18.8% DD, 106 orders — edge confirmed",
    "avgo_v28_base": "+164.5%, Sharpe 0.594 — adder adds 3x returns",
    "avgo_verdict": "Trend adder is dominant return driver (2/3 of total return)",
    "mara_v28plus": "FAILED — 3 orders, +13.9%, Sharpe 0.12 — no structural edge",
    # ── Safety Infrastructure (March 2026) ──
    "premium_compression_alert": "Active — Telegram fires if mNAV drops >15% from 30d high",
    "strike_adjustment_engine": "Live on /projections — real-time (10s refresh), dynamic recs by mNAV band",
    "hitl_strike_roll": "Telegram inline buttons + Dashboard banner + iPhone Claude + Cowork MCP",
    "pid_lockfiles": "All 3 daemons protected — duplicates blocked on spawn",
    "daily_loss_limit": "2% NLV daily cap — auto-pause + Telegram alert",
    "consecutive_loss_shutdown": "5 stop-outs = pause trading, require HITL restart",
    "self_evaluation": "4-hour loop — compares live vs predicted, alerts on drift",
    "lookahead_audit": "Audited March 2026 — no lookahead bias found in QC or live code",
    # ── Advanced Stress Tests (March 20, 2026) ──
    "flash_crash_gap_and_trap": {
        "verdict": "PASS",
        "description": "Simulated -10% to -30% gap-down opens on MSTR",
        "key_finding": "Put positions BENEFIT from crashes. -20% gap = +6.7% portfolio gain",
        "details": "Premium compression alerts fire correctly. No trail stop gap-through issues.",
    },
    "monte_carlo_bootstrap": {
        "verdict": "CONDITIONAL",
        "description": "5,000 bootstrap shuffles of MSTR weekly returns (80% annual vol)",
        "key_finding": "40%+ drawdown near-certain over 5yr WITHOUT circuit breakers",
        "details": "P50 return +152%, P5 return -86.8%. 2% daily cap + 5-loss shutdown = survival.",
        "interpretation": "Barbell alone can't survive extreme paths. Circuit breakers are REQUIRED.",
        "p95_max_dd": "96.2%",
        "paths_exceeding_40pct_dd": "99.9%",
        "daily_loss_trigger_rate": "100%",
        "five_loss_trigger_rate": "92%",
    },
    "mnav_apocalypse": {
        "verdict": "PASS (was FAIL before 0.75x kill switch)",
        "description": "BTC flat $70K, MSTR de-rates from 2.5x → 0.25x",
        "key_finding": "0.75x kill switch saves 2x capital at 0.5x, 7.5x at 0.25x",
        "kill_point": "0.75x mNAV — $100 safety LEAP still has $3.70 intrinsic",
        "failure_point_without_kill": "0.5x — all LEAPs lose intrinsic value",
        "capital_saved_at_05x": "$6,213",
        "capital_saved_at_025x": "$10,636",
    },
    "mnav_kill_switch": {
        "threshold": 0.75,
        "action": "Close ALL positions, block new entries, DEFCON 1 Telegram",
        "recovery": "Manual restart required. Entries unblocked above 1.0x mNAV.",
        "stress_tested": True,
    },
    # ── System 13: Neural Regime Classifier (March 21, 2026) ──
    "system_13_regime_classifier": {
        "model": "CalibratedEnsemble(RF300+GB200)",
        "cv_accuracy": "95.6% (5-fold stratified)",
        "features": "65 (13 base × 5 lags)",
        "regimes": ["ACCUMULATION", "MARKUP", "DISTRIBUTION", "MARKDOWN"],
        "current_regime": "DISTRIBUTION at 82.2%",
        "transition_pressure": "MARKDOWN at 17.8% — rising",
        "purpose": "Awareness layer only — does NOT modify v2.8+ entry/exit logic",
        "phase_aware_seasonality": True,
        "reinforcement_learning": True,
    },
    "system_13_reinforcement_learning": {
        "type": "Experience Replay + Adaptive Confidence",
        "description": "RL feedback loop that learns from prediction outcomes",
        "lookback": "4 weeks — evaluates each prediction against actual BTC returns",
        "scoring": "ACCUMULATION(>-5%), MARKUP(>+5%), DISTRIBUTION(-10% to +10%), MARKDOWN(<-5%)",
        "confidence_adjustment": "Per-regime accuracy multiplier (0.0-1.0x)",
        "retrain_trigger": "50 new experiences → auto-retrain with experience-weighted samples",
        "accuracy_alert": "Telegram if rolling accuracy drops below 60%",
        "decay_factor": "0.95 — recent experiences weighted more than old ones",
        "purpose": "System 13 adapts to new market behavior instead of relying on static labels",
    },
    # ── Last Updated ──
    "last_stress_test": "2026-03-21",
}

# ── CROSS-TICKER RESEARCH LOG ──
CROSS_TICKER_RESULTS = {
    "MARA": {
        "status": "research_only",
        "version": "v2.8+",
        "result": "FAILED — 3 orders in 7 years, +13.9%, Sharpe 0.12",
        "reason": "No mNAV premium dynamic. Lacks structural edge.",
        "note": "Future target ONLY if MARA-specific valuation metric developed",
    },
    "AVGO": {
        "status": "research_validated",
        "v28plus": "+501.5%, Sharpe 0.888, 18.8% DD, 106 orders",
        "v28_base": "+164.5%, Sharpe 0.594, 15.4% DD, 100 orders",
        "trend_adder_impact": "3x return boost with only 6 additional orders",
        "wf_issue": "OOS windows produce 0 trades — AVGO rarely dips below 200W SMA",
        "verdict": "Edge exists but insufficient OOS trades for deployment",
    },
}
MARA_STATUS = "research_only"
AVGO_STATUS = "research_validated_not_deployed"

# =====================================================================
# BTC CYCLE PHASE INTELLIGENCE (March 21, 2026)
# =====================================================================
# Bitcoin is in the DISTRIBUTION / EARLY WINTER phase of the 4-year
# halving cycle. This is NOT a filter change — v2.8+ entry logic is
# UNCHANGED. This is an awareness layer for strategic context.
#
# CURRENT CYCLE POSITION:
#   ATH: ~$126,200 (October 6, 2025)
#   Current: ~$70,500 (March 21, 2026)
#   Drawdown from ATH: ~44-47%
#   Months post-April 2024 halving: ~23
#   Phase: Distribution → Early Winter transition
#
# KEY FRAMEWORKS ALIGNED:
#   1. Morgan Stanley 4-Seasons: "Fall" ended Oct 2025, now in "Winter"
#      - Historical crypto winters last 12-14 months post-peak
#      - Winter started ~Oct 2025, could extend into late 2026
#   2. Traditional 4-Year Halving Cycle:
#      - Peak 12-18 months post-halving → Oct 2025 fits perfectly
#      - Then multi-month bear/correction (40-80% drawdowns typical)
#      - Potential bottom: $60K range H1 2026 (Bernstein estimate)
#   3. On-Chain Indicators:
#      - Mega-whales (1,000+ BTC) buying dips → redistribution
#      - LTH supply near highs → old hands selling to new buyers
#      - CryptoQuant Bull Cycle Indicator: bear consolidation
#      - No euphoria (FOMO absent), no extreme capitulation yet
#
# CRITICAL LEVEL: $78,500-$80,000 (bull/bear threshold)
#   - Sustained below = deeper correction toward 200W SMA
#   - Sustained above = potential resumption
#
# v2.8+ IMPLICATIONS:
#   - The 200W SMA dip+reclaim is MORE LIKELY in this environment
#   - Entry signal could fire in next few months (validates Phase 1 plan)
#   - BTC dropping toward 200W SMA (~$42K) = v2.8+ sweet spot
#   - Distribution phase = be READY, don't be surprised by the dip
#   - Institutional maturity (ETFs) may moderate downside vs past cycles
#
# STRATEGIC POSTURE: "Sell rallies until proven otherwise, but
#   accumulate on deep dips" — v2.8+ is built for exactly this.
#   The system waits for the dip+reclaim, which this cycle phase
#   suggests is approaching.

# ── BTC Phase-Aware Monthly Seasonality ──
# The SAME month behaves completely differently in bull vs bear markets.
# Trader1 detects current phase (bull/bear) and reads the correct column.
# Source: DeepSeek analysis + CoinGlass/Bitbo/Bitcoin Suisse/StatMuse data.
#
# PHASE DETECTION: BTC > $80K + <25% from ATH = BULL
#                  BTC < $80K + >40% from ATH = BEAR
#                  Transition zone = 200W SMA as tiebreaker
#
# ┌───────┬─────────────────────────────────────┬─────────────────────────────────────┐
# │ Month │ 🟢 BULL MARKET                      │ 🔴 BEAR MARKET                     │
# ├───────┼─────────────────────────────────────┼─────────────────────────────────────┤
# │ Jan   │ Reversal start; green but volatile  │ Deep red; continuation of sell-off  │
# │ Feb   │ Strong recovery rally               │ Sucker's rally; fades quickly       │
# │ Mar   │ Very bullish; strong close           │ High vol; bounce before drop        │
# │ Apr   │ Continuation; steady gains           │ Relief rally peak — could be trap   │
# │ May   │ Mixed; pause before summer           │ Bearish; starts major downtrend     │
# │ Jun   │ Shallow pullback — BUY THE DIP      │ BRUTAL — liquidations, miner capit  │
# │ Jul   │ Summer bounce; strong recovery       │ Minor consolidation; more pain      │
# │ Aug   │ Neutral to weak                      │ Consistently bearish; heavy outflow │
# │ Sep   │ Weakest — BEST buying opportunity   │ THE WORST — devastating drops       │
# │ Oct   │ STRONGEST — parabolic run starts    │ Dead cat trap — deceives bulls      │
# │ Nov   │ MASSIVE gains — parabolic top       │ Cycle bottom — CAPITULATION         │
# │ Dec   │ Topping out; profit-taking          │ Tax-loss selling; low volume        │
# └───────┴─────────────────────────────────────┴─────────────────────────────────────┘
#
# HIGH-ALERT MONTHS (eval every 2 hours):
#   Bear: Jun, Aug, Sep, Oct, Nov (dip zone + dead cat traps)
#   Bull: Sep, Oct, Nov (entry zone + parabolic — must catch signals FAST)
#
# KEY INSIGHT: In bear mode, Oct/Nov rallies are TRAPS. In bull mode, they're
# the explosive run you've been waiting for. Phase detection is critical.
#
# Monday 9:30 AM sentinel check: auto-eval if BTC dropped >5% over weekend.
# DATA SOURCES: CoinGlass, Bitbo Charts, Bitcoin Suisse, StatMuse, DeepSeek

BTC_CYCLE_PHASE = "DISTRIBUTION_EARLY_WINTER"
BTC_ATH = 126200                                  # Oct 6, 2025
BTC_ATH_DATE = "2025-10-06"
BTC_HALVING_DATE = "2024-04-20"                   # April 2024 halving
BTC_BULL_BEAR_THRESHOLD = 80000                   # $80K — above = bull, below = bear
BTC_200W_SMA_APPROX = 42000                       # Updated March 2026
BTC_EXPECTED_BOTTOM_RANGE = (55000, 65000)        # Analyst consensus for cycle bottom
BTC_WINTER_END_ESTIMATE = "2026-Q4"               # Could extend to Q1 2027

# ── BTC Weekend Sentinel ──
# 24/7 BTC monitoring — because BTC trades weekends/holidays and
# weekend moves directly impact Monday's MSTR open.
BTC_SENTINEL_ENABLED = True
BTC_SENTINEL_SCRIPT = "btc_sentinel.py"
BTC_SENTINEL_CHECK_INTERVAL = 900                 # 15 minutes
BTC_SENTINEL_ALERT_THRESHOLDS = [-5, -10, -15, -20, -25, -30]  # % from anchor
BTC_SENTINEL_CRITICAL_LEVEL = BTC_200W_SMA_APPROX # Alert if BTC drops below

# =====================================================================
# FUTURE OPPORTUNITY: TESLA CYBERCAB FLEET (Research / Long-Term)
# =====================================================================
# Source: "Build Your Cybercab Empire!" — Brighter with Herbert (YouTube)
# Analyst: Cern Basher (CFA, BrilliantAdvice)
# Date noted: March 2026
#
# THESIS: Individual owners scale a Tesla Cybercab fleet by reinvesting
# Robotaxi network profits. Exponential compounding via reinvestment.
#
# KEY ASSUMPTIONS (Conservative / "Worst Case" 30% utilization):
CYBERCAB_MODEL = {
    "vehicle_price": 30000,
    "down_payment": 5000,
    "starting_cash": 6000,
    "utilization_pct": 30,           # ~7.2 hours/day in service
    "avg_speed_mph": 25,
    "avg_trip_miles": 5,
    "empty_miles_pct": 40,
    "base_fare": 3.00,
    "per_mile_fare": 1.40,           # Current Austin levels
    "tesla_network_share_pct": 35,   # Tesla takes 35% of gross
    "owner_net_profit_per_year": 23000,   # ~$1,929/month after ALL expenses
    "expenses_included": [
        "Charging ($0.35/kWh)",
        "Cleaning",
        "Parking",
        "Insurance",
        "Tires",
        "FSD subscription ($199/month)",
        "Depreciation (over 600,000 miles)",
    ],
    "reinvestment_rule": "1/3 of monthly cash flow toward next $5,000 down payment",
    "revenue_NOT_counted": [
        "Parked compute (Digital Optimus / MacroHard)",
        "Advertising revenue",
        "Entertainment / curated experiences",
    ],
}

# PROJECTED FLEET SCALING (Reinvestment Compounding):
CYBERCAB_PROJECTIONS = {
    "year_1": {"vehicles": 5, "monthly_pretax_cashflow": 4700},
    "year_2": {"vehicles": 38, "monthly_pretax_cashflow": 35800},
    "year_3": {"vehicles": 300, "monthly_pretax_cashflow": 285000},
}

# STRATEGIC NOTES:
# - Elon allows owner participation to avoid monopoly/regulatory risk
# - Model also works for Model Y/3/Cybertruck (higher cost, cargo/luxury use)
# - Risks: market saturation, fare compression, utilization drops, regulatory
# - Higher utilization (50-65%) or better fares accelerate dramatically
# - Parked AI compute could generate revenue even when vehicle is idle
# - Some argue owning TSLA stock may be safer than operating the business
#
# ACTION: Monitor Tesla Robotaxi launch timeline. If Cybercab becomes
# available for individual purchase with Robotaxi network access,
# evaluate as a capital deployment vehicle alongside MSTR LEAP strategy.
# Potential synergy: MSTR LEAP profits → Cybercab fleet seed capital.

# =====================================================================
# ARTICLE XI — AUTHORIZED TRADER REGISTRY & CLONE PROHIBITION
# Locked: March 2026 | Effective: Immediately
# =====================================================================
#
# SECTION 1 — AUTHORIZED TRADERS (Exhaustive List)
# ┌──────────────┬──────────────────────────────┬───────────────────────────────┐
# │ Identity     │ Script                       │ Authority                     │
# ├──────────────┼──────────────────────────────┼───────────────────────────────┤
# │ Trader1      │ trader_v28.py                │ BUY + SELL (v2.8+ LEAP only)  │
# │ Trader2      │ trader2_mstr_put.py          │ SELL ONLY (MSTR Put exit)     │
# │ Trader3      │ trader3_spy_put.py           │ SELL ONLY (SPY Put exit)      │
# └──────────────┴──────────────────────────────┴───────────────────────────────┘
#
# SECTION 2 — CLONE PROHIBITION (Absolute Rule)
#
# The system is PERMANENTLY AND ABSOLUTELY FORBIDDEN from:
#
#   1. Creating any new trader script that has buy or sell authority
#      without explicit Commander approval and a constitutional amendment.
#
#   2. Duplicating, copying, or deriving any version of trader_v28.py,
#      trader2_mstr_put.py, or trader3_spy_put.py under any new filename
#      or path that has placeOrder / execute_trade / buy / sell capability.
#
#   3. Running ANY trader script not in the Authorized Trader Registry
#      above. Scripts trader1.py, trader2.py, trader3.py, trader4.py
#      through trader12.py, trader_moonshot.py, trader_v30.py, and ALL
#      future unnamed variants are LOCKED OUT via authority guard blocks.
#
#   4. Removing or bypassing the authority guard block from any locked
#      script without a constitution amendment.
#
#   5. Registering new LaunchAgents for any trader script not in the
#      Authorized Trader Registry without explicit Commander approval.
#
# SECTION 3 — CLOSE PERMISSION AUTHORITY LOCK
#
# Once the Commander grants Trader2 or Trader3 permission to close
# their positions, NO other trader — including future scripts — may
# execute any buy or sell order until the close is confirmed complete
# and the Commander explicitly re-opens trading authority.
#
# SECTION 4 — VIOLATION CONSEQUENCE
#
# Any code that attempts to circumvent this article by creating,
# renaming, or importing unauthorized trading logic shall be treated
# as a critical safety violation. Claude must refuse the action and
# alert the Commander via Telegram before proceeding.
#
# =====================================================================

VERSION = "50.0"
STATUS = "Locked – v2.8+ LIVE, 3-business preamble restored, safety infrastructure mandatory, kill switch + audit + order confirmation + premium compression alert + Article XI clone prohibition"
