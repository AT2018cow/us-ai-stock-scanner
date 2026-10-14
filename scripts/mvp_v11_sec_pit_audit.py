"""Bounded, read-only EdgarTools audit for historical MVP v1.1 SEC evidence.

prepare selects HEI + predeclared frozen Top-15 controls without reading
outcomes. verify requires explicit network permission. Neither command changes
historical data, ranks, labels, production logic or candidate-return gates.
A filing header is NOT proof that historical scoring used that filing.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_value_scanner.fundamentals.edgartools_diagnostic import (
    configure_edgartools, resolve_git_sha,
)
from ai_value_scanner.research.mvp_v11 import inspect_frozen_dataset


EXPECTED_V3_SHA = "2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e"
EXPECTED_RANK_SHA = "4b0d25e0ad54c394a5eeed2ed47a2c4f0ba01fae29cc8d793f573980a2d88d51"
HEI_DATES = ("2023-12-29", "2024-12-31", "2025-08-29", "2025-12-31")
CONTROL_DATES = ("2023-01-31", "2024-01-31", "2024-12-31")
CONTROL_POSITIONS = (1, 8, 15)
MAX_CASES = 15
MAX_FILINGS_PER_ISSUER = 3
SEC_FORMS = ("10-K", "10-Q", "10-K/A", "10-Q/A")
ACC_PATTERN = re.compile(r"^\d{10}-\d{2}-\d{6}$")
SHARES_PATTERN = (
    "(?i)(?:EntityCommonStockSharesOutstanding|CommonStockSharesOutstanding"
    "|SharesOutstanding|CommonStockSharesIssued)"
)
SEC_EASTERN = ZoneInfo("America/New_York")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def require_sha(path: Path, expected: str) -> str:
    if not path.is_file():
        raise ValueError(f"missing frozen input: {path}")
    sha = sha256_file(path)
    if sha != expected.lower():
        raise ValueError(f"frozen input SHA256 mismatch: {path}: {sha}")
    return sha


def _read_rank(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"signal_date": str})
    if not {"signal_date", "v1_top15"}.issubset(frame.columns):
        raise ValueError("frozen rank reference missing signal_date or v1_top15")
    if frame.signal_date.duplicated().any():
        raise ValueError("duplicate rank reference signal dates")
    return frame.set_index("signal_date")


def build_cases(v3: pd.DataFrame, ranks: pd.DataFrame) -> pd.DataFrame:
    """Fixed 4 HEI dates + nine Top-1/8/15 controls, no forward outcomes."""
    required = {"signal_date", "symbol", "fundamental_data_asof"}
    if not required.issubset(v3.columns):
        raise ValueError(f"v3 missing columns: {sorted(required - set(v3.columns))}")
    data = v3.copy()
    data["symbol"] = data.symbol.astype("string").str.upper().str.strip()
    if data.duplicated(["signal_date", "symbol"]).any():
        raise ValueError("duplicate historical date×symbol")
    data = data.set_index(["signal_date", "symbol"], verify_integrity=True)
    selected: dict[tuple[str, str], dict[str, str]] = {}
    for day in HEI_DATES:
        selected[(day, "HEI")] = {"case_type": "HEI_CLASS_SCOPE", "rank_slot": ""}
    for day in CONTROL_DATES:
        if day not in ranks.index:
            raise ValueError(f"missing predeclared control date: {day}")
        symbols = [
            str(s).strip().upper()
            for s in str(ranks.at[day, "v1_top15"]).split(";")
        ]
        if len(symbols) < 15 or any(not s for s in symbols[:15]):
            raise ValueError(f"incomplete frozen Top-15 on {day}")
        for position in CONTROL_POSITIONS:
            selected.setdefault(
                (day, symbols[position - 1]),
                {"case_type": "FIXED_TOP15_CONTROL", "rank_slot": str(position)},
            )
    output = []
    for (day, symbol), info in sorted(
        selected.items(),
        key=lambda item: (
            item[1]["case_type"] != "HEI_CLASS_SCOPE",
            item[0][0], item[0][1],
        ),
    ):
        if (day, symbol) not in data.index:
            raise ValueError(f"case absent from v3: {day} {symbol}")
        row = data.loc[(day, symbol)]
        output.append({
            "signal_date": day,
            "symbol": symbol,
            "case_type": info["case_type"],
            "rank_slot": info["rank_slot"],
            "frozen_fundamental_data_asof": (
                "" if pd.isna(row["fundamental_data_asof"])
                else str(row["fundamental_data_asof"])
            ),
            "frozen_shares_asof_end": (
                "" if pd.isna(row.get("shares_asof_end"))
                else str(row.get("shares_asof_end"))
            ),
            "frozen_shares_outstanding": (
                "" if pd.isna(row.get("shares_outstanding"))
                else str(row.get("shares_outstanding"))
            ),
            "frozen_market_cap": (
                "" if pd.isna(row.get("market_cap"))
                else str(row.get("market_cap"))
            ),
            "historical_cik": "",
            "historical_accession": "",
        })
    if len(output) > MAX_CASES:
        raise ValueError("too many audit cases")
    return pd.DataFrame(output)


def header_accepted_utc(value: object) -> datetime | None:
    """SEC filing.header.acceptance_datetime is naive US Eastern, not UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        token = str(value).strip()
        if not token:
            return None
        try:
            parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SEC_EASTERN)
    return parsed.astimezone(timezone.utc)


def assess_filing_timing(header_time: datetime | None, signal_date: str) -> str:
    """Never certify same-day visibility without a frozen market calendar."""
    if header_time is None:
        return "UNVERIFIED_HEADER_TIME"
    filing_day = header_time.astimezone(SEC_EASTERN).date()
    signal_day = date.fromisoformat(str(signal_date)[:10])
    if filing_day < signal_day:
        return "FILING_PUBLIC_BEFORE_SIGNAL_DATE"
    if filing_day == signal_day:
        return "UNVERIFIED_SAME_DAY_MARKET_CLOSE"
    return "FILING_AFTER_SIGNAL_DATE"


def _source_url(cik: Any, accession: str) -> str | None:
    try:
        digits = str(int(str(cik)))
    except (TypeError, ValueError):
        return None
    if not ACC_PATTERN.fullmatch(accession):
        return None
    return (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{digits}/{accession.replace('-', '')}/"
    )


def _share_facts(filing: Any, *, max_rows: int = 12) -> tuple[list[dict[str, Any]], str]:
    """Sample exact-filing stock-share XBRL with any exposed dimension fields.

    Values remain descriptive, not normalized issuer market capitalization.
    Missing class-axis metadata must remain UNVERIFIED.
    """
    try:
        xbrl = filing.xbrl()
        if xbrl is None:
            return [], "XBRL_UNAVAILABLE"
        frame = xbrl.facts.query().by_concept(SHARES_PATTERN).to_dataframe()
    except Exception as exc:
        return [], f"XBRL_QUERY_ERROR:{type(exc).__name__}"
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return [], "SHARE_FACTS_NOT_FOUND"
    fields = (
        "concept", "label", "numeric_value", "value", "unit_ref", "currency",
        "period_end", "period_instant", "dimensions", "dimension",
        "dimension_axis", "dimension_member", "dimension_member_label",
    )
    columns = [c for c in fields if c in frame.columns]
    dimension_fields = {"dimensions", "dimension_axis", "dimension_member"} & set(columns)
    status = (
        "SHARE_FACT_DIMENSION_COLUMNS_PRESENT_NOT_CLASS_VERIFIED"
        if dimension_fields else "SHARE_FACTS_DIMENSIONS_UNVERIFIED"
    )
    rows = []
    for raw in frame.loc[:, columns].head(max_rows).to_dict("records"):
        record = {}
        for key, value in raw.items():
            if isinstance(value, (dict, list)):
                record[str(key)] = str(value)[:400]
            else:
                record[str(key)] = None if pd.isna(value) else str(value)
        rows.append(record)
    return rows, status


def inspect_case(
    case: dict[str, Any],
    *,
    find_filings: Callable[[str, str], list[Any]],
    inspect_shares: bool,
) -> dict[str, Any]:
    """Choose only a filing with SGML-header acceptance before signal date."""
    day = str(case["signal_date"])
    symbol = str(case["symbol"])
    result: dict[str, Any] = {
        "signal_date": day,
        "symbol": symbol,
        "case_type": case["case_type"],
        "case_verdict": "UNVERIFIED",
        "filing_timing": "UNVERIFIED_NO_FILING",
        "historical_cik_verified": False,
        "historical_scoring_accession_verified": False,
        "security_class_verified": False,
        "accession": None,
        "accepted_utc": None,
        "filing_date": None,
        "filing_cik": None,
        "form": None,
        "filing_url": None,
        "share_fact_status": "NOT_REQUESTED",
        "share_facts": [],
        "limitations": [
            "Current ticker lookup cannot prove historical issuer/CIK mapping.",
            "Observed filing cannot prove original v3 scoring used this accession.",
            "No class-by-class price, currency, or market cap certification.",
        ],
    }
    try:
        candidates = find_filings(symbol, day)[:MAX_FILINGS_PER_ISSUER]
    except Exception as exc:
        result["filing_timing"] = f"UNVERIFIED_LOOKUP_ERROR:{type(exc).__name__}"
        return result
    eligible = []
    unresolved = []
    for filing in candidates:
        accession = str(getattr(filing, "accession_no", "") or "")
        if not ACC_PATTERN.fullmatch(accession):
            continue
        try:
            header = getattr(filing, "header", None)
            accepted = (
                header_accepted_utc(getattr(header, "acceptance_datetime", None))
                if header is not None else None
            )
        except Exception:
            accepted = None
        timing = assess_filing_timing(accepted, day)
        if timing == "FILING_PUBLIC_BEFORE_SIGNAL_DATE":
            eligible.append((accepted, filing))
        else:
            unresolved.append(timing)
    if not eligible:
        if "UNVERIFIED_SAME_DAY_MARKET_CLOSE" in unresolved:
            result["filing_timing"] = "UNVERIFIED_SAME_DAY_MARKET_CLOSE"
        elif "UNVERIFIED_HEADER_TIME" in unresolved:
            result["filing_timing"] = "UNVERIFIED_HEADER_TIME"
        elif unresolved:
            result["filing_timing"] = "FILING_AFTER_SIGNAL_DATE"
        return result
    accepted, filing = max(eligible, key=lambda item: item[0])
    cik = getattr(filing, "cik", None)
    accession = str(filing.accession_no)
    result.update({
        "filing_timing": "FILING_PUBLIC_BEFORE_SIGNAL_DATE",
        "accession": accession,
        "accepted_utc": accepted.isoformat(),
        "filing_date": str(getattr(filing, "filing_date", "") or ""),
        "filing_cik": str(cik) if cik is not None else None,
        "form": str(getattr(filing, "form", "") or ""),
        "filing_url": _source_url(cik, accession),
    })
    # Do NOT claim historical CIK/accession provenance from ticker search.
    # Immutable source artifacts need a separate binding/CIK adjudication.
    if inspect_shares:
        result["share_facts"], result["share_fact_status"] = _share_facts(filing)
    if unresolved:
        result["limitations"].append(
            "Other nearby filings have unverified same-day/header timing."
        )
    return result


def make_case_lookup(company_factory: Callable[[str], Any]) -> Callable[[str, str], list[Any]]:
    cache: dict[str, Any] = {}

    def lookup(symbol: str, signal_date: str) -> list[Any]:
        if symbol not in cache:
            cache[symbol] = company_factory(symbol)
        collection = cache[symbol].get_filings(
            form=list(SEC_FORMS),
            filing_date=f"2021-01-01:{signal_date}",
        )
        return list(collection.head(MAX_FILINGS_PER_ISSUER))

    return lookup


def select_verify_cases(
    frozen_cases: pd.DataFrame,
    *,
    case_type: str,
    max_cases: int,
) -> pd.DataFrame:
    """Select pre-registered cases only; caller must SHA-verify the full file.

    HEI/controls selection cannot mutate, re-sort, regenerate or add tickers.
    Complete-case counts stop partial cherry-picking for focused audits.
    """
    if case_type not in {"all", "HEI_CLASS_SCOPE", "FIXED_TOP15_CONTROL"}:
        raise ValueError("invalid frozen audit case_type")
    if not 1 <= max_cases <= MAX_CASES:
        raise ValueError("max_cases outside fixed audit cap")
    required = {"signal_date", "symbol", "case_type",
                "historical_cik", "historical_accession"}
    if required - set(frozen_cases.columns):
        raise ValueError("incorrect frozen SEC audit case schema")
    if frozen_cases.duplicated(["signal_date", "symbol"]).any():
        raise ValueError("duplicate frozen SEC audit cases")
    if frozen_cases[["historical_cik", "historical_accession"]].ne("").any().any():
        raise ValueError("historical binding must use independent archival evidence")
    types = frozen_cases["case_type"].value_counts()
    if len(frozen_cases) != 13 or types.get("HEI_CLASS_SCOPE", 0) != 4 or types.get("FIXED_TOP15_CONTROL", 0) != 9:
        raise ValueError("frozen 4 HEI + 9 control case roster mismatch")
    expected_hei = [
        ("2023-12-29", "HEI"), ("2024-12-31", "HEI"),
        ("2025-08-29", "HEI"), ("2025-12-31", "HEI"),
    ]
    actual_hei = list(
        frozen_cases.loc[
            frozen_cases.case_type == "HEI_CLASS_SCOPE", ["signal_date", "symbol"]
        ].itertuples(index=False, name=None)
    )
    if actual_hei != expected_hei:
        raise ValueError("frozen HEI ordering/dates changed")
    if case_type == "all":
        # Retains backward compatibility for the original 4-HEI prefix run.
        return frozen_cases.head(max_cases).copy()
    selected = frozen_cases.loc[frozen_cases.case_type == case_type]
    if max_cases != len(selected):
        raise ValueError(
            f"{case_type} requires exactly {len(selected)} cases "
            f"(received max_cases={max_cases})"
        )
    return selected.copy()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="offline, zero SEC requests")
    prepare.add_argument("--entry-dataset", required=True)
    prepare.add_argument("--entry-meta", required=True)
    prepare.add_argument("--archived-ranking", required=True)
    prepare.add_argument("--output-dir", required=True)
    verify = sub.add_parser("verify", help="bounded SEC/EdgarTools lookup")
    verify.add_argument("--cases", required=True)
    verify.add_argument("--expected-cases-sha256", required=True)
    verify.add_argument("--allow-network", action="store_true")
    verify.add_argument("--inspect-xbrl", action="store_true")
    verify.add_argument("--max-cases", type=int, default=4)
    verify.add_argument("--case-type", default="all",
                        choices=["all", "HEI_CLASS_SCOPE", "FIXED_TOP15_CONTROL"],
                        help="Use only registered case rows from the SHA-pinned 13-case roster")
    verify.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    out = Path(args.output_dir)
    if out.exists():
        raise SystemExit(f"refusing to overwrite results: {out}")

    if args.command == "prepare":
        inv = inspect_frozen_dataset(
            args.entry_dataset, expected_kind="entry_quality",
            metadata=args.entry_meta,
        )
        if inv["dataset_sha256"] != EXPECTED_V3_SHA:
            raise ValueError("v3 differs from frozen PR-A study")
        ref = Path(args.archived_ranking)
        require_sha(ref, EXPECTED_RANK_SHA)
        columns = (
            "signal_date", "symbol", "fundamental_data_asof",
            "shares_asof_end", "shares_outstanding", "market_cap",
        )
        present = set(pd.read_csv(args.entry_dataset, nrows=0).columns)
        data = pd.read_csv(
            args.entry_dataset,
            usecols=[name for name in columns if name in present],
            dtype={"signal_date": str, "symbol": str},
        )
        cases = build_cases(data, _read_rank(ref))
        out.mkdir(parents=True)
        case_path = out / "sec_pit_cases.csv"
        cases.to_csv(case_path, index=False)
        report = {
            "status": "OFFLINE_CASES_FROZEN_NOT_PIT_VERIFIED",
            "ready_for_candidate_returns": False,
            "cases_sha256": sha256_file(case_path),
            "case_count": len(cases),
            "v3_sha256": inv["dataset_sha256"],
            "ranking_sha256": EXPECTED_RANK_SHA,
            "code_sha": resolve_git_sha(),
            "notes": [
                "Four HEI dates first, then fixed Top-1/8/15 from 3 old B0 dates",
                "No candidate outcomes/SEC requests",
                "Original historical CIK and accession are not present in v3",
            ],
        }
        (out / "case_manifest.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8",
        )
        print(f"{report['status']}: {len(cases)} cases, SHA256 {report['cases_sha256']}")
        return

    if not args.allow_network:
        raise SystemExit("verify requires --allow-network; zero SEC requests made")
    cases_path = Path(args.cases)
    require_sha(cases_path, args.expected_cases_sha256)
    cases = pd.read_csv(cases_path, dtype=str, keep_default_na=False)
    cases = select_verify_cases(
        cases, case_type=args.case_type, max_cases=args.max_cases
    )
    _, runtime = configure_edgartools()
    from edgar import Company

    lookup = make_case_lookup(Company)
    rows = [
        inspect_case(case, find_filings=lookup, inspect_shares=args.inspect_xbrl)
        for case in cases.to_dict(orient="records")
    ]
    out.mkdir(parents=True)
    row_path = out / "sec_pit_filing_review.jsonl"
    row_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows),
        encoding="utf-8",
    )
    summary = {
        "status": "SEC_FILING_EVIDENCE_ONLY_NOT_FULL_PIT_CERTIFICATION",
        "ready_for_candidate_returns": False,
        "cases_sha256": sha256_file(cases_path),
        "review_sha256": sha256_file(row_path),
        "case_count": len(rows),
        "case_type": args.case_type,
        "selected_cases": [f"{row['signal_date']}|{row['symbol']}" for row in cases.to_dict(orient="records")],
        "timing_summary": {
            status: sum(row["filing_timing"] == status for row in rows)
            for status in sorted({row["filing_timing"] for row in rows})
        },
        "n_cases_pit_fully_verified": 0,
        "code_sha": resolve_git_sha(),
        "edgartools_version": runtime.get("edgartools_version"),
        "edgar_identity_source": runtime.get("identity_source"),
        "inspect_xbrl": bool(args.inspect_xbrl),
        "network": True,
        "limits": [
            "Present-day ticker lookup does not establish historical CIK identity.",
            "Filing header availability does not prove that v3 used that accession.",
            "Same-day filings stay unverified without archived early-close calendar.",
            "Share facts alone cannot validate a two-class issuer market-cap denominator.",
        ],
    }
    (out / "sec_pit_audit_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"{summary['status']}: {len(rows)} cases; {out}")


if __name__ == "__main__":
    main()
