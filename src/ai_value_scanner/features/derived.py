from __future__ import annotations

import numpy as np
import pandas as pd

from .valuation import safe_divide


def compute_cross_section_derived_features(
    frame: pd.DataFrame,
    *,
    earnings_yoy_col: str,
    assumed_position_usd: float,
) -> dict[str, pd.Series]:
    """Pure vectorized expectation, cycle, capacity and slippage features.

    Scanner and historical replay supply the same column names but choose the
    earnings YoY input according to their own ScanConfig. This function never
    alters its input frame and retains the established missing-value policy:
    expectation inputs missing -> zero; cycle EBIT fallback -> missing if both
    EBIT series are missing; missing/zero ADV -> missing participation/slippage.
    Negative participation is clipped only for the slippage estimate.
    """
    expectation = (
        0.5 * pd.to_numeric(frame["revenue_yoy"], errors="coerce").fillna(0)
        + 0.5 * pd.to_numeric(frame[earnings_yoy_col], errors="coerce").fillna(0)
        - 0.5 * pd.to_numeric(frame["return_20d"], errors="coerce").fillna(0)
        - 0.5 * pd.to_numeric(frame["return_60d"], errors="coerce").fillna(0)
    )
    cycle = pd.to_numeric(
        frame["adjusted_ebit_yoy"], errors="coerce"
    ).fillna(pd.to_numeric(frame["ebit_yoy"], errors="coerce")) - pd.to_numeric(
        frame["revenue_yoy"], errors="coerce"
    )
    participation = safe_divide(
        pd.Series(float(assumed_position_usd), index=frame.index),
        frame["avg_dollar_volume_20d"],
    )
    slippage = 200.0 * np.sqrt(
        pd.to_numeric(participation, errors="coerce").clip(lower=0)
    )
    return {
        "expectation_proxy": expectation,
        "cycle_proxy": cycle,
        "adv_participation": participation,
        "estimated_slippage_bps": slippage,
    }
