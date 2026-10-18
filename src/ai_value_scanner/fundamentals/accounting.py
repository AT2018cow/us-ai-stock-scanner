from __future__ import annotations

from typing import Any

import numpy as np


def safe_yoy(latest: float | None, previous: float | None) -> float | None:
    """Return latest/previous - 1, preserving the scanner's missing semantics."""
    if latest is None or previous is None:
        return None
    if previous == 0:
        return None
    try:
        return float(latest) / float(previous) - 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        return None


GROWTH_DIRECTION_POSITIVE_BASE = "positive_base"
GROWTH_DIRECTION_BOTH_NEGATIVE = "both_negative"
GROWTH_DIRECTION_TURNAROUND = "turnaround"
GROWTH_DIRECTION_REVERSAL = "reversal"
GROWTH_DIRECTION_INCOMPARABLE = "incomparable"


def growth_direction(
    latest: float | None,
    previous: float | None,
) -> tuple[str | None, float | None]:
    """Return (direction, normalized change) for a signed earnings series.

    The plain ratio ``latest/previous - 1`` is only economically meaningful
    when the prior-period base is positive. For series that are allowed to be
    negative (net income, EBIT, operating cash flow) the raw ratio inverts the
    sign of the change. This helper normalizes the change by the absolute
    prior base so that positive means "improved" for every sign combination,
    and tags the case so callers can score turnaround/reversal separately.

    Returns ``(None, None)`` when either input is missing, and
    ``("incomparable", None)`` when the prior base is exactly zero.
    """
    if latest is None or previous is None:
        return None, None
    try:
        latest_v = float(latest)
        previous_v = float(previous)
    except (TypeError, ValueError):
        return None, None
    if previous_v == 0:
        return GROWTH_DIRECTION_INCOMPARABLE, None
    change = (latest_v - previous_v) / abs(previous_v)
    if previous_v > 0.0:
        if latest_v >= 0.0:
            return GROWTH_DIRECTION_POSITIVE_BASE, change
        return GROWTH_DIRECTION_REVERSAL, change
    if latest_v >= 0.0:
        return GROWTH_DIRECTION_TURNAROUND, change
    return GROWTH_DIRECTION_BOTH_NEGATIVE, change


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def fundamental_quality_score_from_metrics(
    net_debt_to_ebitda: float | None,
    interest_coverage: float | None,
    current_ratio: float | None,
    ocf_to_net_income: float | None,
    accrual_ratio: float | None,
) -> float:
    """Current five-component quality score with neutral missing fallbacks."""
    nd_component = 0.5
    if net_debt_to_ebitda is not None:
        if net_debt_to_ebitda <= 0:
            nd_component = 1.0
        else:
            nd_component = clamp01(1.0 - (float(net_debt_to_ebitda) / 6.0))

    ic_component = 0.5
    if interest_coverage is not None:
        ic_component = clamp01(float(interest_coverage) / 8.0)

    cr_component = 0.5
    if current_ratio is not None:
        cr_component = clamp01(float(current_ratio) / 2.0)

    ocf_component = 0.5
    if ocf_to_net_income is not None:
        ocf_component = clamp01(float(ocf_to_net_income) / 1.2)

    accrual_component = 0.5
    if accrual_ratio is not None:
        accrual_component = clamp01(1.0 - abs(float(accrual_ratio)))

    return round(
        float(
            np.mean(
                [
                    nd_component,
                    ic_component,
                    cr_component,
                    ocf_component,
                    accrual_component,
                ]
            )
        ),
        6,
    )


def compute_adjusted_metrics(
    net_income: float | None,
    ebit: float | None,
    da: float | None,
    revenue: float | None,
    revenue_prev: float | None,
    addback: float | None,
    gain: float | None,
    addback_prev: float | None,
    gain_prev: float | None,
    cap_ratio: float | None,
    net_income_prev: float | None = None,
    ebit_prev: float | None = None,
) -> dict[str, float | None]:
    """Apply the existing replay non-recurring adjustment semantics.

    The revenue cap applies to addbacks. Callers that already prepared/capped
    adjustments (the live scanner currently caps both addbacks and gains)
    pass cap_ratio=None so this function performs only the common adjustment
    arithmetic. Keeping that caller distinction explicit preserves PR #8 as a
    behavior-neutral refactor.
    """
    if cap_ratio is not None:
        if addback is not None and revenue is not None and revenue > 0:
            addback = min(float(addback), float(revenue) * float(cap_ratio))
        if addback_prev is not None and revenue_prev is not None and revenue_prev > 0:
            addback_prev = min(
                float(addback_prev),
                float(revenue_prev) * float(cap_ratio),
            )

    def _adjust(
        value: float | None,
        adj_add: float | None,
        adj_gain: float | None,
    ) -> float | None:
        if value is None:
            return None
        return float(value) + float(adj_add or 0.0) - float(adj_gain or 0.0)

    adjusted_net_income = _adjust(net_income, addback, gain)
    adjusted_ebit = _adjust(ebit, addback, gain)
    adjusted_net_income_prev = _adjust(net_income_prev, addback_prev, gain_prev)
    adjusted_ebit_prev = _adjust(ebit_prev, addback_prev, gain_prev)
    adjusted_ebitda = (
        float(adjusted_ebit) + float(da or 0.0)
        if adjusted_ebit is not None
        else None
    )
    return {
        "adjusted_net_income": adjusted_net_income,
        "adjusted_ebit": adjusted_ebit,
        "adjusted_ebitda": adjusted_ebitda,
        "adjusted_net_income_prev": adjusted_net_income_prev,
        "adjusted_ebit_prev": adjusted_ebit_prev,
    }


def derive_accounting_metrics(
    *,
    revenue: float | None,
    revenue_prev: float | None,
    net_income: float | None,
    net_income_prev: float | None,
    operating_cash_flow: float | None,
    operating_cash_flow_prev: float | None,
    capex_raw: float | None,
    ebit: float | None,
    ebit_prev: float | None,
    shares: float | None,
    shares_prev: float | None,
    cash_and_equivalents: float | None,
    debt_long_term: float | None,
    debt_current: float | None,
    current_assets: float | None,
    current_liabilities: float | None,
    receivables_current: float | None,
    receivables_prev: float | None,
    inventory_current: float | None,
    inventory_prev: float | None,
    interest_expense: float | None,
    depreciation_and_amortization: float | None,
    depreciation_and_amortization_prev: float | None,
    adjusted_net_income: float | None,
    adjusted_net_income_prev: float | None,
    adjusted_ebit: float | None,
    adjusted_ebit_prev: float | None,
    adjusted_ebitda: float | None,
) -> dict[str, Any]:
    """Derive accounting ratios after fact/PIT selection has already happened.

    This function deliberately knows nothing about SEC filings, visibility,
    TTM reconstruction, caches, prices or strategy configuration.
    """
    capex = abs(capex_raw) if capex_raw is not None else None
    free_cash_flow = (
        float(operating_cash_flow) - float(capex)
        if operating_cash_flow is not None and capex is not None
        else None
    )

    # Debt completeness (R01): a missing debt field must never silently
    # become zero. ``reported`` requires both components; ``partial`` keeps
    # the known component but is flagged so quality cannot score it as a
    # clean balance sheet; ``missing`` leaves total_debt unknown.
    total_debt = None
    total_debt_source = "missing"
    if debt_long_term is not None and debt_current is not None:
        total_debt = float(debt_long_term) + float(debt_current)
        total_debt_source = "reported"
    elif debt_long_term is not None:
        total_debt = float(debt_long_term)
        total_debt_source = "partial"
    elif debt_current is not None:
        total_debt = float(debt_current)
        total_debt_source = "partial"

    # Net debt additionally requires cash. Missing cash is unknown, not zero.
    net_debt = None
    net_debt_source = "missing"
    if total_debt is not None and cash_and_equivalents is not None:
        net_debt = float(total_debt) - float(cash_and_equivalents)
        net_debt_source = (
            "partial" if total_debt_source == "partial" else "reported"
        )

    revenue_yoy = safe_yoy(revenue, revenue_prev)
    net_income_yoy = safe_yoy(net_income, net_income_prev)
    adjusted_net_income_yoy = safe_yoy(
        adjusted_net_income,
        adjusted_net_income_prev,
    )
    ebit_yoy = safe_yoy(ebit, ebit_prev)
    adjusted_ebit_yoy = safe_yoy(adjusted_ebit, adjusted_ebit_prev)
    operating_cash_flow_yoy = safe_yoy(
        operating_cash_flow,
        operating_cash_flow_prev,
    )
    shares_yoy = safe_yoy(shares, shares_prev)
    receivables_yoy = safe_yoy(receivables_current, receivables_prev)
    inventory_yoy = safe_yoy(inventory_current, inventory_prev)
    da_yoy = safe_yoy(
        depreciation_and_amortization,
        depreciation_and_amortization_prev,
    )

    # Sign-aware growth (R02): the raw YoY ratio is inverted whenever the
    # prior base is negative. These fields normalize the change by the
    # absolute prior base (positive = improved) and tag the case so the
    # quality layer never reads a widening loss as "strong growth".
    (
        net_income_growth_direction,
        net_income_growth,
    ) = growth_direction(net_income, net_income_prev)
    (
        adjusted_net_income_growth_direction,
        adjusted_net_income_growth,
    ) = growth_direction(adjusted_net_income, adjusted_net_income_prev)
    (
        ebit_growth_direction,
        ebit_growth,
    ) = growth_direction(ebit, ebit_prev)
    (
        adjusted_ebit_growth_direction,
        adjusted_ebit_growth,
    ) = growth_direction(adjusted_ebit, adjusted_ebit_prev)
    (
        operating_cash_flow_growth_direction,
        operating_cash_flow_growth,
    ) = growth_direction(operating_cash_flow, operating_cash_flow_prev)

    interest_expense_abs = (
        abs(float(interest_expense)) if interest_expense is not None else None
    )
    interest_coverage = None
    if (
        adjusted_ebit is not None
        and interest_expense_abs is not None
        and interest_expense_abs > 0
    ):
        interest_coverage = float(adjusted_ebit) / interest_expense_abs

    net_debt_to_ebitda = None
    net_debt_to_ebitda_source = "missing"
    if (
        net_debt is not None
        and adjusted_ebitda is not None
        and adjusted_ebitda != 0
    ):
        net_debt_to_ebitda = float(net_debt) / float(adjusted_ebitda)
        net_debt_to_ebitda_source = net_debt_source

    current_ratio = None
    if current_assets is not None and current_liabilities not in (None, 0):
        current_ratio = float(current_assets) / float(current_liabilities)

    current_debt_ratio_reported = None
    current_debt_ratio_inferred = None
    current_debt_ratio = None
    current_debt_ratio_source = "missing"
    if debt_current is not None and current_assets not in (None, 0):
        current_debt_ratio_reported = float(debt_current) / float(current_assets)
        current_debt_ratio = current_debt_ratio_reported
        current_debt_ratio_source = "reported"
    elif current_assets not in (None, 0):
        if total_debt is not None and total_debt <= 0:
            current_debt_ratio_inferred = 0.0
            current_debt_ratio = current_debt_ratio_inferred
            current_debt_ratio_source = "inferred_zero_nonpositive_total_debt"
        elif total_debt is not None and current_liabilities not in (None, 0):
            inferred_current_debt = min(
                max(float(total_debt), 0.0),
                float(current_liabilities),
            )
            current_debt_ratio_inferred = (
                inferred_current_debt / float(current_assets)
            )
            current_debt_ratio = current_debt_ratio_inferred
            current_debt_ratio_source = (
                "inferred_total_debt_capped_by_current_liabilities"
            )

    ocf_to_net_income = None
    if operating_cash_flow is not None and adjusted_net_income not in (None, 0):
        ocf_to_net_income = (
            float(operating_cash_flow) / float(adjusted_net_income)
        )

    accrual_ratio = None
    if (
        adjusted_net_income is not None
        and operating_cash_flow is not None
        and current_assets not in (None, 0)
    ):
        accrual_ratio = (
            float(adjusted_net_income) - float(operating_cash_flow)
        ) / float(current_assets)

    receivables_growth_gap = None
    if receivables_yoy is not None and revenue_yoy is not None:
        receivables_growth_gap = float(receivables_yoy) - float(revenue_yoy)

    # Inventory (R01): only reported inventory data can produce evidence.
    # Two explicit zeros mean "reported zero inventory, unchanged" (a real
    # observation); two missing fields are unknown and must NOT be inferred
    # as "not applicable" (that manufactured a supportive 0.0 gap).
    inventory_growth_gap_reported = None
    inventory_growth_gap_inferred = None
    inventory_growth_gap = None
    inventory_growth_gap_source = "missing"
    if (
        inventory_yoy is None
        and inventory_current is not None
        and inventory_prev is not None
        and float(inventory_current) == 0.0
        and float(inventory_prev) == 0.0
    ):
        inventory_yoy = 0.0
    if inventory_yoy is not None and revenue_yoy is not None:
        inventory_growth_gap_reported = float(inventory_yoy) - float(revenue_yoy)
        inventory_growth_gap = inventory_growth_gap_reported
        inventory_growth_gap_source = "reported"

    quality_score = fundamental_quality_score_from_metrics(
        net_debt_to_ebitda=net_debt_to_ebitda,
        interest_coverage=interest_coverage,
        current_ratio=current_ratio,
        ocf_to_net_income=ocf_to_net_income,
        accrual_ratio=accrual_ratio,
    )

    return {
        "capex": capex,
        "free_cash_flow": free_cash_flow,
        "total_debt": total_debt,
        "total_debt_source": total_debt_source,
        "net_debt": net_debt,
        "net_debt_source": net_debt_source,
        "revenue_yoy": revenue_yoy,
        "net_income_yoy": net_income_yoy,
        "adjusted_net_income_yoy": adjusted_net_income_yoy,
        "ebit_yoy": ebit_yoy,
        "adjusted_ebit_yoy": adjusted_ebit_yoy,
        "operating_cash_flow_yoy": operating_cash_flow_yoy,
        "net_income_growth": net_income_growth,
        "net_income_growth_direction": net_income_growth_direction,
        "adjusted_net_income_growth": adjusted_net_income_growth,
        "adjusted_net_income_growth_direction": adjusted_net_income_growth_direction,
        "ebit_growth": ebit_growth,
        "ebit_growth_direction": ebit_growth_direction,
        "adjusted_ebit_growth": adjusted_ebit_growth,
        "adjusted_ebit_growth_direction": adjusted_ebit_growth_direction,
        "operating_cash_flow_growth": operating_cash_flow_growth,
        "operating_cash_flow_growth_direction": operating_cash_flow_growth_direction,
        "shares_yoy": shares_yoy,
        "receivables_yoy": receivables_yoy,
        "inventory_yoy": inventory_yoy,
        "da_yoy": da_yoy,
        "interest_expense": interest_expense_abs,
        "interest_coverage": interest_coverage,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "net_debt_to_ebitda_source": net_debt_to_ebitda_source,
        "current_ratio": current_ratio,
        "current_debt_ratio_reported": current_debt_ratio_reported,
        "current_debt_ratio_inferred": current_debt_ratio_inferred,
        "current_debt_ratio": current_debt_ratio,
        "current_debt_ratio_source": current_debt_ratio_source,
        "ocf_to_net_income": ocf_to_net_income,
        "accrual_ratio": accrual_ratio,
        "receivables_growth_gap": receivables_growth_gap,
        "inventory_growth_gap": inventory_growth_gap,
        "inventory_growth_gap_reported": inventory_growth_gap_reported,
        "inventory_growth_gap_inferred": inventory_growth_gap_inferred,
        "inventory_growth_gap_source": inventory_growth_gap_source,
        "fundamental_quality_score": quality_score,
    }
