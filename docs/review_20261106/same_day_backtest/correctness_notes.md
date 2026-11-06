# Correctness changes during implementation

- The evaluator now calls the shared production price/liquidity prefilter and `select_weekly_attention`, rather than treating priority<=15 as the product list.
- Snapshot parity: all 16 existing official weekly lists reproduce exactly from their stored canonical decisions. This proves selection parity, not historical input parity.
- Frozen 2022 labels contain mismatched stock/QQQ end dates. Intermediate frozen-data runs are diagnostics only; formal extended results require newly extracted labels.
- The historical session calendar omitted the 2018-12-05 and 2025-01-09 exchange closures. Both are now explicit. Source: [ICE Carter notice](https://ir.theice.com/press/news-details/2024/The-New-York-Stock-Exchange-Will-Close-Markets-on-January-9-to-Honor-the-Passing-of-Former-President-Jimmy-Carter-on-National-Day-of-Mourning/default.aspx), [ICE Bush notice](https://s2.q4cdn.com/154085107/files/doc_news/archive/266fafb2-a85c-433a-8350-0760d895b49c.pdf).
- Rebalance dates roll back exchange holidays to the preceding session. These are correctness changes shared by baseline/candidate, not return-tuned candidates.
- The first monthly extraction launched before these calendar corrections is provisional; it must not substitute for the corrected extraction.
- Candidate remains the single preregistered removal of the filing-age ranking penalty. Production default penalty stays unchanged unless adoption gates pass.
- Annual (252-session) labels require an exchange-holiday allowance beyond the short 7/5 calendar approximation. The long-window guard and split-query coverage now share an extended annual envelope; an independent 252-session fixture verifies acceptance.
- SIP prices are stored under an isolated `alpaca_sip_research` cache directory. Legacy cross-key cache fallback has no embedded feed identity; sharing it would risk mixing IEX/SIP volume semantics. Production cache/feed remains IEX.
- Dates lacking benchmark SMA200/60d warm-up remain in the output, with unknown market group; they are excluded from formal paired comparison on an input-availability rule, not on return magnitude.
