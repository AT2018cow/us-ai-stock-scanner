# Entry Quality v1 policy

> Status: **pre-registered MVP v1 policy**
>
> Date frozen for Implementation PR 3: 2026-10-10
>
> Policy version: `entry_quality_v1_2026-10-10`

This document freezes the first Entry Quality rules **before final historical
state-outcome tables are inspected**. Entry Quality answers a narrower question
than Company Quality:

> Given a company that already passes a minimum Company Quality standard, is
> the current price/market setup reasonable enough for immediate human review?

It does not predict short-term returns and it does not create an order.

## 1. Inputs

Entry Quality v1 uses the existing canonical price/replay feature path and adds
only two interpretation-oriented features:

- `price_to_sma50`;
- 60-trading-day relative strength versus QQQ:
  `return_60d - qqq_trailing_return_60d`.

The classifier otherwise reuses:

- `price_to_sma200`;
- `days_below_sma200`;
- `return_20d`;
- `return_60d`;
- `drawdown_from_52w_high`;
- `range_position_52w`;
- `volatility_60d`;
- market regime / benchmark trend context.

No RSI, MACD, ADX, candlestick pattern library, machine-learning classifier, or
legacy list membership is an Entry Quality input.

## 2. Market-data coverage and freshness

The six critical numeric inputs are:

1. `price_to_sma200`;
2. `price_to_sma50`;
3. `return_20d`;
4. `return_60d`;
5. `drawdown_from_52w_high`;
6. `relative_strength_60d_qqq`.

Rules:

- at least five of six critical inputs must be present;
- both SMA ratios are mandatory;
- `market_asof` must be known;
- future `market_asof` relative to the decision date is a hard error;
- market data age <= 3 calendar days is fresh;
- age 4–7 days is allowed but emits a stale-data risk and reduces confidence;
- age > 7 days produces `INSUFFICIENT_DATA`.

Missing evidence never becomes a positive signal.

## 3. State priority

State assignment is deterministic and follows this exact order:

1. `INSUFFICIENT_DATA`;
2. `TREND_DAMAGED`;
3. `WATCH_PULLBACK`;
4. `ENTRY_READY`;
5. otherwise `WATCH_BREAKOUT`.

The final fallback is `WATCH_BREAKOUT` because the current Entry enum has no
separate generic monitoring state. It means the structure is not damaged or
obviously overextended, but confirmation is incomplete.

## 4. TREND_DAMAGED

A sufficient-data observation is `TREND_DAMAGED` if **any** of the following
is true:

- `price_to_sma200 < 0.95`;
- `days_below_sma200 >= 15`;
- `price_to_sma50 < 0.97` **and** `return_60d <= -8%`;
- `return_60d <= -15%` **and** `relative_strength_60d_qqq <= -10%`.

Damage rules have priority over overextension rules. A sharp bounce inside a
damaged long-term structure must not be promoted to a pullback/watch state.

## 5. WATCH_PULLBACK

A sufficient-data, non-damaged observation is `WATCH_PULLBACK` if **any** of
the following chase / extension conditions is true:

- `price_to_sma50 > 1.10`;
- `return_20d > 15%`;
- `range_position_52w >= 0.95` **and** `return_20d > 8%`.

This state deliberately prevents the highest recent-return names from
mechanically becoming `ENTRY_READY`.

## 6. ENTRY_READY

A sufficient-data observation that is neither damaged nor overextended becomes
`ENTRY_READY` only when **all** of the following are true:

- `price_to_sma200 >= 1.00`;
- `0.98 <= price_to_sma50 <= 1.08`;
- `-3% <= return_20d <= 12%`;
- `return_60d >= 0%`;
- `relative_strength_60d_qqq >= -3%`;
- `drawdown_from_52w_high <= 22%`;
- if `volatility_60d` is present, it is <= 80% annualized.

### Defensive-regime gate

If either:

- `regime == "down"`; or
- `benchmark_trend_ok is False`;

then `ENTRY_READY` additionally requires:

- `relative_strength_60d_qqq >= +5%`; and
- `return_20d >= 0%`.

A company can therefore remain technically healthy in a weak market but still
wait for stronger relative confirmation.

## 7. WATCH_BREAKOUT

Any sufficient-data observation that is:

- not `TREND_DAMAGED`;
- not `WATCH_PULLBACK`;
- not `ENTRY_READY`;

is `WATCH_BREAKOUT`.

Typical examples include:

- price remains above SMA200 but is below / only recovering toward SMA50;
- medium-term trend is positive but 20d confirmation is weak;
- relative strength versus QQQ is not yet good enough;
- a defensive regime blocks an otherwise acceptable setup;
- volatility is too high for `ENTRY_READY`.

## 8. Numeric Entry score

The product-facing state is primary. The numeric score is a secondary,
non-optimized diagnostic.

Four fixed components are used:

| Component | Weight | Inputs |
|---|---:|---|
| trend | 35% | SMA200 ratio, SMA50 ratio, days below SMA200 when available |
| momentum | 25% | 20d and 60d return |
| relative strength | 20% | 60d excess return versus QQQ |
| location | 20% | 52w drawdown and range position |

Observed metric scores are averaged inside each component. Missing metrics reduce
component coverage; the effective contribution is
`weight × component score × component coverage`. Confidence is the sum of
weighted component coverage, then freshness/regime-provenance adjustments are
applied.

The score is not used to override the ordered state rules.

### 8.1 Fixed component scoring bands

Trend:

- SMA200 ratio: >=1.05 -> 1.00; >=1.00 -> 0.90; >=0.95 -> 0.50; otherwise 0.00.
- SMA50 ratio: 0.98–1.08 -> 1.00; 0.95–1.10 -> 0.60;
  0.92–1.15 -> 0.30; otherwise 0.00.
- days below SMA200: <=0 -> 1.00; <=5 -> 0.80; <15 -> 0.40; otherwise 0.00.

Momentum:

- 20d return: -3% to +12% -> 1.00; -8% to +15% -> 0.60;
  otherwise 0.20.
- 60d return: >=10% -> 1.00; >=0% -> 0.80; >=-8% -> 0.40;
  otherwise 0.10.

Relative strength versus QQQ:

- >=+5% -> 1.00;
- >=-3% -> 0.75;
- >=-10% -> 0.40;
- otherwise 0.00.

Location:

- 52w drawdown: 3–18% -> 1.00; 0–22% -> 0.75; <=30% -> 0.45;
  otherwise 0.10.
- 52w range position: 0.50–0.90 -> 1.00; 0.30–0.50 -> 0.60;
  0.90–0.95 -> 0.70; >0.95 -> 0.35; otherwise 0.25.

These score bands are also frozen before outcome inspection.

## 9. Historical evaluation

Entry validation is conditional on Company Quality **A or B**. The historical
dataset must be captured from the same pre-strategy PIT cross-section used for
Company Quality validation, before old list-specific hard gates.

Required retrospective diagnostics:

- counts for `ENTRY_READY`, `WATCH_PULLBACK`, `WATCH_BREAKOUT`,
  `TREND_DAMAGED`, and `INSUFFICIENT_DATA`;
- 20d / 60d / 120d return and QQQ excess by Entry state;
- hit rate;
- decision-date-equal-weight outcomes;
- worst-date diagnostics;
- year splits;
- regime splits;
- Quality A vs B splits;
- symbol / date concentration;
- state-to-state transition counts and same-state persistence.

The desired pattern is not that `ENTRY_READY` has the highest recent return.
In fact, the overextension rules intentionally send extreme recent winners to
`WATCH_PULLBACK`.

These outputs are retrospective diagnostics, not OOS evidence and not automatic
promotion criteria. This PR does not tune thresholds from final outcome tables.
