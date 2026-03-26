# Memory Index — Rudy v2.0 / Agent Zero

## User
- [user_profile.md](user_profile.md) — Commander profile, preferences, devices, capital situation

## Feedback (How to Work)
- [feedback_update_globally.md](feedback_update_globally.md) — "Update globally" means EVERY file, no exceptions
- [feedback_no_paper_trading.md](feedback_no_paper_trading.md) — Paper trading permanently disabled, remove all references
- [feedback_telegram_module.md](feedback_telegram_module.md) — Use shared telegram.py module, not os.environ.get
- [feedback_launchctl_not_nohup.md](feedback_launchctl_not_nohup.md) — All daemons via LaunchAgents, never nohup
- [feedback_restart_dashboard.md](feedback_restart_dashboard.md) — Always restart dashboard + tell user to hard refresh
- [feedback_avgo_research_only.md](feedback_avgo_research_only.md) — AVGO is research validation only, NOT for deployment
- [feedback_dont_change_v28plus.md](feedback_dont_change_v28plus.md) — Never modify v2.8+ entry/exit logic, only add around it
- [feedback_ibkr_price_source.md](feedback_ibkr_price_source.md) — ALL prices from IBKR only, no hardcoded/proxy/stale prices
- [feedback_mcp_ib_insync.md](feedback_mcp_ib_insync.md) — ib_insync in MCP must run in ThreadPoolExecutor + new event loop; install in .mcp_venv not system Python
- [feedback_no_clone_traders.md](feedback_no_clone_traders.md) — NEVER create trader scripts with buy/sell authority. Only Trader1 (trader_v28.py), Trader2 (trader2_mstr_put.py), Trader3 (trader3_spy_put.py) are authorized. All others LOCKED. Constitution Article XI.

## Project Context
- [project_rudy_v2_architecture.md](project_rudy_v2_architecture.md) — Full system architecture, daemons, safety, divisions, Claude Cloud integration. Includes: LEAP expiry extension protocol, quarterly OOS re-validation, Grok CT fixes, grok-intel-scan LaunchAgent, Trader1 panel, Authorized Trader Registry (Article XI), clone prohibition, live search grounding for all 3 brains (March 23, 2026)
- [project_system13_regime.md](project_system13_regime.md) — System 13 Neural Regime Classifier (CalibratedEnsemble, 95.6% CV, 4 regimes)
- [project_stress_tests.md](project_stress_tests.md) — All stress tests (March 2026) + candlestick backtest REJECTED + quarterly OOS re-validation system added March 22
- [project_capital_plan.md](project_capital_plan.md) — Three-phase capital deployment ($7.9K → $130K → $139.6K)
- [project_btc_cycle_phase.md](project_btc_cycle_phase.md) — BTC cycle intelligence, phase-aware seasonality, System 13 regime

- [project_position_audit_fix.md](project_position_audit_fix.md) — Position audit fixed for Trader2/3 recognition (2026-03-25)
- [project_equity_chart.md](project_equity_chart.md) — Daily equity curve chart to Telegram + dashboard /api/equity_chart (2026-03-25)
- [project_mar26_fixes.md](project_mar26_fixes.md) — Dashboard live values, Gemini prompt, premium bug, verify alerts, backtests (2026-03-26)

## Feedback
- [feedback_communication_style.md](feedback_communication_style.md) — When told "fix everything", do it all without per-item confirmation

## Reference
- [reference_key_files.md](reference_key_files.md) — All critical file paths (scripts, config, data, LaunchAgents)
