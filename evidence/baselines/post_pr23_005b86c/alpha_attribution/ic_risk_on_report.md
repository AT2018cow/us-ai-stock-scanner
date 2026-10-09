# Production-score ranking diagnostics — risk_on

Hard-gate survivors are scored with the current production weights.
These are descriptive forward-return labels, not account NAV.

## All-channel headline

- low_value 20d: mean_IC=+0.0307, t_NW=+1.20, top-bottom excess=+0.0184, adjacent-up=56%
- low_value 60d: mean_IC=+0.0500, t_NW=+1.77, top-bottom excess=+0.0360, adjacent-up=67%
- low_value 120d: mean_IC=+0.0543, t_NW=+1.79, top-bottom excess=+0.0561, adjacent-up=44%
- momentum 20d: mean_IC=+0.0553, t_NW=+3.17, top-bottom excess=+0.0155, adjacent-up=78%
- momentum 60d: mean_IC=+0.0476, t_NW=+2.15, top-bottom excess=+0.0186, adjacent-up=56%
- momentum 120d: mean_IC=+0.0936, t_NW=+4.44, top-bottom excess=+0.0678, adjacent-up=56%

## Interpretation gate

- Continue weight/threshold research only if the score has a positive, reasonably stable rank relationship and the upper deciles outperform the lower deciles across more than one year/regime/channel.
- A single strong year or a non-monotone decile curve is not evidence to tune production weights.
- QQQ excess is shown for level comparisons; within-date rank IC is unchanged by subtracting the same QQQ return from every stock.
