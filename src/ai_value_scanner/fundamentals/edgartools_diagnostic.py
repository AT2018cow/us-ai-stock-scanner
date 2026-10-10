from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Iterable

import pandas as pd


INTEGRITY_CODES = {
    "latest_periodic_filing_not_covered",
    "fundamental_currency_unsupported",
}

CORE_SPECS: dict[str, dict[str, tuple[str, ...]]] = {
    "revenue": {
        "standard": ("Revenue",),
        "raw_patterns": (
            r"Revenue",
            r"SalesRevenue",
        ),
    },
    "net_income": {
        "standard": ("NetIncome",),
        "raw_patterns": (
            r"NetIncome",
            r"ProfitLoss",
        ),
    },
    "operating_cash_flow": {
        "standard": (
            "OperatingCashFlow",
            "NetCashProvidedByUsedInOperatingActivities",
        ),
        "raw_patterns": (
            r"NetCashProvidedByUsedInOperatingActivities",
            r"CashFlowsFromUsedInOperatingActivities",
        ),
    },
}

STANDARD_TAXONOMIES = {"us-gaap", "ifrs-full", "dei"}


def _clean_token(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _taxonomy_from_concept(concept: str) -> str | None:
    token = str(concept or "").strip()
    if not token:
        return None
    if ":" in token:
        return token.split(":", 1)[0]
    if "_" in token:
        prefix = token.split("_", 1)[0]
        if prefix == "us-gaap":
            return "us-gaap"
        if prefix == "ifrs-full":
            return "ifrs-full"
        return prefix
    return None


def _statement_dataframe(statement: object | None) -> pd.DataFrame:
    if statement is None:
        return pd.DataFrame()
    converter = getattr(statement, "to_dataframe", None)
    if not callable(converter):
        return pd.DataFrame()
    try:
        frame = converter(include_unit=True)
    except TypeError:
        frame = converter()
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    return pd.DataFrame(frame)


def _facts_dataframe(xbrl: object) -> pd.DataFrame:
    facts = getattr(xbrl, "facts", None)
    converter = getattr(facts, "to_dataframe", None)
    if not callable(converter):
        return pd.DataFrame()
    frame = converter()
    if isinstance(frame, pd.DataFrame):
        return frame.copy()
    return pd.DataFrame(frame)


def _row_matches_spec(row: pd.Series, spec: dict[str, tuple[str, ...]]) -> bool:
    standard = _clean_token(row.get("standard_concept"))
    if standard and standard in spec["standard"]:
        return True
    haystack = " ".join(
        _clean_token(row.get(key))
        for key in ("concept", "label", "original_label")
    )
    return any(
        re.search(pattern, haystack, flags=re.IGNORECASE)
        for pattern in spec["raw_patterns"]
    )


def _summarize_statement(
    statement: object | None,
    *,
    targets: Iterable[str],
) -> dict[str, Any]:
    frame = _statement_dataframe(statement)
    result: dict[str, Any] = {
        "available": not frame.empty,
        "row_count": int(len(frame)),
        "period_columns": [],
        "matched": {},
    }
    if frame.empty:
        return result

    result["period_columns"] = [
        str(column)
        for column in frame.columns
        if re.match(r"^20\d{2}-\d{2}-\d{2}", str(column))
    ]

    for target in targets:
        spec = CORE_SPECS[target]
        matches: list[dict[str, Any]] = []
        for _, row in frame.iterrows():
            if not _row_matches_spec(row, spec):
                continue
            concept = _clean_token(row.get("concept"))
            taxonomy = _taxonomy_from_concept(concept)
            matches.append(
                {
                    "concept": concept or None,
                    "standard_concept": _clean_token(
                        row.get("standard_concept")
                    )
                    or None,
                    "label": _clean_token(row.get("label")) or None,
                    "unit": _clean_token(row.get("unit")) or None,
                    "taxonomy": taxonomy,
                }
            )
            if len(matches) >= 8:
                break
        result["matched"][target] = matches
    return result


def _detected_fact_units(frame: pd.DataFrame) -> list[str]:
    if frame.empty:
        return []
    for column in ("unit", "unit_ref"):
        if column not in frame.columns:
            continue
        units = sorted(
            {
                token
                for token in (_clean_token(value) for value in frame[column])
                if token
            }
        )
        if units:
            return units[:40]
    return []


def _detected_fact_taxonomies(frame: pd.DataFrame) -> list[str]:
    if frame.empty or "concept" not in frame.columns:
        return []
    taxonomies = {
        taxonomy
        for taxonomy in (
            _taxonomy_from_concept(_clean_token(value))
            for value in frame["concept"]
        )
        if taxonomy
    }
    return sorted(taxonomies)


def diagnose_accession(
    *,
    symbol: str,
    accession: str,
    get_filing: Callable[[str], object],
) -> dict[str, Any]:
    """Inspect one exact SEC filing through EdgarTools without changing decisions."""
    base: dict[str, Any] = {
        "symbol": symbol,
        "accession": accession,
        "edgartools_fetch_ok": False,
        "xbrl_available": False,
        "filing_form": None,
        "filing_date": None,
        "company": None,
        "fact_count": 0,
        "fact_units": [],
        "fact_taxonomies": [],
        "income_statement": {},
        "cash_flow_statement": {},
        "balance_sheet": {},
        "core_presence": {
            "revenue": False,
            "net_income": False,
            "operating_cash_flow": False,
        },
        "core_taxonomies": [],
        "custom_core_taxonomy_present": False,
        "error": None,
    }

    try:
        filing = get_filing(accession)
    except Exception as exc:  # pragma: no cover - exercised by injected fakes
        base["error"] = f"{type(exc).__name__}: {exc}"
        return base
    if filing is None:
        base["error"] = "filing_not_found"
        return base

    base["edgartools_fetch_ok"] = True
    base["filing_form"] = _clean_token(getattr(filing, "form", None)) or None
    base["filing_date"] = (
        _clean_token(getattr(filing, "filing_date", None)) or None
    )
    base["company"] = _clean_token(getattr(filing, "company", None)) or None

    try:
        xbrl = filing.xbrl()
    except Exception as exc:
        base["error"] = f"xbrl_error:{type(exc).__name__}: {exc}"
        return base
    if xbrl is None:
        base["error"] = "xbrl_unavailable"
        return base
    base["xbrl_available"] = True

    try:
        facts_frame = _facts_dataframe(xbrl)
    except Exception as exc:
        facts_frame = pd.DataFrame()
        base["error"] = f"facts_dataframe_error:{type(exc).__name__}: {exc}"
    base["fact_count"] = int(len(facts_frame))
    base["fact_units"] = _detected_fact_units(facts_frame)
    base["fact_taxonomies"] = _detected_fact_taxonomies(facts_frame)

    statements = getattr(xbrl, "statements", None)
    try:
        income = (
            statements.income_statement()
            if statements is not None
            else None
        )
    except Exception:
        income = None
    try:
        cash_flow = (
            statements.cash_flow_statement()
            if statements is not None
            else None
        )
    except Exception:
        cash_flow = None
    try:
        balance = (
            statements.balance_sheet()
            if statements is not None
            else None
        )
    except Exception:
        balance = None

    base["income_statement"] = _summarize_statement(
        income,
        targets=("revenue", "net_income"),
    )
    base["cash_flow_statement"] = _summarize_statement(
        cash_flow,
        targets=("operating_cash_flow",),
    )
    base["balance_sheet"] = _summarize_statement(balance, targets=())

    core_taxonomies: set[str] = set()
    for target, statement_key in (
        ("revenue", "income_statement"),
        ("net_income", "income_statement"),
        ("operating_cash_flow", "cash_flow_statement"),
    ):
        matches = base[statement_key].get("matched", {}).get(target, [])
        base["core_presence"][target] = bool(matches)
        for item in matches:
            taxonomy = item.get("taxonomy")
            if taxonomy:
                core_taxonomies.add(str(taxonomy))

    base["core_taxonomies"] = sorted(core_taxonomies)
    base["custom_core_taxonomy_present"] = any(
        taxonomy not in STANDARD_TAXONOMIES
        for taxonomy in core_taxonomies
    )
    return base


def decision_integrity_codes(decision: dict[str, Any]) -> list[str]:
    quality = decision.get("quality", {}) or {}
    items = list(quality.get("missing", []) or []) + list(
        quality.get("risks", []) or []
    )
    return sorted(
        {
            str(item.get("code"))
            for item in items
            if isinstance(item, dict) and item.get("code") in INTEGRITY_CODES
        }
    )


def load_snapshot_cases(
    snapshot_root: str | Path,
    *,
    symbols: Iterable[str] = (),
    all_flagged: bool = False,
) -> tuple[list[dict[str, Any]], Path]:
    root = Path(snapshot_root)
    decisions_path = root / "decisions.jsonl"
    if not decisions_path.is_file():
        raise FileNotFoundError(f"missing canonical decisions: {decisions_path}")

    requested = {str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()}
    cases: list[dict[str, Any]] = []
    seen_requested: set[str] = set()
    for line in decisions_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        decision = json.loads(line)
        symbol = str(decision.get("symbol") or "").strip().upper()
        codes = decision_integrity_codes(decision)
        selected = (all_flagged and bool(codes)) or symbol in requested
        if not selected:
            continue
        if symbol in requested:
            seen_requested.add(symbol)
        provenance = decision.get("provenance", {}) or {}
        accession = str(
            provenance.get("fundamental_latest_periodic_accession") or ""
        ).strip()
        cases.append(
            {
                "symbol": symbol,
                "company_name": decision.get("company_name"),
                "decision_date": decision.get("decision_date"),
                "quality_grade": (decision.get("quality", {}) or {}).get("grade"),
                "quality_confidence": (decision.get("quality", {}) or {}).get(
                    "confidence"
                ),
                "fundamental_data_asof": (decision.get("quality", {}) or {}).get(
                    "data_asof"
                ),
                "current_integrity_codes": codes,
                "current_latest_periodic_filing_date": provenance.get(
                    "fundamental_latest_periodic_filing_date"
                ),
                "current_latest_periodic_form": provenance.get(
                    "fundamental_latest_periodic_form"
                ),
                "current_latest_periodic_accession": accession or None,
                "current_reporting_currency": provenance.get(
                    "fundamental_reporting_currency"
                ),
                "current_currency_supported": provenance.get(
                    "fundamental_currency_supported"
                ),
                "current_facts_cover_latest_periodic": provenance.get(
                    "fundamental_facts_cover_latest_periodic"
                ),
            }
        )

    missing = sorted(requested - seen_requested)
    if missing:
        raise ValueError(
            "requested symbols not found in snapshot: " + ", ".join(missing)
        )
    if not cases:
        raise ValueError("no diagnostic cases selected")
    return cases, decisions_path


def classify_case(case: dict[str, Any], diagnostic: dict[str, Any]) -> str:
    codes = set(case.get("current_integrity_codes") or [])
    if not diagnostic.get("edgartools_fetch_ok"):
        return "EDGARTOOLS_FETCH_FAILED"
    if not diagnostic.get("xbrl_available"):
        return "EDGARTOOLS_XBRL_UNAVAILABLE"

    core_presence = diagnostic.get("core_presence", {}) or {}
    core_found = any(bool(value) for value in core_presence.values())
    usd_seen = any(
        str(unit).upper() == "USD"
        for unit in diagnostic.get("fact_units", []) or []
    )

    if "latest_periodic_filing_not_covered" in codes:
        if core_found:
            if diagnostic.get("custom_core_taxonomy_present"):
                return "CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND_CUSTOM"
            return "CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND"
        return "CURRENT_PATH_GAP_EDGARTOOLS_CORE_NOT_FOUND"

    if "fundamental_currency_unsupported" in codes:
        if usd_seen:
            return "CURRENT_PATH_NON_USD_EDGARTOOLS_USD_SEEN"
        return "CURRENT_PATH_NON_USD_EDGARTOOLS_NON_USD_ONLY"

    if core_found:
        return "CONTROL_EDGARTOOLS_CORE_FOUND"
    return "CONTROL_EDGARTOOLS_CORE_NOT_FOUND"


def summarize_results(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    materialized = list(rows)
    classifications = Counter(
        str(row.get("classification") or "UNKNOWN") for row in materialized
    )
    gap_rows = [
        row
        for row in materialized
        if "latest_periodic_filing_not_covered"
        in set(row.get("current_integrity_codes") or [])
    ]
    gap_core_found = sum(
        str(row.get("classification", "")).startswith(
            "CURRENT_PATH_GAP_EDGARTOOLS_CORE_FOUND"
        )
        for row in gap_rows
    )
    return {
        "cases": len(materialized),
        "classifications": dict(sorted(classifications.items())),
        "current_path_gap_cases": len(gap_rows),
        "current_path_gap_edgartools_core_found": int(gap_core_found),
        "current_path_gap_core_found_rate": (
            round(gap_core_found / len(gap_rows), 6) if gap_rows else None
        ),
        "custom_core_taxonomy_cases": sum(
            bool((row.get("edgartools") or {}).get("custom_core_taxonomy_present"))
            for row in materialized
        ),
        "edgartools_fetch_failures": sum(
            not bool((row.get("edgartools") or {}).get("edgartools_fetch_ok"))
            for row in materialized
        ),
        "edgartools_xbrl_unavailable": sum(
            bool((row.get("edgartools") or {}).get("edgartools_fetch_ok"))
            and not bool((row.get("edgartools") or {}).get("xbrl_available"))
            for row in materialized
        ),
    }


def render_summary_markdown(
    rows: Iterable[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    materialized = list(rows)
    lines = [
        "# EdgarTools SEC parity diagnostic",
        "",
        "This is a diagnostic-only artifact. It does not modify Company Quality, Entry Quality, or Action State.",
        "",
        "## Summary",
        "",
        f"- Cases: {summary['cases']}",
        f"- Current-path filing-gap cases: {summary['current_path_gap_cases']}",
        (
            "- Filing-gap cases where EdgarTools found at least one core "
            f"Revenue / NetIncome / OCF concept: {summary['current_path_gap_edgartools_core_found']}"
        ),
        (
            "- Filing-gap EdgarTools core-found rate: "
            f"{summary['current_path_gap_core_found_rate']}"
        ),
        f"- EdgarTools fetch failures: {summary['edgartools_fetch_failures']}",
        f"- EdgarTools XBRL unavailable: {summary['edgartools_xbrl_unavailable']}",
        "",
        "## Classification counts",
        "",
    ]
    for name, count in summary["classifications"].items():
        lines.append(f"- {name}: {count}")

    lines.extend(
        [
            "",
            "## Cases",
            "",
            "| Symbol | Current blockers | Filing | EdgarTools core | Taxonomies | Classification |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in materialized:
        edgar = row.get("edgartools", {}) or {}
        presence = edgar.get("core_presence", {}) or {}
        core = ",".join(
            key for key in ("revenue", "net_income", "operating_cash_flow")
            if presence.get(key)
        ) or "none"
        blockers = ",".join(row.get("current_integrity_codes") or []) or "none"
        filing = (
            f"{row.get('current_latest_periodic_form') or 'n/a'} "
            f"{row.get('current_latest_periodic_filing_date') or 'n/a'}"
        )
        taxonomies = ",".join(edgar.get("core_taxonomies", []) or []) or "n/a"
        lines.append(
            "| {symbol} | {blockers} | {filing} | {core} | {taxonomies} | {classification} |".format(
                symbol=row.get("symbol"),
                blockers=blockers,
                filing=filing,
                core=core,
                taxonomies=taxonomies,
                classification=row.get("classification"),
            )
        )
    lines.append("")
    return "\n".join(lines)


def resolve_git_sha() -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        token = completed.stdout.strip()
        return token or None
    except Exception:
        return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def configure_edgartools(identity: str | None = None) -> tuple[Callable[[str], object], dict[str, Any]]:
    """Load the optional EdgarTools dependency and configure SEC identity."""
    try:
        from edgar import get_by_accession_number, set_identity
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "EdgarTools is not installed. Run: pip install -e '.[sec-diagnostic]'"
        ) from exc

    resolved_identity = (
        identity
        or os.getenv("EDGAR_IDENTITY")
        or os.getenv("SEC_USER_AGENT")
        or ""
    ).strip()
    if not resolved_identity:
        raise RuntimeError(
            "Set EDGAR_IDENTITY='Name email@example.com' (preferred) or SEC_USER_AGENT before running the diagnostic."
        )
    set_identity(resolved_identity)
    try:
        version = importlib.metadata.version("edgartools")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"
    source = (
        "argument"
        if identity
        else "EDGAR_IDENTITY"
        if os.getenv("EDGAR_IDENTITY")
        else "SEC_USER_AGENT"
    )
    return get_by_accession_number, {
        "edgartools_version": version,
        "identity_source": source,
    }


def build_run_meta(
    *,
    snapshot_root: Path,
    decisions_path: Path,
    runtime_meta: dict[str, Any],
    case_count: int,
) -> dict[str, Any]:
    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_sha": resolve_git_sha(),
        "snapshot_root": str(snapshot_root),
        "decisions_sha256": sha256_file(decisions_path),
        "case_count": int(case_count),
        **runtime_meta,
    }
