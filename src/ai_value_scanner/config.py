from __future__ import annotations

import json
import types
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints

import numpy as np


def default_ai_link_benchmark_etfs() -> list[str]:
    return [
        "AIQ",
        "BOTZ",
        "SMH",
        "SOXX",
        "XLK",
        "XLI",
        "XLU",
        "PAVE",
    ]


def default_watchlist_core_etfs() -> list[str]:
    return [
        "AIQ",
        "BOTZ",
        "ROBT",
        "WTAI",
        "SOXX",
        "SMH",
        "IRBO",
        "ARKQ",
        "IGV",
        "IGM",
        "FDN",
        "PNQI",
        "SOXQ",
        "XSD",
        "KOMP",
    ]


def default_watchlist_enabler_etfs() -> list[str]:
    return [
        "DTCR",
        "IFRA",
        "XLI",
        "XLU",
        "NLR",
        "URA",
        "SKYY",
        "CLOU",
        "SRVR",
        "GRID",
        "CIBR",
        "IHAK",
        "BUG",
        "PAVE",
        "IGF",
        "IXP",
    ]


def default_watchlist_peripheral_etfs() -> list[str]:
    return [
        "XLB",
        "VIS",
        "ITA",
        "IYT",
        "ITB",
        "PICK",
        "COPX",
        "VPU",
        "XLRE",
        "VNQ",
        "FXR",
        "IGE",
    ]


def default_channel_profiles() -> dict[str, dict[str, Any]]:
    return {
        "core_ai": {
            "min_watchlist_etf_count": 1,
            "min_ai_link_score": 0.30,
            "min_ps_discount": 0.15,
            "min_pe_discount": 0.10,
            "max_ps_percentile_in_sic": 0.45,
            "max_pe_percentile_in_sic": 0.45,
            "max_ev_to_ebit": 24.0,
            "min_fcf_yield": 0.02,
            "min_revenue_yoy": 0.00,
            "min_net_income_yoy": -0.05,
            "min_drawdown_from_52w_high": None,
            "max_range_position_52w": None,
            "max_price_to_sma200": None,
            "min_days_below_sma200": 7,
            "max_20d_return": 0.12,
            "max_60d_volatility": 0.70,
            "score_weights": {
                "ps_discount": 0.24,
                "pe_discount": 0.16,
                "ps_percentile_low": 0.10,
                "pe_percentile_low": 0.08,
                "ev_to_ebit_low": 0.08,
                "fcf_yield": 0.08,
                "revenue_yoy": 0.05,
                "net_income_yoy": 0.04,
                "liquidity": 0.05,
                "watchlist_etf_count": 0.15,
                "ai_link_score": 0.10,
                "range_position_52w_low": 0.10,
                "days_below_sma200": 0.05,
                "net_margin": 0.02,
            },
        },
        "ai_enabler": {
            "min_watchlist_etf_count": 1,
            "min_ai_link_score": 0.45,
            "min_ps_discount": 0.08,
            "min_pe_discount": 0.02,
            "max_ps_percentile_in_sic": 0.55,
            "max_pe_percentile_in_sic": 0.55,
            "max_ev_to_ebit": 30.0,
            "min_fcf_yield": 0.015,
            "min_revenue_yoy": -0.02,
            "min_net_income_yoy": -0.10,
            "min_drawdown_from_52w_high": None,
            "max_range_position_52w": None,
            "max_price_to_sma200": None,
            "min_days_below_sma200": 5,
            "max_20d_return": 0.18,
            "max_60d_volatility": 0.85,
            "score_weights": {
                "ps_discount": 0.18,
                "pe_discount": 0.12,
                "ps_percentile_low": 0.12,
                "pe_percentile_low": 0.10,
                "ev_to_ebit_low": 0.08,
                "fcf_yield": 0.08,
                "revenue_yoy": 0.05,
                "net_income_yoy": 0.04,
                "liquidity": 0.05,
                "watchlist_etf_count": 0.25,
                "ai_link_score": 0.12,
                "range_position_52w_low": 0.15,
                "days_below_sma200": 0.05,
                "net_margin": 0.03,
            },
        },
        "ai_peripheral": {
            "min_watchlist_etf_count": 1,
            "min_ai_link_score": 0.55,
            "min_ps_discount": 0.02,
            "min_pe_discount": -0.10,
            "max_ps_percentile_in_sic": 0.70,
            "max_pe_percentile_in_sic": 0.70,
            "max_ev_to_ebit": 36.0,
            "min_fcf_yield": 0.005,
            "min_revenue_yoy": -0.05,
            "min_net_income_yoy": -0.15,
            "min_drawdown_from_52w_high": 0.05,
            "max_range_position_52w": 0.90,
            "max_price_to_sma200": 1.20,
            "min_days_below_sma200": 3,
            "max_20d_return": 0.18,
            "max_60d_volatility": 0.95,
            "score_weights": {
                "ps_discount": 0.24,
                "pe_discount": 0.16,
                "ps_percentile_low": 0.10,
                "pe_percentile_low": 0.08,
                "ev_to_ebit_low": 0.08,
                "fcf_yield": 0.08,
                "revenue_yoy": 0.05,
                "net_income_yoy": 0.04,
                "liquidity": 0.07,
                "watchlist_etf_count": 0.08,
                "ai_link_score": 0.15,
                "range_position_52w_low": 0.08,
                "days_below_sma200": 0.04,
            },
            "trend_min_return_60d": -0.03,
            "trend_max_60d_volatility": 0.70,
            "trend_min_avg_dollar_volume_20d": 20000000.0,
            "momentum_min_return_20d": 0.06,
            "momentum_min_return_60d": 0.05,
            "momentum_min_price_to_sma200": 1.06,
            "momentum_max_drawdown_from_52w_high": 0.25,
            "momentum_max_60d_volatility": 0.75,
            "momentum_min_avg_dollar_volume_20d": 25000000.0,
            "momentum_min_watchlist_etf_count": 1,
        },
        "ai_smallcap": {
            "min_watchlist_etf_count": 0,
            "min_ai_link_score": 0.30,
            "min_ps_discount": 0.02,
            "min_pe_discount": -0.10,
            "max_ps_percentile_in_sic": 0.70,
            "max_pe_percentile_in_sic": 0.70,
            "max_ev_to_ebit": 36.0,
            "min_fcf_yield": 0.005,
            "min_revenue_yoy": -0.05,
            "min_net_income_yoy": -0.15,
            "min_drawdown_from_52w_high": 0.05,
            "max_range_position_52w": 0.90,
            "max_price_to_sma200": 1.20,
            "min_days_below_sma200": 3,
            "max_20d_return": 0.18,
            "max_60d_volatility": 0.95,
            "score_weights": {
                "ps_discount": 0.24,
                "pe_discount": 0.16,
                "ps_percentile_low": 0.10,
                "pe_percentile_low": 0.08,
                "ev_to_ebit_low": 0.08,
                "fcf_yield": 0.08,
                "revenue_yoy": 0.05,
                "net_income_yoy": 0.04,
                "liquidity": 0.15,
                "watchlist_etf_count": 0.0,
                "ai_link_score": 0.15,
                "range_position_52w_low": 0.08,
                "days_below_sma200": 0.04,
            },
            "trend_min_return_60d": -0.03,
            "trend_max_60d_volatility": 0.70,
            "trend_min_avg_dollar_volume_20d": 10000000.0,
            "momentum_min_return_20d": 0.06,
            "momentum_min_return_60d": 0.05,
            "momentum_min_price_to_sma200": 1.06,
            "momentum_max_drawdown_from_52w_high": 0.25,
            "momentum_max_60d_volatility": 0.75,
            "momentum_min_avg_dollar_volume_20d": 10000000.0,
            "momentum_min_watchlist_etf_count": 0,
        },
    }


def default_triage_rules() -> dict[str, dict[str, Any]]:
    return {
        "keep": {
            "core_ai": {
                "min_composite_score": 0.50,
                "min_ps_discount": 0.00,
                "min_pe_discount": 0.00,
            },
            "ai_enabler": {
                "min_composite_score": 0.45,
                "min_ps_discount": 0.00,
                "min_pe_discount": -0.10,
            },
            "ai_peripheral": {
                "min_composite_score": 0.50,
                "min_ps_discount": 0.05,
                "min_pe_discount": 0.00,
            },
            "ai_smallcap": {
                "min_composite_score": 0.45,
                "min_ps_discount": 0.00,
                "min_pe_discount": -0.10,
            },
        },
        "drop": {
            "max_composite_score": 0.35,
            "require_both_value_premium": True,
        },
    }


def default_low_coverage_soft_score_weights() -> dict[str, float]:
    return {
        "current_debt_ratio_low": 0.03,
        "inventory_growth_gap_low": 0.03,
    }


@dataclass
class ScanConfig:
    config_schema_version: int = 1
    # Explicit identity for production two-style configs. None is valid for
    # theme/venture/calibration configs that are not one of the two AI styles.
    strategy_style: str | None = None
    max_symbols: int | None = None
    max_workers: int = 8
    alpaca_max_requests_per_sec: float = 2.5
    sec_max_requests_per_sec: float = 5.0
    alpaca_cache_enabled: bool = True
    alpaca_cache_ttl_assets_sec: int = 21600
    alpaca_cache_ttl_snapshots_sec: int = 120
    alpaca_cache_ttl_bars_sec: int = 21600
    watchlist_csv_path: str = "data/ai_watchlist.csv"
    # Multi-theme engine: theme scans (configs/config.theme.*.json) read a
    # per-theme watchlist and MUST NOT archive it into
    # data/watchlist_history — those snapshots are the PIT record of the AI
    # watchlist for historical_replay, and a theme file there would be
    # resolved as "the AI watchlist as of <date>" by the next backtest
    # (pollution observed 2026-09-28 with the first nuclear scan).
    archive_watchlist_snapshots: bool = True
    watchlist_fetch_timeout_sec: int = 20
    ai_link_benchmark_etfs: list[str] = field(default_factory=default_ai_link_benchmark_etfs)
    ai_link_etf_count_saturation: int = 4
    ai_link_disclosure_keyword_cap: int = 6
    # Component weights of the theme/link composite (multi-theme engine,
    # docs/multi_theme_expansion.md Path 1, 2026-09-28): disclosure weight
    # is configurable per config because the SEC submissions JSON carries no
    # business description text — the production disclosure component has
    # been constant-zero since introduction. AI configs keep the historical
    # defaults (0.40/0.35/0.15/0.10, composite max 0.65); theme configs set
    # disclosure to 0 and scale etf-consensus saturation to the theme's
    # source-basket size so consensus measures "fraction of the theme's
    # ETFs holding the name". No renormalization anywhere: thresholds
    # (min_ai_link_score) are calibrated against the 0.65-max scale.
    ai_link_weight_etf_consensus: float = 0.40
    ai_link_weight_disclosure: float = 0.35
    ai_link_weight_market_link: float = 0.15
    ai_link_weight_backlog: float = 0.10
    ai_link_market_return_tolerance_20d: float = 0.25
    ai_link_market_return_tolerance_60d: float = 0.40
    ai_link_backlog_ratio_cap: float = 0.20
    watchlist_core_etfs: list[str] = field(default_factory=default_watchlist_core_etfs)
    watchlist_enabler_etfs: list[str] = field(default_factory=default_watchlist_enabler_etfs)
    watchlist_peripheral_etfs: list[str] = field(default_factory=default_watchlist_peripheral_etfs)
    chunk_size: int = 200
    request_timeout_sec: int = 20
    min_price: float = 1.0
    min_market_cap: float = 100_000_000.0
    max_market_cap: float | None = None
    min_dollar_volume: float = 1_000_000.0
    min_avg_dollar_volume_20d: float | None = None
    require_positive_revenue: bool = True
    require_positive_net_income: bool = True
    require_positive_operating_cash_flow: bool = True
    require_positive_free_cash_flow: bool = True
    require_positive_ebit: bool = True
    use_adjusted_quality_metrics: bool = True
    nonrecurring_addback_revenue_cap: float | None = 0.25
    use_ttm_metrics: bool = True
    min_fundamental_quality_score: float | None = 0.45
    min_revenue: float | None = 10_000_000.0
    min_net_income: float | None = 1_000_000.0
    min_operating_cash_flow: float | None = 0.0
    min_free_cash_flow: float | None = 0.0
    min_ebit: float | None = 0.0
    min_net_margin: float | None = None
    max_ps: float | None = None
    max_pe: float | None = None
    max_ev_to_ebit: float | None = 25.0
    min_fcf_yield: float | None = 0.02
    max_ps_percentile_in_sic: float | None = 0.60
    max_pe_percentile_in_sic: float | None = 0.60
    min_revenue_yoy: float | None = 0.00
    min_net_income_yoy: float | None = -0.10
    max_net_debt_to_ebitda: float | None = 5.0
    min_interest_coverage: float | None = 1.8
    max_current_debt_ratio: float | None = 0.75
    min_current_ratio: float | None = 0.90
    min_ocf_to_net_income: float | None = 0.60
    max_accrual_ratio: float | None = 0.35
    max_receivables_growth_gap: float | None = 0.60
    max_inventory_growth_gap: float | None = 1.00
    max_shares_yoy: float | None = 0.08
    own_history_valuation_window_days: int = 252
    max_ps_hist_percentile: float | None = 0.85
    max_pe_hist_percentile: float | None = 0.85
    min_expectation_proxy: float | None = -0.20
    min_cycle_proxy: float | None = None
    assumed_position_usd: float = 250_000.0
    max_adv_participation: float = 0.05
    max_estimated_slippage_bps: float | None = 40.0
    max_per_sector_per_list: int | None = 3
    max_per_watchlist_etf_source_per_list: int | None = None
    metric_hard_filter_coverage_mode: str = "balanced"
    force_hard_filter_low_coverage_metrics: bool = False
    low_coverage_soft_score_weights: dict[str, float] = field(
        default_factory=default_low_coverage_soft_score_weights
    )
    score_penalty_overvaluation: float = 0.20
    score_penalty_deterioration: float = 0.20
    min_ps_discount: float | None = 0.15
    min_pe_discount: float | None = 0.10
    # 0..1: how strongly NI-based PE cheap-credit is discounted by OCF/NI cash
    # backing (1.0 = trust cheap credit exactly in proportion to OCF/NI;
    # 0.0 = legacy behavior). Guards against non-operating gains (e.g.
    # unrealized investment marks) manufacturing spurious PE cheapness.
    pe_cash_backing_haircut: float = 1.0
    price_lookback_days: int = 420
    min_drawdown_from_52w_high: float | None = None
    max_range_position_52w: float | None = None
    min_range_position_52w: float | None = None
    max_price_to_sma200: float | None = None
    min_price_to_sma200: float | None = None
    min_days_below_sma200: int | None = 5
    min_return_20d: float | None = None
    min_return_60d: float | None = None
    max_20d_return: float | None = 0.18
    max_60d_volatility: float | None = 0.85
    min_drawdown_percentile: float | None = None
    min_avg_dollar_volume_20d_percentile: float | None = None
    max_60d_volatility_percentile: float | None = None
    score_winsor_lower_q: float = 0.05
    score_winsor_upper_q: float = 0.95
    benchmark_trend_filter_symbol: str | None = None
    benchmark_trend_filter_sma_days: int = 200
    # Default 24h: the scheduled SEC cache refresher (scripts/refresh_sec_cache.py,
    # cron 10:30 local = 22:30 ET, after the EDGAR 22:00 ET cutoff) updates all
    # caches daily; daily runs then use the fresh cache with zero downloads.
    # If the refresher is missed, the age exceeds the TTL and the run
    # self-heals by refetching inline (~2-3 min at 5 req/s).
    sec_cache_ttl_submissions_sec: int = 86400
    filter_mode: str = "scored"  # "hard" = legacy all-hard; "scored" = core + soft scoring
    soft_filter_weight: float = 0.30  # contribution of soft pass_rate to composite_score
    enabled_exchanges: list[str] = field(
        default_factory=lambda: ["NYSE", "NASDAQ", "AMEX", "ARCA", "BATS"]
    )
    require_channel_bucket_match: bool = True
    enforce_unique_symbol_per_list: bool = False
    enforce_unique_symbol_across_lists: bool = False
    exclude_sic_codes: list[str] = field(default_factory=lambda: ["6770"])
    channel_profiles: dict[str, dict[str, Any]] = field(default_factory=default_channel_profiles)
    triage_rules: dict[str, dict[str, Any]] = field(default_factory=default_triage_rules)
    low_value_allowed_research_priorities: list[str] = field(
        default_factory=lambda: ["research_now", "watch_for_pullback"]
    )
    low_value_excluded_research_risks: list[str] = field(
        default_factory=lambda: ["possible_value_trap", "weak_ai_link", "negative_momentum"]
    )
    low_value_min_research_score: float | None = 0.0
    top_n_per_channel_low_value: int = 10
    top_n_per_channel_trend: int = 10
    top_n_per_channel_momentum: int = 10
    research_pool_top_n: int = 50
    research_pool_min_score: float = 2.0
    cache_dir: str = "cache"
    output_dir: str = "outputs"

    @staticmethod
    def _matches_annotation(value: Any, annotation: Any) -> bool:
        if annotation is Any:
            return True
        origin = get_origin(annotation)
        if origin is types.UnionType:
            return any(ScanConfig._matches_annotation(value, arg) for arg in get_args(annotation))
        if origin is list:
            if not isinstance(value, list):
                return False
            args = get_args(annotation)
            item_type = args[0] if args else Any
            return all(ScanConfig._matches_annotation(item, item_type) for item in value)
        if origin is dict:
            if not isinstance(value, dict):
                return False
            args = get_args(annotation)
            key_type, value_type = args if len(args) == 2 else (Any, Any)
            return all(
                ScanConfig._matches_annotation(k, key_type)
                and ScanConfig._matches_annotation(v, value_type)
                for k, v in value.items()
            )
        if annotation is bool:
            return isinstance(value, bool)
        if annotation is int:
            return isinstance(value, int) and not isinstance(value, bool)
        if annotation is float:
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if annotation is str:
            return isinstance(value, str)
        if annotation is type(None):
            return value is None
        return isinstance(value, annotation)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ScanConfig":
        if not isinstance(raw, dict):
            raise ValueError("ScanConfig must be loaded from a JSON object")
        base = cls()
        known = {f.name for f in fields(cls)}
        hints = get_type_hints(cls)
        unknown = sorted(k for k in raw if k not in known and not str(k).startswith("_"))
        if unknown:
            raise ValueError(
                "Unknown ScanConfig keys (possible typo): " + ", ".join(repr(k) for k in unknown)
            )
        type_errors: list[str] = []
        for key, value in raw.items():
            # Metadata blocks (_theme_meta/_venture_meta) are documentation
            # provenance, not runtime configuration.
            if key not in known:
                continue
            annotation = hints.get(key, Any)
            if not cls._matches_annotation(value, annotation):
                type_errors.append(
                    f"{key}: expected {annotation!s}, got {type(value).__name__}"
                )
                continue
            setattr(base, key, value)
        if type_errors:
            raise ValueError("Invalid ScanConfig types:\n- " + "\n- ".join(type_errors))
        base.validate()
        return base

    def validate(self) -> None:
        """Fail fast on config type/range/cross-field errors.

        This intentionally validates semantics that would otherwise be
        silently coerced by downstream float()/bool() calls. It is not a
        separate configuration framework; ScanConfig remains the source of
        truth for runtime fields.
        """
        errors: list[str] = []

        def err(name: str, message: str) -> None:
            errors.append(f"{name}: {message}")

        def require_bool(name: str) -> None:
            if not isinstance(getattr(self, name), bool):
                err(name, "must be boolean")

        def require_int(name: str, *, minimum: int | None = None, allow_none: bool = False) -> None:
            value = getattr(self, name)
            if value is None and allow_none:
                return
            if isinstance(value, bool) or not isinstance(value, int):
                err(name, "must be an integer" + (" or null" if allow_none else ""))
                return
            if minimum is not None and value < minimum:
                err(name, f"must be >= {minimum}")

        def require_number(
            name: str,
            *,
            minimum: float | None = None,
            maximum: float | None = None,
            allow_none: bool = False,
        ) -> None:
            value = getattr(self, name)
            if value is None and allow_none:
                return
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                err(name, "must be numeric" + (" or null" if allow_none else ""))
                return
            val = float(value)
            if not np.isfinite(val):
                err(name, "must be finite")
                return
            if minimum is not None and val < minimum:
                err(name, f"must be >= {minimum}")
            if maximum is not None and val > maximum:
                err(name, f"must be <= {maximum}")

        require_int("config_schema_version", minimum=1)
        if self.config_schema_version != 1:
            err(
                "config_schema_version",
                f"unsupported version {self.config_schema_version!r}; expected 1",
            )
        if self.strategy_style not in (None, "risk_on", "risk_off"):
            err("strategy_style", "must be null, 'risk_on', or 'risk_off'")

        for name in (
            "alpaca_cache_enabled",
            "archive_watchlist_snapshots",
            "require_positive_revenue",
            "require_positive_net_income",
            "require_positive_operating_cash_flow",
            "require_positive_free_cash_flow",
            "require_positive_ebit",
            "use_adjusted_quality_metrics",
            "use_ttm_metrics",
            "force_hard_filter_low_coverage_metrics",
            "require_channel_bucket_match",
            "enforce_unique_symbol_per_list",
            "enforce_unique_symbol_across_lists",
        ):
            require_bool(name)

        for name in (
            "max_workers",
            "chunk_size",
            "request_timeout_sec",
            "watchlist_fetch_timeout_sec",
            "ai_link_etf_count_saturation",
            "ai_link_disclosure_keyword_cap",
            "own_history_valuation_window_days",
            "price_lookback_days",
            "benchmark_trend_filter_sma_days",
            "top_n_per_channel_low_value",
            "top_n_per_channel_trend",
            "top_n_per_channel_momentum",
            "research_pool_top_n",
        ):
            require_int(name, minimum=1)
        require_int("max_symbols", minimum=1, allow_none=True)
        require_int("min_days_below_sma200", minimum=0, allow_none=True)
        require_int("max_per_sector_per_list", minimum=1, allow_none=True)
        require_int("max_per_watchlist_etf_source_per_list", minimum=1, allow_none=True)
        for name in (
            "alpaca_cache_ttl_assets_sec",
            "alpaca_cache_ttl_snapshots_sec",
            "alpaca_cache_ttl_bars_sec",
            "sec_cache_ttl_submissions_sec",
        ):
            require_int(name, minimum=0)

        for name in ("alpaca_max_requests_per_sec", "sec_max_requests_per_sec"):
            require_number(name, minimum=0.000001)
        for name in (
            "min_price",
            "min_market_cap",
            "min_dollar_volume",
            "assumed_position_usd",
            "research_pool_min_score",
        ):
            require_number(name, minimum=0.0)
        for name in (
            "max_adv_participation",
            "pe_cash_backing_haircut",
            "soft_filter_weight",
            "ai_link_weight_etf_consensus",
            "ai_link_weight_disclosure",
            "ai_link_weight_market_link",
            "ai_link_weight_backlog",
            "score_winsor_lower_q",
            "score_winsor_upper_q",
        ):
            require_number(name, minimum=0.0, maximum=1.0)
        for name in (
            "max_ps_percentile_in_sic",
            "max_pe_percentile_in_sic",
            "max_ps_hist_percentile",
            "max_pe_hist_percentile",
            "min_drawdown_percentile",
            "min_avg_dollar_volume_20d_percentile",
            "max_60d_volatility_percentile",
            "min_fundamental_quality_score",
        ):
            require_number(name, minimum=0.0, maximum=1.0, allow_none=True)
        require_number(
            "nonrecurring_addback_revenue_cap",
            minimum=0.0,
            maximum=1.0,
            allow_none=True,
        )
        for name in (
            "min_avg_dollar_volume_20d",
            "min_operating_cash_flow",
            "min_free_cash_flow",
            "min_ebit",
            "min_net_margin",
            "max_ps",
            "max_pe",
            "max_ev_to_ebit",
            "min_fcf_yield",
            "min_revenue_yoy",
            "min_net_income_yoy",
            "max_net_debt_to_ebitda",
            "min_interest_coverage",
            "max_current_debt_ratio",
            "min_current_ratio",
            "min_ocf_to_net_income",
            "max_accrual_ratio",
            "max_receivables_growth_gap",
            "max_inventory_growth_gap",
            "max_shares_yoy",
            "min_expectation_proxy",
            "min_cycle_proxy",
            "max_estimated_slippage_bps",
            "min_drawdown_from_52w_high",
            "max_range_position_52w",
            "min_range_position_52w",
            "max_price_to_sma200",
            "min_price_to_sma200",
            "min_return_20d",
            "min_return_60d",
            "max_20d_return",
            "max_60d_volatility",
            "low_value_min_research_score",
        ):
            require_number(name, allow_none=True)
        for name in (
            "min_revenue",
            "min_net_income",
            "min_ps_discount",
            "min_pe_discount",
        ):
            require_number(name, allow_none=True)
        for name in (
            "ai_link_market_return_tolerance_20d",
            "ai_link_market_return_tolerance_60d",
            "ai_link_backlog_ratio_cap",
            "score_penalty_overvaluation",
            "score_penalty_deterioration",
        ):
            require_number(name)
        if self.ai_link_market_return_tolerance_20d <= 0:
            err("ai_link_market_return_tolerance_20d", "must be > 0")
        if self.ai_link_market_return_tolerance_60d <= 0:
            err("ai_link_market_return_tolerance_60d", "must be > 0")
        if self.ai_link_backlog_ratio_cap <= 0:
            err("ai_link_backlog_ratio_cap", "must be > 0")
        if (
            isinstance(self.score_winsor_lower_q, (int, float))
            and isinstance(self.score_winsor_upper_q, (int, float))
            and float(self.score_winsor_lower_q) >= float(self.score_winsor_upper_q)
        ):
            err("score_winsor_lower_q/score_winsor_upper_q", "must satisfy lower < upper")
        if self.max_market_cap is not None:
            require_number("max_market_cap", minimum=0.0, allow_none=True)
            if (
                isinstance(self.max_market_cap, (int, float))
                and isinstance(self.min_market_cap, (int, float))
                and float(self.max_market_cap) < float(self.min_market_cap)
            ):
                err("max_market_cap", "must be >= min_market_cap")
        if self.min_range_position_52w is not None and self.max_range_position_52w is not None:
            if float(self.min_range_position_52w) > float(self.max_range_position_52w):
                err("min_range_position_52w/max_range_position_52w", "must satisfy min <= max")
        if self.min_price_to_sma200 is not None and self.max_price_to_sma200 is not None:
            if float(self.min_price_to_sma200) > float(self.max_price_to_sma200):
                err("min_price_to_sma200/max_price_to_sma200", "must satisfy min <= max")

        if self.filter_mode not in {"hard", "scored"}:
            err("filter_mode", "must be 'hard' or 'scored'")
        if self.metric_hard_filter_coverage_mode not in {
            "high_coverage_only",
            "balanced",
            "all_metrics",
        }:
            err(
                "metric_hard_filter_coverage_mode",
                "must be high_coverage_only, balanced, or all_metrics",
            )

        for name in ("watchlist_csv_path", "cache_dir", "output_dir"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                err(name, "must be a non-empty string")
        if self.benchmark_trend_filter_symbol is not None and (
            not isinstance(self.benchmark_trend_filter_symbol, str)
            or not self.benchmark_trend_filter_symbol.strip()
        ):
            err("benchmark_trend_filter_symbol", "must be a non-empty string or null")
        for name in (
            "enabled_exchanges",
            "exclude_sic_codes",
            "ai_link_benchmark_etfs",
            "watchlist_core_etfs",
            "watchlist_enabler_etfs",
            "watchlist_peripheral_etfs",
            "low_value_allowed_research_priorities",
            "low_value_excluded_research_risks",
        ):
            value = getattr(self, name)
            if (
                not isinstance(value, list)
                or any(not isinstance(item, str) or not item.strip() for item in value)
            ):
                err(name, "must be a list of non-empty strings")

        if not isinstance(self.channel_profiles, dict) or not self.channel_profiles:
            err("channel_profiles", "must be a non-empty object")
        else:
            allowed_profile_keys = {
                "require_positive_revenue", "require_positive_net_income",
                "require_positive_operating_cash_flow", "require_positive_free_cash_flow",
                "require_positive_ebit", "require_channel_bucket_match",
                "min_watchlist_etf_count", "min_ai_link_score", "min_avg_dollar_volume_20d",
                "min_net_margin", "min_revenue", "min_net_income", "min_operating_cash_flow",
                "min_free_cash_flow", "min_ebit", "max_ev_to_ebit", "max_ps", "max_pe",
                "min_fcf_yield", "max_ps_percentile_in_sic", "max_pe_percentile_in_sic",
                "min_revenue_yoy", "min_net_income_yoy", "min_fundamental_quality_score",
                "max_net_debt_to_ebitda", "min_interest_coverage", "max_current_debt_ratio",
                "min_current_ratio", "min_ocf_to_net_income", "max_accrual_ratio",
                "max_receivables_growth_gap", "max_inventory_growth_gap", "max_shares_yoy",
                "max_ps_hist_percentile", "max_pe_hist_percentile", "min_expectation_proxy",
                "min_cycle_proxy", "max_adv_participation", "max_estimated_slippage_bps",
                "min_ps_discount", "min_pe_discount", "min_drawdown_from_52w_high",
                "max_range_position_52w", "min_range_position_52w", "max_price_to_sma200",
                "min_price_to_sma200", "min_days_below_sma200", "min_return_20d",
                "min_return_60d", "max_20d_return", "max_60d_volatility",
                "min_drawdown_percentile", "min_avg_dollar_volume_20d_percentile",
                "max_60d_volatility_percentile", "hard_filter_current_debt_ratio",
                "hard_filter_inventory_growth_gap", "score_weights",
                "trend_min_return_60d", "trend_max_60d_volatility",
                "trend_min_avg_dollar_volume_20d", "trend_min_watchlist_etf_count",
                "trend_score_weights", "momentum_min_return_20d",
                "momentum_min_return_60d", "momentum_min_price_to_sma200",
                "momentum_max_drawdown_from_52w_high", "momentum_max_60d_volatility",
                "momentum_min_avg_dollar_volume_20d", "momentum_min_watchlist_etf_count",
                "momentum_score_weights",
            }
            for channel, profile in self.channel_profiles.items():
                if not isinstance(channel, str) or not channel.strip():
                    err("channel_profiles", "channel names must be non-empty strings")
                    continue
                if not isinstance(profile, dict):
                    err(f"channel_profiles.{channel}", "must be an object")
                    continue
                extra = sorted(set(profile) - allowed_profile_keys)
                if extra:
                    err(
                        f"channel_profiles.{channel}",
                        "unknown keys: " + ", ".join(extra),
                    )
                bool_profile_keys = {
                    "require_positive_revenue",
                    "require_positive_net_income",
                    "require_positive_operating_cash_flow",
                    "require_positive_free_cash_flow",
                    "require_positive_ebit",
                    "require_channel_bucket_match",
                    "hard_filter_current_debt_ratio",
                    "hard_filter_inventory_growth_gap",
                }
                int_profile_keys = {
                    "min_watchlist_etf_count",
                    "min_days_below_sma200",
                    "trend_min_watchlist_etf_count",
                    "momentum_min_watchlist_etf_count",
                }
                dict_profile_keys = {
                    "score_weights",
                    "trend_score_weights",
                    "momentum_score_weights",
                }
                for key, value in profile.items():
                    if key in bool_profile_keys:
                        if not isinstance(value, bool):
                            err(f"channel_profiles.{channel}.{key}", "must be boolean")
                        continue
                    if key in int_profile_keys:
                        if (
                            value is not None
                            and (
                                isinstance(value, bool)
                                or not isinstance(value, int)
                                or value < 0
                            )
                        ):
                            err(
                                f"channel_profiles.{channel}.{key}",
                                "must be a non-negative integer or null",
                            )
                        continue
                    if key in dict_profile_keys:
                        continue
                    if value is not None and (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not np.isfinite(float(value))
                    ):
                        err(
                            f"channel_profiles.{channel}.{key}",
                            "must be a finite numeric value or null",
                        )

                min_range = profile.get("min_range_position_52w")
                max_range = profile.get("max_range_position_52w")
                if (
                    isinstance(min_range, (int, float))
                    and not isinstance(min_range, bool)
                    and isinstance(max_range, (int, float))
                    and not isinstance(max_range, bool)
                    and float(min_range) > float(max_range)
                ):
                    err(
                        f"channel_profiles.{channel}.min/max_range_position_52w",
                        "must satisfy min <= max",
                    )
                min_sma = profile.get("min_price_to_sma200")
                max_sma = profile.get("max_price_to_sma200")
                if (
                    isinstance(min_sma, (int, float))
                    and not isinstance(min_sma, bool)
                    and isinstance(max_sma, (int, float))
                    and not isinstance(max_sma, bool)
                    and float(min_sma) > float(max_sma)
                ):
                    err(
                        f"channel_profiles.{channel}.min/max_price_to_sma200",
                        "must satisfy min <= max",
                    )

                allowed_score_weight_keys = {
                    "accrual_ratio_low",
                    "adv_participation_low",
                    "ai_link_score",
                    "current_debt_ratio_low",
                    "cycle_proxy",
                    "days_below_sma200",
                    "drawdown_from_52w_high",
                    "ebit_yoy",
                    "estimated_slippage_bps_low",
                    "ev_to_ebit_low",
                    "expectation_proxy",
                    "fcf_yield",
                    "fundamental_quality_score",
                    "interest_coverage",
                    "inventory_growth_gap_low",
                    "liquidity",
                    "net_debt_to_ebitda_low",
                    "net_income_yoy",
                    "net_margin",
                    "ocf_to_net_income",
                    "operating_cash_flow_yoy",
                    "pe_discount",
                    "pe_hist_percentile_low",
                    "pe_percentile_low",
                    "ps_discount",
                    "ps_hist_percentile_low",
                    "ps_percentile_low",
                    "range_position_52w_low",
                    "return_20d",
                    "return_60d",
                    "revenue_yoy",
                    "shares_yoy_low",
                    "soft_pass_rate",
                    "watchlist_etf_count",
                }
                for weight_key in ("score_weights", "trend_score_weights", "momentum_score_weights"):
                    weights = profile.get(weight_key)
                    if weights is None:
                        continue
                    if not isinstance(weights, dict) or not weights:
                        err(f"channel_profiles.{channel}.{weight_key}", "must be a non-empty object")
                        continue
                    unknown_metrics = sorted(set(weights) - allowed_score_weight_keys)
                    if unknown_metrics:
                        err(
                            f"channel_profiles.{channel}.{weight_key}",
                            "unknown score dimensions: " + ", ".join(unknown_metrics),
                        )
                    for metric, weight in weights.items():
                        if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not np.isfinite(float(weight)):
                            err(
                                f"channel_profiles.{channel}.{weight_key}.{metric}",
                                "must be a finite numeric weight",
                            )

                for pct_key in (
                    "min_ai_link_score", "min_fundamental_quality_score",
                    "max_ps_percentile_in_sic", "max_pe_percentile_in_sic",
                    "max_ps_hist_percentile", "max_pe_hist_percentile",
                    "min_drawdown_percentile", "min_avg_dollar_volume_20d_percentile",
                    "max_60d_volatility_percentile", "min_range_position_52w",
                    "max_range_position_52w",
                ):
                    value = profile.get(pct_key)
                    if value is not None and (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not np.isfinite(float(value))
                        or float(value) < 0.0
                        or float(value) > 1.0
                    ):
                        err(f"channel_profiles.{channel}.{pct_key}", "must be within [0, 1] or null")

        if not isinstance(self.low_coverage_soft_score_weights, dict):
            err("low_coverage_soft_score_weights", "must be an object")
        else:
            allowed_soft = {"current_debt_ratio_low", "inventory_growth_gap_low"}
            extra_soft = sorted(set(self.low_coverage_soft_score_weights) - allowed_soft)
            if extra_soft:
                err(
                    "low_coverage_soft_score_weights",
                    "unknown score dimensions: " + ", ".join(extra_soft),
                )
            for metric, weight in self.low_coverage_soft_score_weights.items():
                if isinstance(weight, bool) or not isinstance(weight, (int, float)) or not np.isfinite(float(weight)) or float(weight) < 0:
                    err(f"low_coverage_soft_score_weights.{metric}", "must be a finite non-negative number")

        if not isinstance(self.triage_rules, dict):
            err("triage_rules", "must be an object")
        else:
            extra_triage = sorted(set(self.triage_rules) - {"keep", "drop"})
            if extra_triage:
                err("triage_rules", "unknown sections: " + ", ".join(extra_triage))
            keep_rules = self.triage_rules.get("keep", {})
            if not isinstance(keep_rules, dict):
                err("triage_rules.keep", "must be an object")
            else:
                for channel, rule in keep_rules.items():
                    if not isinstance(rule, dict):
                        err(f"triage_rules.keep.{channel}", "must be an object")
                        continue
                    extra = sorted(
                        set(rule)
                        - {"min_composite_score", "min_ps_discount", "min_pe_discount"}
                    )
                    if extra:
                        err(
                            f"triage_rules.keep.{channel}",
                            "unknown keys: " + ", ".join(extra),
                        )
                    for key, value in rule.items():
                        if (
                            isinstance(value, bool)
                            or not isinstance(value, (int, float))
                            or not np.isfinite(float(value))
                        ):
                            err(
                                f"triage_rules.keep.{channel}.{key}",
                                "must be a finite numeric value",
                            )
            drop_rules = self.triage_rules.get("drop", {})
            if not isinstance(drop_rules, dict):
                err("triage_rules.drop", "must be an object")
            else:
                extra = sorted(
                    set(drop_rules)
                    - {"max_composite_score", "require_both_value_premium"}
                )
                if extra:
                    err("triage_rules.drop", "unknown keys: " + ", ".join(extra))
                if "max_composite_score" in drop_rules:
                    value = drop_rules["max_composite_score"]
                    if (
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not np.isfinite(float(value))
                    ):
                        err(
                            "triage_rules.drop.max_composite_score",
                            "must be a finite numeric value",
                        )
                if "require_both_value_premium" in drop_rules and not isinstance(
                    drop_rules["require_both_value_premium"], bool
                ):
                    err(
                        "triage_rules.drop.require_both_value_premium",
                        "must be boolean",
                    )

        if errors:
            raise ValueError("Invalid ScanConfig:\n- " + "\n- ".join(errors))


def merge_soft_score_weights(
    base_weights: dict[str, float] | None, soft_weights: dict[str, float]
) -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(base_weights, dict):
        for k, v in base_weights.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    for k, v in soft_weights.items():
        if k not in out:
            out[k] = float(v)
    return out


def resolve_channel_profile(
    config: ScanConfig, channel_name: str, profile: dict[str, Any]
) -> dict[str, Any]:
    exclude_codes = sorted(set(str(x).strip() for x in config.exclude_sic_codes if str(x).strip()))
    score_weights = merge_soft_score_weights(
        profile.get("score_weights", {}),
        config.low_coverage_soft_score_weights,
    )

    return {
        "name": channel_name,
        "require_positive_revenue": bool(
            profile.get("require_positive_revenue", config.require_positive_revenue)
        ),
        "require_positive_net_income": bool(
            profile.get("require_positive_net_income", config.require_positive_net_income)
        ),
        "require_positive_operating_cash_flow": bool(
            profile.get(
                "require_positive_operating_cash_flow", config.require_positive_operating_cash_flow
            )
        ),
        "require_positive_free_cash_flow": bool(
            profile.get("require_positive_free_cash_flow", config.require_positive_free_cash_flow)
        ),
        "require_positive_ebit": bool(profile.get("require_positive_ebit", config.require_positive_ebit)),
        "require_channel_bucket_match": bool(
            profile.get("require_channel_bucket_match", config.require_channel_bucket_match)
        ),
        "min_watchlist_etf_count": int(profile.get("min_watchlist_etf_count", 1)),
        "min_ai_link_score": (
            None
            if profile.get("min_ai_link_score") is None
            else float(profile.get("min_ai_link_score"))
        ),
        "min_avg_dollar_volume_20d": (
            None
            if profile.get("min_avg_dollar_volume_20d", config.min_avg_dollar_volume_20d) is None
            else float(profile.get("min_avg_dollar_volume_20d", config.min_avg_dollar_volume_20d))
        ),
        "min_net_margin": (
            None
            if profile.get("min_net_margin", config.min_net_margin) is None
            else float(profile.get("min_net_margin", config.min_net_margin))
        ),
        "min_revenue": (
            None
            if profile.get("min_revenue", config.min_revenue) is None
            else float(profile.get("min_revenue", config.min_revenue))
        ),
        "min_net_income": (
            None
            if profile.get("min_net_income", config.min_net_income) is None
            else float(profile.get("min_net_income", config.min_net_income))
        ),
        "min_operating_cash_flow": (
            None
            if profile.get("min_operating_cash_flow", config.min_operating_cash_flow) is None
            else float(profile.get("min_operating_cash_flow", config.min_operating_cash_flow))
        ),
        "min_free_cash_flow": (
            None
            if profile.get("min_free_cash_flow", config.min_free_cash_flow) is None
            else float(profile.get("min_free_cash_flow", config.min_free_cash_flow))
        ),
        "min_ebit": (
            None
            if profile.get("min_ebit", config.min_ebit) is None
            else float(profile.get("min_ebit", config.min_ebit))
        ),
        "max_ev_to_ebit": (
            None
            if profile.get("max_ev_to_ebit", config.max_ev_to_ebit) is None
            else float(profile.get("max_ev_to_ebit", config.max_ev_to_ebit))
        ),
        "max_ps": (
            None
            if profile.get("max_ps", config.max_ps) is None
            else float(profile.get("max_ps", config.max_ps))
        ),
        "max_pe": (
            None
            if profile.get("max_pe", config.max_pe) is None
            else float(profile.get("max_pe", config.max_pe))
        ),
        "min_fcf_yield": (
            None
            if profile.get("min_fcf_yield", config.min_fcf_yield) is None
            else float(profile.get("min_fcf_yield", config.min_fcf_yield))
        ),
        "max_ps_percentile_in_sic": (
            None
            if profile.get("max_ps_percentile_in_sic", config.max_ps_percentile_in_sic) is None
            else float(profile.get("max_ps_percentile_in_sic", config.max_ps_percentile_in_sic))
        ),
        "max_pe_percentile_in_sic": (
            None
            if profile.get("max_pe_percentile_in_sic", config.max_pe_percentile_in_sic) is None
            else float(profile.get("max_pe_percentile_in_sic", config.max_pe_percentile_in_sic))
        ),
        "min_revenue_yoy": (
            None
            if profile.get("min_revenue_yoy", config.min_revenue_yoy) is None
            else float(profile.get("min_revenue_yoy", config.min_revenue_yoy))
        ),
        "min_net_income_yoy": (
            None
            if profile.get("min_net_income_yoy", config.min_net_income_yoy) is None
            else float(profile.get("min_net_income_yoy", config.min_net_income_yoy))
        ),
        "min_fundamental_quality_score": (
            None
            if profile.get("min_fundamental_quality_score", config.min_fundamental_quality_score) is None
            else float(profile.get("min_fundamental_quality_score", config.min_fundamental_quality_score))
        ),
        "max_net_debt_to_ebitda": (
            None
            if profile.get("max_net_debt_to_ebitda", config.max_net_debt_to_ebitda) is None
            else float(profile.get("max_net_debt_to_ebitda", config.max_net_debt_to_ebitda))
        ),
        "min_interest_coverage": (
            None
            if profile.get("min_interest_coverage", config.min_interest_coverage) is None
            else float(profile.get("min_interest_coverage", config.min_interest_coverage))
        ),
        "max_current_debt_ratio": (
            None
            if profile.get("max_current_debt_ratio", config.max_current_debt_ratio) is None
            else float(profile.get("max_current_debt_ratio", config.max_current_debt_ratio))
        ),
        "min_current_ratio": (
            None
            if profile.get("min_current_ratio", config.min_current_ratio) is None
            else float(profile.get("min_current_ratio", config.min_current_ratio))
        ),
        "min_ocf_to_net_income": (
            None
            if profile.get("min_ocf_to_net_income", config.min_ocf_to_net_income) is None
            else float(profile.get("min_ocf_to_net_income", config.min_ocf_to_net_income))
        ),
        "max_accrual_ratio": (
            None
            if profile.get("max_accrual_ratio", config.max_accrual_ratio) is None
            else float(profile.get("max_accrual_ratio", config.max_accrual_ratio))
        ),
        "max_receivables_growth_gap": (
            None
            if profile.get("max_receivables_growth_gap", config.max_receivables_growth_gap) is None
            else float(profile.get("max_receivables_growth_gap", config.max_receivables_growth_gap))
        ),
        "max_inventory_growth_gap": (
            None
            if profile.get("max_inventory_growth_gap", config.max_inventory_growth_gap) is None
            else float(profile.get("max_inventory_growth_gap", config.max_inventory_growth_gap))
        ),
        "max_shares_yoy": (
            None
            if profile.get("max_shares_yoy", config.max_shares_yoy) is None
            else float(profile.get("max_shares_yoy", config.max_shares_yoy))
        ),
        "max_ps_hist_percentile": (
            None
            if profile.get("max_ps_hist_percentile", config.max_ps_hist_percentile) is None
            else float(profile.get("max_ps_hist_percentile", config.max_ps_hist_percentile))
        ),
        "max_pe_hist_percentile": (
            None
            if profile.get("max_pe_hist_percentile", config.max_pe_hist_percentile) is None
            else float(profile.get("max_pe_hist_percentile", config.max_pe_hist_percentile))
        ),
        "min_expectation_proxy": (
            None
            if profile.get("min_expectation_proxy", config.min_expectation_proxy) is None
            else float(profile.get("min_expectation_proxy", config.min_expectation_proxy))
        ),
        "min_cycle_proxy": (
            None
            if profile.get("min_cycle_proxy", config.min_cycle_proxy) is None
            else float(profile.get("min_cycle_proxy", config.min_cycle_proxy))
        ),
        "max_adv_participation": (
            None
            if profile.get("max_adv_participation", config.max_adv_participation) is None
            else float(profile.get("max_adv_participation", config.max_adv_participation))
        ),
        "max_estimated_slippage_bps": (
            None
            if profile.get("max_estimated_slippage_bps", config.max_estimated_slippage_bps) is None
            else float(profile.get("max_estimated_slippage_bps", config.max_estimated_slippage_bps))
        ),
        "hard_filter_current_debt_ratio": bool(
            profile.get("hard_filter_current_debt_ratio", config.force_hard_filter_low_coverage_metrics)
        ),
        "hard_filter_inventory_growth_gap": bool(
            profile.get("hard_filter_inventory_growth_gap", config.force_hard_filter_low_coverage_metrics)
        ),
        "min_ps_discount": (
            None
            if profile.get("min_ps_discount", config.min_ps_discount) is None
            else float(profile.get("min_ps_discount", config.min_ps_discount))
        ),
        "min_pe_discount": (
            None
            if profile.get("min_pe_discount", config.min_pe_discount) is None
            else float(profile.get("min_pe_discount", config.min_pe_discount))
        ),
        "min_drawdown_from_52w_high": (
            None
            if profile.get("min_drawdown_from_52w_high", config.min_drawdown_from_52w_high) is None
            else float(profile.get("min_drawdown_from_52w_high", config.min_drawdown_from_52w_high))
        ),
        "max_range_position_52w": (
            None
            if profile.get("max_range_position_52w", config.max_range_position_52w) is None
            else float(profile.get("max_range_position_52w", config.max_range_position_52w))
        ),
        "min_range_position_52w": (
            None
            if profile.get("min_range_position_52w", config.min_range_position_52w) is None
            else float(profile.get("min_range_position_52w", config.min_range_position_52w))
        ),
        "max_price_to_sma200": (
            None
            if profile.get("max_price_to_sma200", config.max_price_to_sma200) is None
            else float(profile.get("max_price_to_sma200", config.max_price_to_sma200))
        ),
        "min_price_to_sma200": (
            None
            if profile.get("min_price_to_sma200", config.min_price_to_sma200) is None
            else float(profile.get("min_price_to_sma200", config.min_price_to_sma200))
        ),
        "min_days_below_sma200": (
            None
            if profile.get("min_days_below_sma200", config.min_days_below_sma200) is None
            else int(profile.get("min_days_below_sma200", config.min_days_below_sma200))
        ),
        "min_return_20d": (
            None
            if profile.get("min_return_20d", config.min_return_20d) is None
            else float(profile.get("min_return_20d", config.min_return_20d))
        ),
        "min_return_60d": (
            None
            if profile.get("min_return_60d", config.min_return_60d) is None
            else float(profile.get("min_return_60d", config.min_return_60d))
        ),
        "max_20d_return": (
            None
            if profile.get("max_20d_return", config.max_20d_return) is None
            else float(profile.get("max_20d_return", config.max_20d_return))
        ),
        "max_60d_volatility": (
            None
            if profile.get("max_60d_volatility", config.max_60d_volatility) is None
            else float(profile.get("max_60d_volatility", config.max_60d_volatility))
        ),
        "min_drawdown_percentile": (
            None
            if profile.get("min_drawdown_percentile", config.min_drawdown_percentile) is None
            else float(profile.get("min_drawdown_percentile", config.min_drawdown_percentile))
        ),
        "min_avg_dollar_volume_20d_percentile": (
            None
            if profile.get(
                "min_avg_dollar_volume_20d_percentile", config.min_avg_dollar_volume_20d_percentile
            )
            is None
            else float(
                profile.get(
                    "min_avg_dollar_volume_20d_percentile", config.min_avg_dollar_volume_20d_percentile
                )
            )
        ),
        "max_60d_volatility_percentile": (
            None
            if profile.get("max_60d_volatility_percentile", config.max_60d_volatility_percentile) is None
            else float(profile.get("max_60d_volatility_percentile", config.max_60d_volatility_percentile))
        ),
        "exclude_sic_codes": exclude_codes,
        "score_weights": score_weights,
    }


def load_config(path: str | None) -> ScanConfig:
    if not path:
        config = ScanConfig()
        config.validate()
        return config
    raw = json.loads(Path(path).read_text())
    config = ScanConfig.from_dict(raw)
    name = Path(path).name
    expected_style = {
        "config.risk_on.json": "risk_on",
        "config.risk_off.json": "risk_off",
    }.get(name)
    if expected_style is not None and config.strategy_style != expected_style:
        raise ValueError(
            f"{path}: strategy_style must be {expected_style!r}; "
            f"got {config.strategy_style!r}"
        )
    return config
