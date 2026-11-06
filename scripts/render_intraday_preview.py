"""Render a provisional intraday report with the daily Top-15 stability policy.

Reads the latest official production snapshot (or ``--snapshot-dir``), replaces
Entry Quality with a provisional estimate built from the current intraday price,
re-applies Action/Priority v2, then selects the daily and weekly lists through
the same canonical selectors used by production (including
``S2_confirm_1_2_safe``).

The output is explicitly provisional and read-only with respect to decision
snapshots: it never writes under ``outputs/decisions/`` and never updates
``latest_production.json``.

Example:
    python scripts/render_intraday_preview.py
    python scripts/render_intraday_preview.py --output-dir outputs/preview_intraday_1105
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from ai_value_scanner.config import load_config  # noqa: E402
from ai_value_scanner.decision.action import (  # noqa: E402
    assign_action_priorities_v2,
    map_action_state_v2,
)
from ai_value_scanner.decision.attention import (  # noqa: E402
    DAILY_ATTENTION_STABILITY_POLICY_VERSION,
)
from ai_value_scanner.decision.entry import build_entry_quality_v2  # noqa: E402
from ai_value_scanner.decision.integrated import (  # noqa: E402
    select_daily_attention,
    select_weekly_attention,
)
from ai_value_scanner.decision.model import (  # noqa: E402
    ActionState,
    EntryState,
    StockDecision,
    stock_decisions_from_jsonl,
)
from ai_value_scanner.reporting.decision import (  # noqa: E402
    render_action_list,
    render_detailed_report,
)
from ai_value_scanner.reporting.snapshot import (  # noqa: E402
    REPORT_RENDERER_REVISION,
    compute_in_list_streaks,
    load_previous_daily_symbols,
)
from ai_value_scanner.scanner import price_dimension_from_bars  # noqa: E402
from intraday_watch import (  # noqa: E402
    LOOKBACK_DAYS,
    _provisional_series,
    _qqq_context,
    build_alpaca_client,
    snapshot_market_source,
)

DEFAULT_CONFIG = str(REPO_ROOT / "configs" / "config.production.json")
DEFAULT_SNAPSHOT_ROOT = REPO_ROOT / "outputs" / "decisions"
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "outputs"
DETAILED_LINK_RE = re.compile(r"\./detailed_v2/([A-Za-z0-9][A-Za-z0-9.\-]*)\.md")


def display_path(path: Path) -> str:
    """Repository-relative path for manifests; never leak an absolute path."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return os.path.relpath(path.resolve(), REPO_ROOT)
PROVISIONAL_NOTE = (
    "> **PROVISIONAL INTRADAY PREVIEW** — generated {generated} UTC\n"
    "> from `{source}` (baseline: **{baseline}**) with current **IEX intraday** prices.\n"
    "> This is not an official decision snapshot and does not update "
    "`latest_production.json`.\n\n"
)


def resolve_latest_snapshot(snapshot_root: Path) -> Path:
    """Resolve the production snapshot referenced by the latest pointer."""
    pointer = snapshot_root / "latest_production.json"
    if not pointer.is_file():
        raise FileNotFoundError(f"missing latest production pointer: {pointer}")
    payload = json.loads(pointer.read_text(encoding="utf-8"))
    snapshot_dir = payload.get("snapshot_dir")
    if not snapshot_dir:
        raise ValueError(f"latest production pointer has no snapshot_dir: {pointer}")
    resolved = snapshot_root / str(snapshot_dir)
    if not resolved.is_dir():
        raise FileNotFoundError(f"latest production snapshot is missing: {resolved}")
    return resolved


def candidate_symbols(
    decisions: Sequence[StockDecision],
    incumbents: Iterable[str],
    *,
    top_n: int = 40,
) -> list[str]:
    """Symbols that can plausibly enter or leave the next daily list.

    Incumbents are always included (they need a provisional Entry to decide
    grace vs hard exit). New entrants come from canonical PRIORITY_REVIEW,
    every ENTRY_READY name, and the top ``top_n`` canonical priorities.
    """
    symbols = {str(symbol).strip().upper() for symbol in incumbents if str(symbol).strip()}
    symbols.update(
        decision.symbol
        for decision in decisions
        if decision.action_state is ActionState.PRIORITY_REVIEW
    )
    symbols.update(
        decision.symbol
        for decision in decisions
        if decision.entry.state is EntryState.ENTRY_READY
    )
    symbols.update(
        decision.symbol for decision in sorted(decisions, key=lambda d: d.priority)[:top_n]
    )
    return sorted(symbols)


def build_provisional_decisions(
    decisions: Sequence[StockDecision],
    symbols: Iterable[str],
    snapshots: Mapping[str, Mapping[str, Any] | None],
    bars: Mapping[str, Sequence[dict] | None],
    qqq_context: Mapping[str, Any] | None,
) -> tuple[dict[str, StockDecision], list[str]]:
    """Replace Entry with a current-price provisional estimate.

    Quality is carried over from the frozen snapshot. Failures are reported in
    ``skipped`` and the original decision is kept, so a single bad symbol never
    breaks the preview.
    """
    wanted = {str(symbol).strip().upper() for symbol in symbols}
    provisional: dict[str, StockDecision] = {}
    skipped: list[str] = []
    if qqq_context is None:
        return provisional, ["missing_qqq_context"]

    for decision in decisions:
        if decision.symbol not in wanted:
            continue
        price, series, snapshot_date = _provisional_series(
            bars.get(decision.symbol), snapshots.get(decision.symbol)
        )
        if price is None or not series or snapshot_date is None:
            skipped.append(decision.symbol)
            continue
        features = price_dimension_from_bars(price, series)
        stock_ret60 = features.get("return_60d")
        qqq_ret60 = qqq_context.get("return_60d")
        rs60 = (
            stock_ret60 - qqq_ret60
            if stock_ret60 is not None and qqq_ret60 is not None
            else None
        )
        metrics = {
            **features,
            "market_asof": snapshot_date.isoformat(),
            "qqq_trailing_return_60d": qqq_ret60,
            "relative_strength_60d_qqq": rs60,
            "regime": qqq_context.get("regime"),
            "benchmark_trend_ok": qqq_context.get("trend_ok"),
        }
        try:
            entry = build_entry_quality_v2(
                metrics,
                decision_date=snapshot_date,
                market_asof=snapshot_date,
                runtime_reference_date=snapshot_date,
            )
            action, _ = map_action_state_v2(decision.quality, entry)
        except Exception as exc:  # noqa: BLE001 - preview must never crash
            skipped.append(f"{decision.symbol}:{type(exc).__name__}")
            continue
        provisional[decision.symbol] = replace(
            decision, entry=entry, action_state=action
        )
    return provisional, skipped


def with_provisional_context(
    decisions: Sequence[StockDecision],
    provisional: Mapping[str, StockDecision],
    decision_date: str,
) -> list[StockDecision]:
    """Overlay provisional entries and stamp the provisional decision date.

    The source snapshot's canonical ``action_state`` is yesterday's official
    state for the preview session, so it becomes ``previous_action_state``
    (production derives the same field from the previous snapshot). Without
    this, S2 grace would be denied to names that entered the list on the
    source day, and stale state-change text would leak into the preview.
    """
    overlayed: list[StockDecision] = []
    for decision in decisions:
        current = provisional.get(decision.symbol)
        if current is None:
            overlayed.append(replace(decision, decision_date=decision_date))
            continue
        overlayed.append(
            replace(
                current,
                decision_date=decision_date,
                previous_action_state=decision.action_state,
                state_change_reason=None,
            )
        )
    return overlayed


def previous_daily_symbols(
    snapshot_root: Path,
    decision_date: str,
    strategy_style: str,
    fallback: Iterable[str],
) -> tuple[str, ...]:
    """Prior same-style list, falling back to the source snapshot's own list."""
    prior = load_previous_daily_symbols(
        snapshot_root, decision_date, strategy_style=strategy_style
    )
    if prior is None:
        return tuple(str(symbol) for symbol in fallback)
    return prior


def render_preview(
    *,
    snapshot_dir: Path,
    output_dir: Path,
    config_path: str = DEFAULT_CONFIG,
    snapshot_root: Path = DEFAULT_SNAPSHOT_ROOT,
    client: Any | None = None,
    cap: int = 15,
    top_candidates: int = 40,
) -> dict[str, Any]:
    """Build and write the provisional intraday report; return its metadata."""
    manifest = json.loads((snapshot_dir / "run_manifest.json").read_text(encoding="utf-8"))
    decisions = stock_decisions_from_jsonl(
        (snapshot_dir / "decisions.jsonl").read_text(encoding="utf-8")
    )
    baseline_source = snapshot_market_source(
        [{"provenance": dict(decision.provenance)} for decision in decisions]
    )
    incumbents = tuple(str(s) for s in (manifest.get("daily_symbols") or []))
    symbols = candidate_symbols(decisions, incumbents, top_n=top_candidates)

    config = load_config(config_path)
    if client is None:
        client = build_alpaca_client(config)
    fetch_symbols = symbols + ["QQQ"]
    snapshots = client.get_snapshots(fetch_symbols, config.chunk_size)
    start = (
        datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)
    ).isoformat()
    bars = client.get_daily_bars(fetch_symbols, start, config.chunk_size)

    qqq_context = _qqq_context(snapshots.get("QQQ"), bars.get("QQQ"), config)
    if qqq_context is None:
        raise RuntimeError("missing QQQ context; cannot build provisional entries")
    _, _, session_date = _provisional_series(bars.get("QQQ"), snapshots.get("QQQ"))
    decision_date = (
        session_date.isoformat()
        if session_date is not None
        else datetime.now(timezone.utc).date().isoformat()
    )

    provisional, skipped = build_provisional_decisions(
        decisions, symbols, snapshots, bars, qqq_context
    )
    if not provisional:
        raise RuntimeError(
            "no provisional entries were built; refusing to render a stale report"
        )
    ranked = assign_action_priorities_v2(
        with_provisional_context(decisions, provisional, decision_date)
    )
    prior = previous_daily_symbols(
        snapshot_root, decision_date, snapshot_dir.name, incumbents
    )
    daily = select_daily_attention(
        ranked, cap=cap, previous_daily_symbols=prior
    )
    weekly = select_weekly_attention(ranked, cap=cap)
    streaks = compute_in_list_streaks(
        snapshot_root,
        decision_date,
        snapshot_dir.name,
        [decision.symbol for decision in daily],
    )

    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    source = f"{snapshot_dir.parent.name}/{snapshot_dir.name}"
    output_dir.mkdir(parents=True, exist_ok=True)
    note = PROVISIONAL_NOTE.format(
        generated=generated, source=source, baseline=baseline_source
    )

    action_body = render_action_list(
        daily,
        title="Daily Action List — PROVISIONAL INTRADAY",
        cadence="daily",
        layout_version="v2",
        all_decisions=ranked,
        detailed_subdir="detailed_v2",
        streaks_by_symbol=streaks,
    )
    (output_dir / "action_list_v2.md").write_text(
        note + action_body, encoding="utf-8"
    )

    weekly_body = render_action_list(
        weekly,
        title="Weekly Review — PROVISIONAL INTRADAY",
        cadence="weekly",
        layout_version="v2",
        all_decisions=ranked,
        detailed_subdir="detailed_v2",
        streaks_by_symbol=streaks,
    )
    (output_dir / "weekly_review_v2.md").write_text(
        note + weekly_body, encoding="utf-8"
    )

    by_symbol = {decision.symbol: decision for decision in ranked}
    linked = set(DETAILED_LINK_RE.findall(action_body)) | set(
        DETAILED_LINK_RE.findall(weekly_body)
    )
    detailed_dir = output_dir / "detailed_v2"
    detailed_dir.mkdir(parents=True, exist_ok=True)
    for symbol in sorted(linked):
        decision = by_symbol.get(symbol)
        if decision is None:
            continue
        (detailed_dir / f"{symbol}.md").write_text(
            render_detailed_report(
                decision,
                layout_version="v2",
                back_link="../action_list_v2.md",
            ),
            encoding="utf-8",
        )

    metadata = {
        "preview_kind": "provisional_intraday",
        "source_snapshot": source,
        "output_dir": display_path(output_dir),
        "decision_date": decision_date,
        "generated_at_utc": generated,
        "provisional_market_data_feed": "iex",
        "baseline_market_data_source": baseline_source,
        "stability_policy_version": DAILY_ATTENTION_STABILITY_POLICY_VERSION,
        "report_renderer_revision": REPORT_RENDERER_REVISION,
        "candidate_count": len(symbols),
        "ranked_count": len(ranked),
        "daily_symbols": [decision.symbol for decision in daily],
        "weekly_symbols": [decision.symbol for decision in weekly],
        "previous_daily_symbols": list(prior),
        "skipped": skipped,
        "is_official": False,
    }
    (output_dir / "preview_manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return metadata


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render a provisional intraday report from the latest production "
            "snapshot, using current prices and the S2 Top-15 stability policy."
        )
    )
    parser.add_argument(
        "--snapshot-dir",
        default=None,
        help="Frozen snapshot directory; defaults to latest_production.json.",
    )
    parser.add_argument(
        "--snapshot-root",
        default=str(DEFAULT_SNAPSHOT_ROOT),
        help="Root containing dated production snapshots.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Preview output directory; defaults to outputs/preview_intraday_<date>.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--cap", type=int, default=15)
    parser.add_argument(
        "--top-candidates",
        type=int,
        default=40,
        help="Also fetch the top N canonical priorities as possible entrants.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv(REPO_ROOT / ".env")
    args = _parse_args(argv)
    snapshot_root = Path(args.snapshot_root)
    snapshot_dir = (
        Path(args.snapshot_dir)
        if args.snapshot_dir
        else resolve_latest_snapshot(snapshot_root)
    )
    default_output = args.output_dir is None
    pending_dir = DEFAULT_OUTPUT_ROOT / "preview_intraday_pending"
    if default_output and pending_dir.exists():
        shutil.rmtree(pending_dir)
    metadata = render_preview(
        snapshot_dir=snapshot_dir,
        output_dir=pending_dir if default_output else Path(args.output_dir),
        config_path=args.config,
        snapshot_root=snapshot_root,
        cap=args.cap,
        top_candidates=args.top_candidates,
    )
    # Rename the default pending directory once the session date is known.
    if default_output:
        final_dir = DEFAULT_OUTPUT_ROOT / f"preview_intraday_{metadata['decision_date']}"
        if pending_dir != final_dir and pending_dir.is_dir():
            if final_dir.exists():
                shutil.rmtree(final_dir)
            pending_dir.rename(final_dir)
        metadata["output_dir"] = display_path(final_dir)
        (final_dir / "preview_manifest.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(f"wrote {metadata['output_dir']}")
    print(
        f"source={metadata['source_snapshot']} date={metadata['decision_date']} "
        f"daily={len(metadata['daily_symbols'])} "
        f"policy={metadata['stability_policy_version']}"
    )
    print("daily:", ", ".join(metadata["daily_symbols"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
