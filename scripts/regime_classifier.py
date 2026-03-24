#!/usr/bin/env python3
"""
System 13 — Neural Regime Classifier (v1.0)
BTC cycle regime classification using Gradient Boosting on sequential features.
Inspired by LSTM sequential modeling, implemented pragmatically.

Classifies BTC into four regimes:
  ACCUMULATION — Post-crash bottom building
  MARKUP       — Bull trend, rising above SMAs
  DISTRIBUTION — Late bull, high vol, weakening
  MARKDOWN     — Bear trend, falling below SMAs

Part of Rudy v2.0 trading system. Does NOT trade.
"""
import argparse
import json
import os
import sys
import time
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import joblib
import requests

warnings.filterwarnings("ignore")

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path("/Users/eddiemae/rudy")
DATA_DIR = BASE_DIR / "data"
SCRIPTS_DIR = BASE_DIR / "scripts"
MODEL_PATH = DATA_DIR / "regime_model.pkl"
STATE_PATH = DATA_DIR / "regime_state.json"
TRADER_STATE_PATH = DATA_DIR / "trader_v28_state.json"
BTC_CACHE_PATH = DATA_DIR / "btc_weekly_cache.json"

# ── Telegram ─────────────────────────────────────────────────────────────────
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    import telegram as tg
except ImportError:
    tg = None

REGIME_LABELS = ["ACCUMULATION", "MARKUP", "DISTRIBUTION", "MARKDOWN"]
REGIME_MAP = {label: i for i, label in enumerate(REGIME_LABELS)}

# ── Known cycle phases for supervised labeling ───────────────────────────────
# Each tuple: (start_date, end_date, regime_label)
KNOWN_PHASES = [
    ("2015-01-01", "2015-10-15", "ACCUMULATION"),
    ("2015-10-16", "2017-06-10", "MARKUP"),
    ("2017-06-11", "2017-12-31", "DISTRIBUTION"),
    ("2018-01-01", "2018-12-31", "MARKDOWN"),
    ("2019-01-01", "2020-03-15", "ACCUMULATION"),
    ("2020-03-16", "2021-04-14", "MARKUP"),
    ("2021-04-15", "2021-11-10", "DISTRIBUTION"),
    ("2021-11-11", "2022-11-20", "MARKDOWN"),
    ("2022-11-21", "2024-01-10", "ACCUMULATION"),
    ("2024-01-11", "2025-10-15", "MARKUP"),
    ("2025-10-16", "2026-12-31", "DISTRIBUTION"),  # current estimate
]


def send_telegram(msg):
    """Send alert via shared telegram module."""
    if tg:
        try:
            tg.send(msg)
        except Exception as e:
            print(f"[WARN] Telegram send failed: {e}")
    else:
        print(f"[WARN] Telegram module not available. Message: {msg}")


# ══════════════════════════════════════════════════════════════════════════════
# DATA FETCHING
# ══════════════════════════════════════════════════════════════════════════════

def fetch_btc_weekly_from_coingecko(start_date="2014-09-01"):
    """
    Fetch BTC weekly close prices from CoinGecko free API.
    Returns list of (date_str, price_usd) tuples, weekly.
    Uses cache to avoid hammering the API.
    """
    cache_valid = False
    if BTC_CACHE_PATH.exists():
        try:
            with open(BTC_CACHE_PATH) as f:
                cache = json.load(f)
            cache_time = datetime.fromisoformat(cache["fetched_at"])
            if (datetime.now() - cache_time).total_seconds() < 86400:  # 24h cache
                print(f"  Using cached BTC data ({len(cache['data'])} weeks)")
                return cache["data"]
        except Exception:
            pass

    print("  Fetching BTC historical data from CoinGecko...")
    start_ts = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
    end_ts = int(datetime.now().timestamp())

    url = "https://api.coingecko.com/api/v3/coins/bitcoin/market_chart/range"
    params = {
        "vs_currency": "usd",
        "from": start_ts,
        "to": end_ts,
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"  [WARN] CoinGecko fetch failed: {e}")
        return _fallback_btc_data()

    prices = data.get("prices", [])
    if not prices:
        print("  [WARN] No price data from CoinGecko")
        return _fallback_btc_data()

    # Convert daily prices to weekly (Sunday close)
    daily = {}
    for ts_ms, price in prices:
        dt = datetime.fromtimestamp(ts_ms / 1000)
        date_str = dt.strftime("%Y-%m-%d")
        daily[date_str] = price

    # Resample to weekly
    weekly = []
    sorted_dates = sorted(daily.keys())
    if not sorted_dates:
        return _fallback_btc_data()

    current = datetime.strptime(sorted_dates[0], "%Y-%m-%d")
    end = datetime.strptime(sorted_dates[-1], "%Y-%m-%d")

    while current <= end:
        # Find the closest date within this week
        best_date = None
        best_price = None
        for d in range(7):
            check = (current + timedelta(days=d)).strftime("%Y-%m-%d")
            if check in daily:
                best_date = check
                best_price = daily[check]
        if best_price is not None:
            weekly.append([best_date, best_price])
        current += timedelta(weeks=1)

    # Cache it
    try:
        with open(BTC_CACHE_PATH, "w") as f:
            json.dump({"fetched_at": datetime.now().isoformat(), "data": weekly}, f)
    except Exception:
        pass

    print(f"  Fetched {len(weekly)} weekly data points")
    return weekly


def _fallback_btc_data():
    """
    Use the existing trader_v28_state.json BTC weekly closes as fallback.
    Prices are in thousands (54.78 = $54,780).
    Data starts ~2017-03.
    """
    print("  Using fallback data from trader_v28_state.json")
    try:
        with open(TRADER_STATE_PATH) as f:
            state = json.load(f)
        closes = state.get("btc_weekly_closes", [])
        if not closes:
            return []

        # Approximate dates: 472 weeks back from 2026-03-21
        base_date = datetime(2026, 3, 21)
        n = len(closes)
        weekly = []
        for i, price in enumerate(closes):
            dt = base_date - timedelta(weeks=(n - 1 - i))
            # Convert from thousands to actual USD
            weekly.append([dt.strftime("%Y-%m-%d"), price * 1000])
        return weekly
    except Exception as e:
        print(f"  [ERROR] Fallback data load failed: {e}")
        return []


def get_btc_weekly_prices():
    """Get BTC weekly prices, preferring CoinGecko, falling back to local state."""
    data = fetch_btc_weekly_from_coingecko(start_date="2014-09-01")
    if len(data) < 100:
        print("  CoinGecko data insufficient, trying fallback...")
        data = _fallback_btc_data()
    return data


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE ENGINEERING
# ══════════════════════════════════════════════════════════════════════════════

def compute_rsi(prices, period=14):
    """Compute RSI from price array."""
    rsi = np.full(len(prices), np.nan)
    if len(prices) < period + 1:
        return rsi

    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))

    return rsi


def compute_sma(prices, period):
    """Compute simple moving average."""
    sma = np.full(len(prices), np.nan)
    if len(prices) < period:
        return sma
    cumsum = np.cumsum(prices)
    sma[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
    return sma


def compute_roc(prices, period):
    """Rate of change over N periods."""
    roc = np.full(len(prices), np.nan)
    for i in range(period, len(prices)):
        if prices[i - period] != 0:
            roc[i] = (prices[i] - prices[i - period]) / prices[i - period]
    return roc


def compute_volatility(prices, period=20):
    """Rolling standard deviation of weekly returns."""
    returns = np.full(len(prices), np.nan)
    for i in range(1, len(prices)):
        if prices[i - 1] != 0:
            returns[i] = (prices[i] - prices[i - 1]) / prices[i - 1]

    vol = np.full(len(prices), np.nan)
    for i in range(period, len(prices)):
        window = returns[i - period + 1:i + 1]
        valid = window[~np.isnan(window)]
        if len(valid) >= period // 2:
            vol[i] = np.std(valid)
    return vol


def compute_features(prices):
    """
    Compute full feature matrix from price array.
    Returns (feature_matrix, feature_names).
    """
    prices = np.array(prices, dtype=float)
    n = len(prices)

    # Core indicators
    rsi_14 = compute_rsi(prices, 14)
    sma_20 = compute_sma(prices, 20)
    sma_50 = compute_sma(prices, 50)
    sma_200 = compute_sma(prices, 200)

    # SMA ratios
    sma_20_ratio = np.where(sma_20 > 0, prices / sma_20, np.nan)
    sma_50_ratio = np.where(sma_50 > 0, prices / sma_50, np.nan)
    sma_200_ratio = np.where(sma_200 > 0, prices / sma_200, np.nan)

    # Rate of change
    roc_4 = compute_roc(prices, 4)
    roc_12 = compute_roc(prices, 12)
    roc_26 = compute_roc(prices, 26)

    # Volatility
    vol_20 = compute_volatility(prices, 20)

    # Volume proxy (absolute weekly return)
    vol_proxy = np.full(n, np.nan)
    for i in range(1, n):
        if prices[i - 1] != 0:
            vol_proxy[i] = abs((prices[i] - prices[i - 1]) / prices[i - 1])

    # MVRV-like: ratio of current price to 200W SMA (realized value proxy)
    mvrv_like = sma_200_ratio.copy()

    # Distance from all-time high (drawdown)
    ath = np.full(n, np.nan)
    running_max = prices[0]
    for i in range(n):
        running_max = max(running_max, prices[i])
        ath[i] = prices[i] / running_max if running_max > 0 else np.nan

    # SMA trend direction (20W SMA slope over 4 weeks)
    sma_20_slope = np.full(n, np.nan)
    for i in range(4, n):
        if not np.isnan(sma_20[i]) and not np.isnan(sma_20[i - 4]) and sma_20[i - 4] > 0:
            sma_20_slope[i] = (sma_20[i] - sma_20[i - 4]) / sma_20[i - 4]

    # RSI momentum (change in RSI over 4 weeks)
    rsi_momentum = np.full(n, np.nan)
    for i in range(4, n):
        if not np.isnan(rsi_14[i]) and not np.isnan(rsi_14[i - 4]):
            rsi_momentum[i] = rsi_14[i] - rsi_14[i - 4]

    feature_names = [
        "rsi_14", "sma_20_ratio", "sma_50_ratio", "sma_200_ratio",
        "roc_4w", "roc_12w", "roc_26w", "volatility_20w",
        "volume_proxy", "mvrv_like", "ath_ratio", "sma_20_slope",
        "rsi_momentum"
    ]

    features = np.column_stack([
        rsi_14, sma_20_ratio, sma_50_ratio, sma_200_ratio,
        roc_4, roc_12, roc_26, vol_20,
        vol_proxy, mvrv_like, ath, sma_20_slope,
        rsi_momentum
    ])

    return features, feature_names


def add_sequential_features(features, lookback=4):
    """
    Add lagged features to capture sequential patterns (LSTM-inspired).
    For each feature, include values from t-1, t-2, ..., t-lookback.
    """
    n, d = features.shape
    expanded = np.full((n, d * (lookback + 1)), np.nan)

    for i in range(n):
        # Current features
        expanded[i, :d] = features[i]
        # Lagged features
        for lag in range(1, lookback + 1):
            if i >= lag:
                expanded[i, lag * d:(lag + 1) * d] = features[i - lag]

    return expanded


def label_dates(dates, prices):
    """
    Assign regime labels based on known cycle phases.
    Returns array of labels (int) with -1 for unlabeled.
    """
    labels = np.full(len(dates), -1, dtype=int)

    for start_str, end_str, regime in KNOWN_PHASES:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d")
        end_dt = datetime.strptime(end_str, "%Y-%m-%d")
        regime_id = REGIME_MAP[regime]

        for i, date_str in enumerate(dates):
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            if start_dt <= dt <= end_dt:
                labels[i] = regime_id

    return labels


# ══════════════════════════════════════════════════════════════════════════════
# MODEL
# ══════════════════════════════════════════════════════════════════════════════

def train_model(weekly_data, lookback=4):
    """
    Train an ensemble classifier on labeled BTC regime data.
    Uses Random Forest + Gradient Boosting voting ensemble with
    calibrated probabilities for reliable confidence estimates.
    """
    from sklearn.ensemble import (
        GradientBoostingClassifier,
        RandomForestClassifier,
        VotingClassifier,
    )
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    from sklearn.preprocessing import StandardScaler

    dates = [d[0] for d in weekly_data]
    prices = np.array([d[1] for d in weekly_data], dtype=float)

    print(f"\n[TRAIN] Computing features for {len(prices)} weeks of data...")
    features, feature_names = compute_features(prices)

    print(f"[TRAIN] Adding sequential features (lookback={lookback})...")
    seq_features = add_sequential_features(features, lookback=lookback)

    print("[TRAIN] Labeling data with known cycle phases...")
    labels = label_dates(dates, prices)

    # Build expanded feature names
    expanded_names = list(feature_names)
    for lag in range(1, lookback + 1):
        expanded_names += [f"{name}_lag{lag}" for name in feature_names]

    # Filter to labeled + valid rows
    valid_mask = (labels >= 0) & (~np.any(np.isnan(seq_features), axis=1))
    X = seq_features[valid_mask]
    y = labels[valid_mask]
    valid_dates = [dates[i] for i in range(len(dates)) if valid_mask[i]]

    print(f"[TRAIN] Valid labeled samples: {len(X)}")
    for regime in REGIME_LABELS:
        count = np.sum(y == REGIME_MAP[regime])
        print(f"  {regime}: {count} samples")

    if len(X) < 50:
        print("[ERROR] Not enough labeled data for training. Need at least 50 samples.")
        return None

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Train ensemble: RF + GBM via soft voting
    print("\n[TRAIN] Training ensemble classifier (RF + GBM)...")

    rf = RandomForestClassifier(
        n_estimators=300,
        max_depth=6,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
    )

    gbm = GradientBoostingClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.08,
        subsample=0.8,
        min_samples_leaf=5,
        random_state=42,
    )

    ensemble = VotingClassifier(
        estimators=[("rf", rf), ("gbm", gbm)],
        voting="soft",
        weights=[1, 1],
    )

    # Calibrate probabilities for realistic confidence
    print("[TRAIN] Calibrating probabilities (isotonic regression)...")
    cv_inner = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    calibrated_model = CalibratedClassifierCV(
        ensemble, method="isotonic", cv=cv_inner
    )
    calibrated_model.fit(X_scaled, y)

    # Cross-validation on the calibrated model
    print("[TRAIN] Running 5-fold cross-validation...")
    cv_outer = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(calibrated_model, X_scaled, y, cv=cv_outer, scoring="accuracy")
    print(f"[TRAIN] CV Accuracy: {cv_scores.mean():.3f} (+/- {cv_scores.std():.3f})")

    # Feature importance from the RF component
    rf_standalone = RandomForestClassifier(
        n_estimators=300, max_depth=6, min_samples_leaf=5,
        class_weight="balanced", random_state=42,
    )
    rf_standalone.fit(X_scaled, y)
    importances = rf_standalone.feature_importances_
    top_indices = np.argsort(importances)[::-1][:10]
    print("\n[TRAIN] Top 10 features (RF importance):")
    for idx in top_indices:
        if idx < len(expanded_names):
            print(f"  {expanded_names[idx]}: {importances[idx]:.4f}")

    # Package model
    model_package = {
        "model": calibrated_model,
        "scaler": scaler,
        "feature_names": feature_names,
        "expanded_names": expanded_names,
        "lookback": lookback,
        "cv_accuracy": float(cv_scores.mean()),
        "cv_std": float(cv_scores.std()),
        "trained_at": datetime.now().isoformat(),
        "n_samples": len(X),
    }

    # Save
    joblib.dump(model_package, MODEL_PATH)
    print(f"\n[TRAIN] Model saved to {MODEL_PATH}")
    print(f"[TRAIN] CV Accuracy: {cv_scores.mean():.1%}")

    return model_package


def evaluate(weekly_data, model_package=None):
    """
    Evaluate current BTC regime using trained model.
    Returns regime classification dict.
    """
    if model_package is None:
        if not MODEL_PATH.exists():
            print("[ERROR] No trained model found. Run with --train first.")
            return None
        model_package = joblib.load(MODEL_PATH)

    model = model_package["model"]
    scaler = model_package["scaler"]
    lookback = model_package["lookback"]
    feature_names = model_package["feature_names"]

    dates = [d[0] for d in weekly_data]
    prices = np.array([d[1] for d in weekly_data], dtype=float)

    # Compute features
    features, _ = compute_features(prices)
    seq_features = add_sequential_features(features, lookback=lookback)

    # Get latest valid point
    latest_idx = len(seq_features) - 1
    while latest_idx >= 0 and np.any(np.isnan(seq_features[latest_idx])):
        latest_idx -= 1

    if latest_idx < 0:
        print("[ERROR] No valid feature data for evaluation.")
        return None

    X_latest = seq_features[latest_idx:latest_idx + 1]
    X_scaled = scaler.transform(X_latest)

    # Predict
    proba = model.predict_proba(X_scaled)[0]
    pred_idx = np.argmax(proba)
    current_regime = REGIME_LABELS[pred_idx]
    confidence = float(proba[pred_idx])

    all_probs = {REGIME_LABELS[i]: round(float(proba[i]), 4) for i in range(len(REGIME_LABELS))}

    # Recent regime history (last 12 weeks)
    regime_history = []
    for offset in range(min(12, latest_idx + 1)):
        idx = latest_idx - offset
        if np.any(np.isnan(seq_features[idx])):
            continue
        X_hist = scaler.transform(seq_features[idx:idx + 1])
        hist_proba = model.predict_proba(X_hist)[0]
        hist_regime = REGIME_LABELS[np.argmax(hist_proba)]
        hist_conf = float(np.max(hist_proba))
        regime_history.append({
            "date": dates[idx],
            "regime": hist_regime,
            "confidence": round(hist_conf, 4),
        })

    regime_history.reverse()

    # Transition detection
    transition_alert = None
    if len(regime_history) >= 4:
        recent = [r["regime"] for r in regime_history[-4:]]
        older = [r["regime"] for r in regime_history[:4]] if len(regime_history) >= 8 else []
        if older and recent[-1] != older[-1]:
            # Check if transition is solidifying
            recent_mode = max(set(recent), key=recent.count)
            if older:
                older_mode = max(set(older), key=older.count)
                if recent_mode != older_mode:
                    transition_alert = f"{older_mode} → {recent_mode} (confidence {confidence:.0%})"

    # Current price info
    current_price = prices[latest_idx]  # GBTC proxy value, NOT actual BTC price
    current_date = dates[latest_idx]

    # Get actual BTC price from trader state (IBKR live)
    actual_btc_price = current_price
    try:
        if TRADER_STATE_PATH.exists():
            with open(TRADER_STATE_PATH) as f:
                ts = json.load(f)
            actual_btc_price = ts.get("last_btc_price", current_price)
    except Exception:
        pass

    result = {
        "current_regime": current_regime,
        "confidence": round(confidence, 4),
        "all_probabilities": all_probs,
        "features_used": feature_names,
        "last_updated": datetime.now().isoformat(),
        "btc_price_gbtc_proxy": round(current_price, 2),
        "btc_price": round(actual_btc_price, 2),
        "data_date": current_date,
        "regime_history": regime_history,
        "transition_alert": transition_alert,
        "model_accuracy": round(model_package.get("cv_accuracy", 0), 4),
    }

    # ── RL Integration ──
    # 1. Evaluate past predictions against actual outcomes
    rl_evaluate_outcomes(actual_btc_price)
    # 2. Adjust current confidence based on RL experience
    result = rl_adjust_confidence(result)
    # 3. Record this prediction for future evaluation
    rl_record_prediction(result)

    # Check for regime change and alert
    _check_regime_change(result)

    # Save state
    with open(STATE_PATH, "w") as f:
        json.dump(result, f, indent=2)

    return result


# ══════════════════════════════════════════════════════════════════════════════
# REINFORCEMENT LEARNING — EXPERIENCE REPLAY + ADAPTIVE CONFIDENCE
# ══════════════════════════════════════════════════════════════════════════════
# The supervised model classifies regimes based on historical labels, but it
# can't learn from its own predictions. The RL layer fixes this:
#   1. Records every prediction + the actual BTC outcome 4 weeks later
#   2. Scores predictions: correct regime call = +1 reward, wrong = -1
#   3. Maintains a confidence adjustment factor per regime
#   4. Periodically retrains the model with new experience data
#   5. Detects when the model is losing accuracy (regime shift) and alerts

RL_STATE_PATH = DATA_DIR / "rl_experience.json"
RL_LOOKBACK_WEEKS = 4          # Evaluate prediction accuracy after 4 weeks
RL_MIN_EXPERIENCES = 10        # Min experiences before adjusting confidence
RL_RETRAIN_TRIGGER = 50        # Retrain after this many new experiences
RL_DECAY_FACTOR = 0.95         # Older experiences decay (recent matter more)
RL_ACCURACY_ALERT = 0.60       # Alert if rolling accuracy drops below 60%


def _load_rl_state():
    """Load RL experience replay buffer."""
    if RL_STATE_PATH.exists():
        try:
            with open(RL_STATE_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "experiences": [],           # List of {date, predicted, confidence, btc_price, outcome, reward}
        "confidence_adjustments": {  # Per-regime accuracy multiplier
            "ACCUMULATION": 1.0,
            "MARKUP": 1.0,
            "DISTRIBUTION": 1.0,
            "MARKDOWN": 1.0,
        },
        "rolling_accuracy": 1.0,
        "total_predictions": 0,
        "total_correct": 0,
        "retrain_counter": 0,
        "last_retrain": None,
        "model_generation": 1,
    }


def _save_rl_state(rl_state):
    """Save RL experience replay buffer."""
    try:
        with open(RL_STATE_PATH, "w") as f:
            json.dump(rl_state, f, indent=2)
    except Exception as e:
        print(f"[RL] Failed to save state: {e}")


def rl_record_prediction(regime_result):
    """
    Record a new prediction in the experience replay buffer.
    Called after every evaluate().
    """
    rl = _load_rl_state()

    experience = {
        "date": regime_result["last_updated"][:10],
        "predicted_regime": regime_result["current_regime"],
        "confidence": regime_result["confidence"],
        "btc_price": regime_result.get("btc_price", 0),
        "all_probs": regime_result.get("all_probabilities", {}),
        "outcome": None,        # Filled in later by rl_evaluate_outcomes()
        "outcome_date": None,
        "reward": None,
        "btc_price_outcome": None,
    }

    rl["experiences"].append(experience)
    rl["total_predictions"] += 1
    _save_rl_state(rl)
    print(f"[RL] Recorded prediction: {experience['predicted_regime']} ({experience['confidence']:.0%})")


def rl_evaluate_outcomes(current_btc_price):
    """
    Look back at predictions made 4+ weeks ago and score them.
    Determines if the predicted regime was correct based on actual price action.

    Regime validation rules:
      ACCUMULATION → BTC should be flat or rising (4W return > -5%)
      MARKUP       → BTC should be rising (4W return > +5%)
      DISTRIBUTION → BTC should show high vol, may be flat or declining
      MARKDOWN     → BTC should be falling (4W return < -5%)
    """
    rl = _load_rl_state()
    cutoff = datetime.now() - timedelta(weeks=RL_LOOKBACK_WEEKS)
    evaluated_count = 0

    for exp in rl["experiences"]:
        # Skip already evaluated or too recent
        if exp["outcome"] is not None:
            continue

        exp_date = datetime.fromisoformat(exp["date"])
        if exp_date > cutoff:
            continue  # Too recent, wait for outcome

        if exp["btc_price"] <= 0 or current_btc_price <= 0:
            continue

        # Calculate actual return over the lookback period
        btc_return_pct = ((current_btc_price - exp["btc_price"]) / exp["btc_price"]) * 100
        predicted = exp["predicted_regime"]

        # Score the prediction
        correct = False
        if predicted == "ACCUMULATION" and btc_return_pct > -5:
            correct = True  # Flat or rising = accumulation confirmed
        elif predicted == "MARKUP" and btc_return_pct > 5:
            correct = True  # Strong rise = markup confirmed
        elif predicted == "DISTRIBUTION" and -10 < btc_return_pct < 10:
            correct = True  # High vol, choppy = distribution confirmed
        elif predicted == "MARKDOWN" and btc_return_pct < -5:
            correct = True  # Falling = markdown confirmed

        exp["outcome"] = "CORRECT" if correct else "WRONG"
        exp["reward"] = 1.0 if correct else -1.0
        exp["outcome_date"] = datetime.now().isoformat()[:10]
        exp["btc_price_outcome"] = current_btc_price

        if correct:
            rl["total_correct"] += 1

        evaluated_count += 1
        rl["retrain_counter"] += 1

        print(f"[RL] Evaluated {exp['date']}: {predicted} → {exp['outcome']} "
              f"(BTC {btc_return_pct:+.1f}%)")

    if evaluated_count > 0:
        # Update rolling accuracy (weighted: recent experiences matter more)
        evaluated_exps = [e for e in rl["experiences"] if e["outcome"] is not None]
        if evaluated_exps:
            weights = []
            rewards = []
            for i, e in enumerate(evaluated_exps):
                weight = RL_DECAY_FACTOR ** (len(evaluated_exps) - 1 - i)
                weights.append(weight)
                rewards.append(1.0 if e["outcome"] == "CORRECT" else 0.0)
            rl["rolling_accuracy"] = round(
                sum(w * r for w, r in zip(weights, rewards)) / sum(weights), 4
            )

        # Update per-regime confidence adjustments
        for regime in REGIME_LABELS:
            regime_exps = [e for e in evaluated_exps if e["predicted_regime"] == regime]
            if len(regime_exps) >= RL_MIN_EXPERIENCES:
                recent_regime = regime_exps[-RL_MIN_EXPERIENCES:]
                correct_count = sum(1 for e in recent_regime if e["outcome"] == "CORRECT")
                regime_accuracy = correct_count / len(recent_regime)
                # Adjustment: 1.0 = perfect, <1.0 = less confidence, >1.0 not allowed
                rl["confidence_adjustments"][regime] = round(min(1.0, regime_accuracy / 0.8), 4)

        # Alert if accuracy dropping
        if rl["rolling_accuracy"] < RL_ACCURACY_ALERT and len(evaluated_exps) >= RL_MIN_EXPERIENCES:
            send_telegram(
                f"⚠️ *SYSTEM 13 RL ALERT — ACCURACY DECLINING*\n\n"
                f"Rolling accuracy: {rl['rolling_accuracy']:.0%}\n"
                f"Threshold: {RL_ACCURACY_ALERT:.0%}\n"
                f"Total predictions: {rl['total_predictions']}\n"
                f"Correct: {rl['total_correct']}\n\n"
                f"Per-regime adjustments:\n"
                + "\n".join(f"  {r}: {v:.0%}" for r, v in rl["confidence_adjustments"].items())
                + "\n\n🔄 Model may need retraining — regime shift detected?"
            )

        # Trigger retrain if enough new experiences
        if rl["retrain_counter"] >= RL_RETRAIN_TRIGGER:
            send_telegram(
                f"🧠 *SYSTEM 13 RL — RETRAIN RECOMMENDED*\n\n"
                f"{rl['retrain_counter']} new experiences since last train.\n"
                f"Rolling accuracy: {rl['rolling_accuracy']:.0%}\n"
                f"Run: `python3 regime_classifier.py --train --rl`"
            )

    _save_rl_state(rl)
    return rl


def rl_adjust_confidence(regime_result):
    """
    Apply RL confidence adjustments to a regime prediction.
    Returns adjusted confidence that reflects real-world accuracy.
    """
    rl = _load_rl_state()
    regime = regime_result["current_regime"]
    raw_confidence = regime_result["confidence"]
    adjustment = rl["confidence_adjustments"].get(regime, 1.0)
    adjusted = round(raw_confidence * adjustment, 4)

    regime_result["raw_confidence"] = raw_confidence
    regime_result["rl_adjustment"] = adjustment
    regime_result["confidence"] = adjusted
    regime_result["rl_rolling_accuracy"] = rl.get("rolling_accuracy", 1.0)
    regime_result["rl_total_predictions"] = rl.get("total_predictions", 0)
    regime_result["rl_model_generation"] = rl.get("model_generation", 1)

    return regime_result


def rl_retrain_with_experience(weekly_data, lookback=4):
    """
    Retrain the model incorporating RL experience data.
    Uses experience replay to adjust training weights:
    - Regimes that the model gets wrong more often get higher sample weights
    - This makes the model pay more attention to its weak spots
    """
    rl = _load_rl_state()
    evaluated = [e for e in rl["experiences"] if e["outcome"] is not None]

    if len(evaluated) < RL_MIN_EXPERIENCES:
        print(f"[RL] Not enough evaluated experiences ({len(evaluated)}/{RL_MIN_EXPERIENCES}). "
              "Skipping RL-enhanced retrain.")
        return train_model(weekly_data, lookback)

    print(f"\n[RL] Retraining with {len(evaluated)} experience-weighted samples...")

    # Calculate per-regime error rates
    regime_errors = {r: 0 for r in REGIME_LABELS}
    regime_totals = {r: 0 for r in REGIME_LABELS}
    for e in evaluated:
        r = e["predicted_regime"]
        regime_totals[r] += 1
        if e["outcome"] == "WRONG":
            regime_errors[r] += 1

    # Sample weights: higher weight for regimes the model struggles with
    regime_weights = {}
    for r in REGIME_LABELS:
        if regime_totals[r] > 0:
            error_rate = regime_errors[r] / regime_totals[r]
            # More errors → higher weight (1.0 to 2.0 range)
            regime_weights[r] = 1.0 + error_rate
        else:
            regime_weights[r] = 1.0

    print("[RL] Regime sample weights (from experience):")
    for r, w in regime_weights.items():
        err = regime_errors.get(r, 0)
        tot = regime_totals.get(r, 0)
        print(f"  {r}: weight={w:.2f} (errors={err}/{tot})")

    # Train with experience-adjusted weights
    from sklearn.ensemble import (
        GradientBoostingClassifier,
        RandomForestClassifier,
        VotingClassifier,
    )
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.model_selection import cross_val_score, StratifiedKFold
    from sklearn.preprocessing import StandardScaler

    dates = [d[0] for d in weekly_data]
    prices = np.array([d[1] for d in weekly_data], dtype=float)

    features, feature_names = compute_features(prices)
    seq_features = add_sequential_features(features, lookback=lookback)
    labels = label_dates(dates, prices)

    expanded_names = list(feature_names)
    for lag in range(1, lookback + 1):
        expanded_names += [f"{name}_lag{lag}" for name in feature_names]

    valid_mask = (labels >= 0) & (~np.any(np.isnan(seq_features), axis=1))
    X = seq_features[valid_mask]
    y = labels[valid_mask]

    if len(X) < 50:
        print("[RL] Not enough data. Falling back to standard training.")
        return train_model(weekly_data, lookback)

    # Apply experience-based sample weights
    sample_weights = np.ones(len(y))
    for i, label in enumerate(y):
        regime = REGIME_LABELS[label]
        sample_weights[i] = regime_weights.get(regime, 1.0)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    rf = RandomForestClassifier(
        n_estimators=300, max_depth=6, min_samples_leaf=5,
        class_weight="balanced", random_state=42,
    )
    gbm = GradientBoostingClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.08,
        subsample=0.8, min_samples_leaf=5, random_state=42,
    )

    ensemble = VotingClassifier(
        estimators=[("rf", rf), ("gbm", gbm)],
        voting="soft", weights=[1, 1],
    )

    # Fit with sample weights
    print("[RL] Training ensemble with experience-weighted samples...")
    cv_inner = StratifiedKFold(n_splits=3, shuffle=True, random_state=42)
    calibrated_model = CalibratedClassifierCV(
        ensemble, method="isotonic", cv=cv_inner
    )
    calibrated_model.fit(X_scaled, y, sample_weight=sample_weights)

    cv_outer = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    cv_scores = cross_val_score(calibrated_model, X_scaled, y, cv=cv_outer, scoring="accuracy")
    print(f"[RL] CV Accuracy (RL-enhanced): {cv_scores.mean():.3f} (+/- {cv_scores.std():.3f})")

    model_package = {
        "model": calibrated_model,
        "scaler": scaler,
        "feature_names": feature_names,
        "expanded_names": expanded_names,
        "lookback": lookback,
        "cv_accuracy": float(cv_scores.mean()),
        "cv_std": float(cv_scores.std()),
        "trained_at": datetime.now().isoformat(),
        "n_samples": len(X),
        "rl_enhanced": True,
        "rl_experiences_used": len(evaluated),
        "rl_regime_weights": regime_weights,
    }

    joblib.dump(model_package, MODEL_PATH)
    print(f"[RL] RL-enhanced model saved to {MODEL_PATH}")

    # Update RL state
    rl["retrain_counter"] = 0
    rl["last_retrain"] = datetime.now().isoformat()
    rl["model_generation"] += 1
    _save_rl_state(rl)

    send_telegram(
        f"🧠 *SYSTEM 13 RL — MODEL RETRAINED*\n\n"
        f"Generation: {rl['model_generation']}\n"
        f"CV Accuracy: {cv_scores.mean():.1%}\n"
        f"Experiences used: {len(evaluated)}\n"
        f"Regime weights: {regime_weights}"
    )

    return model_package


def _check_regime_change(result):
    """Check if regime changed and send Telegram alert."""
    if not STATE_PATH.exists():
        return

    try:
        with open(STATE_PATH) as f:
            old_state = json.load(f)
        old_regime = old_state.get("current_regime")
        new_regime = result["current_regime"]

        if old_regime and old_regime != new_regime:
            msg = (
                f"🔄 *REGIME CHANGE DETECTED*\n\n"
                f"*{old_regime}* → *{new_regime}*\n"
                f"Confidence: {result['confidence']:.0%}\n"
                f"BTC Price: ${result['btc_price']:,.0f}\n\n"
                f"Probabilities:\n"
            )
            for regime, prob in result["all_probabilities"].items():
                bar = "█" * int(prob * 20)
                msg += f"  {regime}: {prob:.0%} {bar}\n"

            if result.get("transition_alert"):
                msg += f"\nTransition: {result['transition_alert']}"

            print(f"\n[ALERT] Regime change: {old_regime} → {new_regime}")
            send_telegram(msg)
    except Exception as e:
        print(f"[WARN] Regime change check failed: {e}")


def print_status():
    """Print current regime status from saved state."""
    if not STATE_PATH.exists():
        print("[INFO] No regime state found. Run with --evaluate first.")
        return

    with open(STATE_PATH) as f:
        state = json.load(f)

    regime = state["current_regime"]
    conf = state["confidence"]
    price = state.get("btc_price", 0)
    updated = state.get("last_updated", "unknown")
    accuracy = state.get("model_accuracy", 0)

    # Regime emoji map
    emoji = {
        "ACCUMULATION": "🟢",
        "MARKUP": "🚀",
        "DISTRIBUTION": "🟡",
        "MARKDOWN": "🔴",
    }

    print(f"\n{'═' * 50}")
    print(f"  System 13 — Neural Regime Classifier")
    print(f"{'═' * 50}")
    print(f"  Regime:     {emoji.get(regime, '?')} {regime}")
    print(f"  Confidence: {conf:.1%}")
    print(f"  BTC Price:  ${price:,.0f}")
    print(f"  Model Acc:  {accuracy:.1%}")
    print(f"  Updated:    {updated[:19]}")
    print()

    print("  Probabilities:")
    for r, p in state.get("all_probabilities", {}).items():
        bar = "█" * int(p * 30)
        marker = " ◀" if r == regime else ""
        print(f"    {r:15s} {p:6.1%} {bar}{marker}")

    if state.get("transition_alert"):
        print(f"\n  ⚠️  Transition: {state['transition_alert']}")

    if state.get("regime_history"):
        print(f"\n  Recent History:")
        for entry in state["regime_history"][-6:]:
            print(f"    {entry['date']}: {entry['regime']} ({entry['confidence']:.0%})")

    print(f"{'═' * 50}\n")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="System 13 — Neural Regime Classifier for BTC cycle phases"
    )
    parser.add_argument("--train", action="store_true", help="Train the regime model")
    parser.add_argument("--evaluate", action="store_true", help="Evaluate current regime")
    parser.add_argument("--status", action="store_true", help="Print current regime status")
    parser.add_argument("--rl", action="store_true", help="Use RL-enhanced training (experience-weighted)")
    parser.add_argument("--rl-status", action="store_true", help="Print RL experience stats")
    parser.add_argument("--lookback", type=int, default=4, help="Lookback window for sequential features (default: 4)")
    args = parser.parse_args()

    if not any([args.train, args.evaluate, args.status, args.rl_status]):
        parser.print_help()
        return

    if args.rl_status:
        rl = _load_rl_state()
        evaluated = [e for e in rl["experiences"] if e["outcome"] is not None]
        pending = [e for e in rl["experiences"] if e["outcome"] is None]
        print(f"\n{'═' * 50}")
        print(f"  System 13 — Reinforcement Learning Status")
        print(f"{'═' * 50}")
        print(f"  Model Generation:    {rl.get('model_generation', 1)}")
        print(f"  Total Predictions:   {rl.get('total_predictions', 0)}")
        print(f"  Evaluated:           {len(evaluated)}")
        print(f"  Pending (< 4 weeks): {len(pending)}")
        print(f"  Correct:             {rl.get('total_correct', 0)}")
        print(f"  Rolling Accuracy:    {rl.get('rolling_accuracy', 0):.1%}")
        print(f"  Retrain Counter:     {rl.get('retrain_counter', 0)}/{RL_RETRAIN_TRIGGER}")
        print(f"  Last Retrain:        {rl.get('last_retrain', 'Never')}")
        print(f"\n  Confidence Adjustments:")
        for regime, adj in rl.get("confidence_adjustments", {}).items():
            print(f"    {regime:15s} {adj:.2f}x")
        if evaluated:
            print(f"\n  Last 5 Evaluated:")
            for e in evaluated[-5:]:
                print(f"    {e['date']}: {e['predicted_regime']:15s} → {e['outcome']} "
                      f"(BTC ${e.get('btc_price', 0):,.0f} → ${e.get('btc_price_outcome', 0):,.0f})")
        print(f"{'═' * 50}\n")
        return

    if args.status:
        print_status()
        return

    # Fetch data
    print("[DATA] Loading BTC weekly price data...")
    weekly_data = get_btc_weekly_prices()
    if not weekly_data:
        print("[ERROR] Could not load BTC price data.")
        sys.exit(1)
    print(f"[DATA] Loaded {len(weekly_data)} weeks ({weekly_data[0][0]} to {weekly_data[-1][0]})")

    if args.train:
        if args.rl:
            model_package = rl_retrain_with_experience(weekly_data, lookback=args.lookback)
        else:
            model_package = train_model(weekly_data, lookback=args.lookback)
        if model_package is None:
            sys.exit(1)
        # Also evaluate after training
        print("\n[EVAL] Running evaluation with newly trained model...")
        result = evaluate(weekly_data, model_package)
        if result:
            print_status()

    elif args.evaluate:
        result = evaluate(weekly_data)
        if result:
            print_status()
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()
