# Universe review — candidate-universe provenance experiment

Source snapshot: outputs/decision_experiments/risk_off_20261011T023956Z/2026-10-09/risk_off
Code SHA: aa59e9d8c4593a815f6c17e906b703bf686d988e
Contract: candidate_universe_v1_2026-10-11
Feed: iex, min_price=1.0, min_dollar_volume=2000000.0
Watchlist refreshed before run: no (used current data/ai_watchlist.csv, archived with sha256)

## 1. Funnel counts

- discovery_unique_symbols: 687
- tradable_mapped_symbols: 678
- post_sample_symbols: 678 (full run, no sampling)
- decision_universe_symbols: 510
- excluded_symbols: 177

Conservation: 687 = 510 + 177; 678 = 510 + 168.

## 2. Exclusions by stage and reason

Stage counts: asset_eligibility=6, sec_mapping=3, price_liquidity_prefilter=168.
Reason counts: ALPACA_ACTIVE_ASSET_MISSING=6, SEC_MAPPING_MISSING=3,
DOLLAR_VOLUME_BELOW_MIN=167, PRICE_BELOW_MIN=1.

## 3. ARQQ and QUBT (both present in archived watchlist)

ARQQ (ai_smallcap, SRC:NASDAQ_SCREEN):
- stage=price_liquidity_prefilter, reason=DOLLAR_VOLUME_BELOW_MIN
- price=17.33, dollar_volume=261041.79 (iex) vs min 2000000.0

QUBT (ai_smallcap, SRC:NASDAQ_SCREEN):
- stage=price_liquidity_prefilter, reason=DOLLAR_VOLUME_BELOW_MIN
- price=7.43, dollar_volume=1407004.24 (iex) vs min 2000000.0

Both rows carry feed/threshold/watchlist provenance in universe_exclusions.jsonl.

## 4. DOLLAR_VOLUME_BELOW_MIN examples (very low to near-threshold, iex)

- MOVE: price=9.875, dollar_volume=9944
- EVCM: price=9.06, dollar_volume=23320
- GRVY: price=66.855, dollar_volume=36637
- ARQQ: price=17.33, dollar_volume=261041.79
- QUBT: price=7.43, dollar_volume=1407004.24
- CNXC: price=25.95, dollar_volume=1984708
- MATX: price=226.08, dollar_volume=1994026
- LSTR: price=169.17, dollar_volume=1995191 (nearest to threshold)

Threshold min_dollar_volume=2000000.0 in all rows.

## 5. All non-price/liquidity exclusions

- AVB, DBRG, EQR, QRVO, WBD: ALPACA_ACTIVE_ASSET_MISSING / asset_eligibility
- YCA.L: ALPACA_ACTIVE_ASSET_MISSING / asset_eligibility (non-US listing suffix)
- HEI.A, MOG.A, UHAL.B: SEC_MAPPING_MISSING / sec_mapping (class-share dotted tickers)
- (For completeness, the single PRICE_BELOW_MIN row: BLND, price=0.9978, stage=price_liquidity_prefilter)

## 6. Conservation confirmation

Verified against archived data/ai_watchlist.csv (687 unique symbols):
- every discovery symbol has exactly one outcome: 510 decisions + 177 exclusions;
- zero duplicate exclusion symbols; zero decision/exclusion overlap;
- zero discovery symbols uncovered; zero exclusion symbols outside discovery.

## 7. Policy/threshold confirmation

This run's Quality/Entry/Action distributions are identical to the approved
formal snapshot (A=183/B=205/C=92/UNRATED=30; Entry 47/85/141/230/7;
Action 19/33/55/281/122). No Quality / Entry / Action / config-threshold
change in this PR; only exclusion observability was added.
