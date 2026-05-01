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
- [feedback_mcp_ib_insync.md](feedback_mcp_ib_insync.md) — ib_insync in MCP must run in ThreadPoolExecutor + new event loop
- [feedback_no_clone_traders.md](feedback_no_clone_traders.md) — Only Trader1/2/3 authorized. All others LOCKED. Article XI.
- [feedback_communication_style.md](feedback_communication_style.md) — When told "fix everything", do it all without per-item confirmation
- [feedback_hitl_entry_options_only.md](feedback_hitl_entry_options_only.md) — ALL entries need Commander YES/NO. No stock buys — LEAPs only.
- [feedback_voice_samantha.md](feedback_voice_samantha.md) — Claude is "E.M.", voice is macOS Samantha ("Sam")

## Project Context
- [project_rudy_v2_architecture.md](project_rudy_v2_architecture.md) — Full system architecture, HITL LEAP entry, Article XI, 3 traders, daemons, safety
- [project_rudy_overview.md](project_rudy_overview.md) — Rudy v2.0 system overview (3 traders, Constitution v50.3, IBKR live)
- [project_system13_regime.md](project_system13_regime.md) — System 13 Neural Regime Classifier (CalibratedEnsemble, 95.6% CV)
- [project_stress_tests.md](project_stress_tests.md) — Stress tests + quarterly OOS re-validation
- [project_capital_plan.md](project_capital_plan.md) — Three-phase capital deployment ($7.9K → $130K → $139.6K)
- [project_btc_cycle_phase.md](project_btc_cycle_phase.md) — BTC cycle intelligence, phase-aware seasonality
- [project_position_audit_fix.md](project_position_audit_fix.md) — Position audit Trader2/3 recognition (2026-03-25)
- [project_equity_chart.md](project_equity_chart.md) — Daily equity curve chart Telegram + dashboard (2026-03-25)
- [project_mar26_fixes.md](project_mar26_fixes.md) — Complete overhaul: real-time dash, HITL LEAP entry, Gemini/Grok, backtests (Mar 25-27)
- [project_backtest_results.md](project_backtest_results.md) — 6 backtest suites all REJECTED — v2.8+ baseline untouchable

## Project Context (continued)
- [project_btc_bottom_detector.md](project_btc_bottom_detector.md) — BTC 8-signal bottom detector: QC validated (100% WR), live scanner, WF+stress pipeline
- [project_treasury_yield.md](project_treasury_yield.md) — 10Y Treasury yield macro tracker, hourly daemon, BTC headwind/tailwind regime
- [project_cloud_sentinel.md](project_cloud_sentinel.md) — GitHub Actions BTC + 10Y monitor, 4h schedule, cloud backup for local sentinel

## Reference
- [reference_key_files.md](reference_key_files.md) — All critical file paths (scripts, config, data, LaunchAgents)
- [reference_firecrawl.md](reference_firecrawl.md) — Firecrawl web scraping: headlines into Grok/Gemini prompts
- [reference_opencli.md](reference_opencli.md) — opencli-rs at ~/bin/ — 55+ websites as CLI commands, intel scanner daemon
- [reference_video_editing.md](reference_video_editing.md) — Mac mini video workflow: meta_video_editor.py + video_config.yaml pipeline
- [reference_music_library.md](reference_music_library.md) — 49 mp3s in ~/Music used by the video editor workflow
