"""Generate per-theme scan configs (Phase 2, docs/multi_theme_expansion.md).

For each theme in configs/theme_universe.json this produces
configs/config.theme.<name>.json:

- watchlist_csv_path  -> data/theme_watchlist_<theme>.csv (built by
  scripts/build_theme_universe.py)
- channel_profiles    -> single bucket keyed by the theme name; gates
  modeled on the AI system's loosest profile (ai_peripheral) with the
  theme's own min_theme_link threshold
- ai_link_benchmark_etfs -> the theme's benchmark basket (market-link
  component follows the theme, not the AI basket)
- ai_link component weights -> Path 1: disclosure weight 0 (SEC
  submissions carry no business description text; the component is
  constant-zero in production AI scans too). No renormalization — the
  composite max stays 0.65 so thresholds keep the same scale.
- ai_link_etf_count_saturation -> len(source ETFs): consensus measures
  "fraction of the theme's ETFs holding the name"
- QQQ SMA200 breaker kept as the master regime gate (design doc: QQQ
  remains the full-market layer; per-theme benchmarks join later)

Idempotent: rerun overwrites the generated configs.

Usage:
    .venv/bin/python scripts/generate_theme_configs.py
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--registry", default="configs/theme_universe.json")
    p.add_argument("--base-config", default="configs/config.risk_off.json")
    p.add_argument("--theme", default=None, help="Only this theme")
    return p


def main() -> None:
    args = build_parser().parse_args()
    registry = json.loads(Path(args.registry).read_text())["themes"]
    base = json.loads(Path(args.base_config).read_text())
    themes = {args.theme: registry[args.theme]} if args.theme else registry

    # Template: the AI system's loosest channel profile (ai_peripheral)
    profile_template = deepcopy((base.get("channel_profiles") or {}).get("ai_peripheral", {}))

    for theme, spec in themes.items():
        bucket = spec["bucket"]
        cfg = deepcopy(base)
        cfg["watchlist_csv_path"] = f"data/theme_watchlist_{theme}.csv"
        # Theme watchlists must never pollute the AI PIT snapshot series.
        cfg["archive_watchlist_snapshots"] = False
        cfg["ai_link_benchmark_etfs"] = list(spec["benchmark_etfs"])
        # Path 1: three-component theme link (disclosure weight 0).
        cfg["ai_link_weight_disclosure"] = 0.0
        # Theme-consensus scale: fraction of the theme's own ETFs.
        cfg["ai_link_etf_count_saturation"] = max(1, len(spec["source_etfs"]))
        # Research gates: drop weak_ai_link from the low_value exclusion —
        # within a theme the min_theme_link soft gate already handles link
        # quality, and the AI-calibrated weak threshold would exclude every
        # theme name (observed 2026-09-28: nuclear low_value = 0 because all
        # names carry weak_ai_link under AI-scale calibration).
        cfg["low_value_excluded_research_risks"] = ["possible_value_trap", "negative_momentum"]
        # Research priorities: the AI-calibrated assessment assigns theme
        # names theme_only (they cannot earn strong_ai_link tags by
        # construction). Within a theme universe, ETF membership IS the
        # theme confirmation, so theme_only may enter low_value — but only
        # above a research-score floor to keep the quality bar meaningful.
        # 3.0 ≈ the research_score of a borderline candidate (UUUU 3.2);
        # needs recalibration after the first scans of other themes.
        cfg["low_value_allowed_research_priorities"] = [
            "research_now", "watch_for_pullback", "theme_only",
        ]
        cfg["low_value_min_research_score"] = 3.0
        # Sector-concentration cap: single-sector themes (biotech ≈ all SIC
        # 2836, rare_earth ≈ all mining) were strangled by the AI-universe
        # default of 3 (observed 2026-09-28: biotech 53 gate survivors -> 2
        # listed). Final concentration stays with top_n_per_channel=10;
        # the sector cap must not cut below it.
        cfg["max_per_sector_per_list"] = 10
        # Research-pool floor: theme names systematically miss AI-tag bonuses
        # (ai_infrastructure_exposure +0.7, strong/medium_ai_link etc.),
        # measured 2026-09-28: biotech 2.2-2.5, rare_earth 2.0, minerals
        # -1.5~2.4 — all below the AI-calibrated 2.6. 1.0 admits the
        # theme-scale distribution; re-verify pool sizes after re-scan.
        cfg["research_pool_min_score"] = 1.0
        # Single-bucket channel profile.
        prof = deepcopy(profile_template)
        prof["min_ai_link_score"] = float(spec.get("min_theme_link_score", 0.3))
        prof["min_watchlist_etf_count"] = 1
        cfg["channel_profiles"] = {bucket: prof}
        # Scanning the theme as its own universe: keep QQQ master breaker
        # (benchmark_trend_filter_* inherited from base) and the scored
        # filter mode. Provenance header for the report.
        cfg["_theme_meta"] = {
            "theme": theme,
            "source_etfs": spec["source_etfs"],
            "benchmark_etfs": spec["benchmark_etfs"],
            "disclosure_keywords_pre_registered": spec["disclosure_keywords"],
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "path": "Path 1 — disclosure weight 0 (submissions text has no business description; see README §5.3)",
        }
        out = Path(f"configs/config.theme.{theme}.json")
        out.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")
        print(f"generated {out} (bucket={bucket}, saturation={cfg['ai_link_etf_count_saturation']}, "
              f"benchmarks={spec['benchmark_etfs']})")


if __name__ == "__main__":
    main()
