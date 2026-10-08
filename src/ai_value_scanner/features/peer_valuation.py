from __future__ import annotations

import numpy as np
import pandas as pd

from .valuation import safe_divide


PEER_VALUATION_COLUMNS = (
    "peer_median_ps",
    "peer_median_pe",
    "ps_discount",
    "pe_discount",
    "ps_percentile_in_sic",
    "pe_percentile_in_sic",
)


def compute_peer_relative_valuation(
    frame: pd.DataFrame,
    *,
    min_peer_count: int = 5,
) -> dict[str, pd.Series]:
    """Compute canonical SIC-relative valuation features.

    Cohort eligibility is metric-specific: a row contributes to the P/S (or
    P/E) peer distribution only when the corresponding multiple is finite and
    positive, SIC is present, and the share count is not marked stale.

    Peer medians are computed from every eligible member of the SIC cohort.
    Percentile ranks require at least ``min_peer_count`` eligible members;
    smaller or ineligible cohorts receive the established neutral fallback
    of 0.5. Discounts remain missing when the row's own multiple or peer
    median is unavailable/invalid.
    """
    index = frame.index
    stale_mask = pd.Series(False, index=index, dtype=bool)
    if "shares_stale" in frame.columns:
        stale_mask = (
            pd.to_numeric(frame["shares_stale"], errors="coerce")
            .fillna(0)
            .astype(bool)
        )

    sic_present = frame["sic"].notna()
    ps = pd.to_numeric(frame["ps"], errors="coerce").astype(float)
    pe = pd.to_numeric(frame["pe"], errors="coerce").astype(float)

    ps_valid = np.isfinite(ps) & (ps > 0) & sic_present & ~stale_mask
    pe_valid = np.isfinite(pe) & (pe > 0) & sic_present & ~stale_mask

    peer_median_ps = pd.Series(np.nan, index=index, dtype=float)
    if bool(ps_valid.any()):
        ps_medians = frame.loc[ps_valid].assign(_ps=ps.loc[ps_valid]).groupby(
            "sic", dropna=True
        )["_ps"].median()
        peer_median_ps = frame["sic"].map(ps_medians).astype(float)

    peer_median_pe = pd.Series(np.nan, index=index, dtype=float)
    if bool(pe_valid.any()):
        pe_medians = frame.loc[pe_valid].assign(_pe=pe.loc[pe_valid]).groupby(
            "sic", dropna=True
        )["_pe"].median()
        peer_median_pe = frame["sic"].map(pe_medians).astype(float)

    ps_percentile = pd.Series(0.5, index=index, dtype=float)
    if bool(ps_valid.any()):
        ps_sizes = frame.loc[ps_valid].groupby("sic")["ps"].transform("size")
        ps_rank = frame.loc[ps_valid].assign(_ps=ps.loc[ps_valid]).groupby(
            "sic"
        )["_ps"].rank(method="average", pct=True)
        eligible = ps_sizes[ps_sizes >= max(1, int(min_peer_count))].index
        ps_percentile.loc[eligible] = ps_rank.loc[eligible]

    pe_percentile = pd.Series(0.5, index=index, dtype=float)
    if bool(pe_valid.any()):
        pe_sizes = frame.loc[pe_valid].groupby("sic")["pe"].transform("size")
        pe_rank = frame.loc[pe_valid].assign(_pe=pe.loc[pe_valid]).groupby(
            "sic"
        )["_pe"].rank(method="average", pct=True)
        eligible = pe_sizes[pe_sizes >= max(1, int(min_peer_count))].index
        pe_percentile.loc[eligible] = pe_rank.loc[eligible]

    return {
        "peer_median_ps": peer_median_ps,
        "peer_median_pe": peer_median_pe,
        "ps_discount": 1 - safe_divide(ps, peer_median_ps),
        "pe_discount": 1 - safe_divide(pe, peer_median_pe),
        "ps_percentile_in_sic": ps_percentile,
        "pe_percentile_in_sic": pe_percentile,
    }
