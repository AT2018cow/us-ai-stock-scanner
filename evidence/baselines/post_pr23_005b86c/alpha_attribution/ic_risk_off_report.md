# Production-score ranking diagnostics — risk_off

Hard-gate survivors are scored with the current production weights.
These are descriptive forward-return labels, not account NAV.

## All-channel headline

- low_value 20d: mean_IC=+0.0210, t_NW=+1.44, top-bottom excess=-0.0044, adjacent-up=56%
- low_value 60d: mean_IC=+0.0296, t_NW=+2.10, top-bottom excess=-0.0142, adjacent-up=56%
- low_value 120d: mean_IC=+0.0524, t_NW=+3.19, top-bottom excess=+0.0023, adjacent-up=67%
- momentum 20d: mean_IC=+0.0535, t_NW=+3.27, top-bottom excess=+0.0162, adjacent-up=67%
- momentum 60d: mean_IC=+0.0506, t_NW=+2.56, top-bottom excess=+0.0197, adjacent-up=56%
- momentum 120d: mean_IC=+0.0955, t_NW=+4.83, top-bottom excess=+0.0690, adjacent-up=78%

## Interpretation gate

- Continue weight/threshold research only if the score has a positive, reasonably stable rank relationship and the upper deciles outperform the lower deciles across more than one year/regime/channel.
- A single strong year or a non-monotone decile curve is not evidence to tune production weights.
- QQQ excess is shown for level comparisons; within-date rank IC is unchanged by subtracting the same QQQ return from every stock.
