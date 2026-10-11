# Opt-in discovery smoke experiment

Code SHA: 9c4879438265a94f9301b2197340a350a518cad6
Decision date: 2026-10-09
Config: outputs/config.discovery.experiment.json (untracked copy of configs/config.risk_off.json + discovery_source_files only)
Mode: experiment
Command: python scripts/run_mvp_full_scan.py --config outputs/config.discovery.experiment.json
Validator: PASS, warnings: none
Cohort: 7 raw source rows (us_core 3 + thematic 2 + manual 2, incl. 1 disabled) → 5 unique symbols → 5 decisions, 0 exclusions
Decisions: JNJ A/PRIORITY_REVIEW, MSFT A/PRIORITY_REVIEW, COST A/HOLD_MONITOR, NVDA B/HOLD_MONITOR, XOM B/HOLD_MONITOR
Identity source: SEC_USER_AGENT
Input/output manually modified after run: no
