MVP EdgarTools fallback-fix experiment (PR #49 validation)

Code SHA: 313c5ffedc9c1cf837b70d5e95d01d545d5c592f
Decision date: 2026-10-09
Config: configs/config.risk_off.json
Strategy style: risk_off
Mode: experiment
Command: python scripts/run_mvp_full_scan.py
Validator: PASS
Warnings:
- latest periodic filing is not covered by recognized Company Facts for 9 decision(s)
- non-USD core monetary facts are unsupported for 17 decision(s)
fundamental_fallback counts (verbatim from validation.json):
- edgartools_10q_used: 44
- status: used=44, not_needed=457, ineligible_form=6, filing_mismatch=2, ttm_not_fresh=1
Identity source: SEC_USER_AGENT
Input/output manually modified after run: no
