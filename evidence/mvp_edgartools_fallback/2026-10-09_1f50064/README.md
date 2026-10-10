MVP EdgarTools fallback experiment (PR #45 validation)

Code SHA: 1f500648b9a00382fdc5b32bbf09330d0fdf5211
Decision date: 2026-10-09
Config: configs/config.risk_off.json
Strategy style: risk_off
Mode: experiment
Command: python scripts/run_mvp_full_scan.py
Validator: PASS
Warnings:
- latest periodic filing is not covered by recognized Company Facts for 53 decision(s)
- non-USD core monetary facts are unsupported for 17 decision(s)
fundamental_fallback counts (verbatim from validation.json):
- edgartools_10q_used: 0
- status: not_needed=457, core_facts_incomplete=45, filing_mismatch=2, ineligible_form=6
Identity source: SEC_USER_AGENT
Input/output manually modified after run: no
