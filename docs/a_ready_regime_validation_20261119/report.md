# A+READY 与 regime：冻结数据回测（只读审计）

- **问题**：`Company Quality A + Entry Quality ENTRY_READY` 的 20/60/120 日前向收益，是否跑赢 QQQ？在 trailing regime = down 时是否仍然成立？
- **性质**：retrospective replay，不是 OOS；不是前瞻证据；不自动改变生产行为。
- **决策口径**：`build_stock_decisions(policy_version="v2")`，与线上同一套 quality v2 / entry v2 / action v2。

## 1. 数据与可复现性

| 输入 | 行数 | 日期数 | SHA256 |
|---|---:|---:|---|
| `base_2023_2026` | 25025 | 39 | `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e` |
| `bear_2022` | 8251 | 12 | `43e5cd4a440c92857c11106016db0b827202c279e2acfbdc7cb0281ff2f007d6` |

- Runner: `audit_a_ready_regime.py` · SHA256 `e1e347b5b42af5f93606fe4d58404931706992f9938ab2ae8c665a6901426aa9`
- 合并样本：33276 行 / 51 个日期；其中 regime down 21 个（2022 熊市 12 个）。
- 宇宙口径：冻结数据集是“硬门幸存者”，不是完整 700 家 universe；baseline 为 survivor-pool，不是全市场。
- watchlist 口径：当前 watchlist 回填历史（union superset approximation）；不是真正的 PIT ETF 成分历史。

## 2. 方法

- 每个 signal date 重建 v2 决策；cohort 为逐行状态，不含 Grace / 顺序 action。
- 前向窗口重叠，行不是独立样本；主统计量是“按日期等权的 cohort 均值”，并报告正日期占比与描述性 t 值。
- severe loss = 前向原始收益 <= -20%；成本敏感性 = 10bps / 20bps round-trip。

## 3. 主结果：A+READY vs 全池

| cohort | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| A_AND_READY | TRAILING_DOWN | 20d | 21 | +0.37% | 33.3% | 2.3% | +0.27% |
| A_AND_READY | TRAILING_DOWN | 60d | 21 | -0.96% | 38.1% | 6.2% | -1.06% |
| A_AND_READY | TRAILING_DOWN | 120d | 21 | -3.09% | 52.4% | 10.9% | -3.19% |
| A_AND_READY | TRAILING_UP | 20d | 30 | -0.61% | 46.7% | 1.2% | -0.71% |
| A_AND_READY | TRAILING_UP | 60d | 30 | -1.20% | 50.0% | 6.3% | -1.30% |
| A_AND_READY | TRAILING_UP | 120d | 30 | -3.56% | 33.3% | 9.5% | -3.66% |
| A_AND_READY | BEAR_2022 | 20d | 12 | +1.73% | 50.0% | 3.4% | +1.63% |
| A_AND_READY | BEAR_2022 | 60d | 12 | +3.76% | 50.0% | 6.8% | +3.66% |
| A_AND_READY | BEAR_2022 | 120d | 12 | -0.85% | 58.3% | 21.6% | -0.95% |
| A_AND_READY | DOWN_EX_2022 | 20d | 10 | -1.01% | 20.0% | 1.7% | -1.11% |
| A_AND_READY | DOWN_EX_2022 | 60d | 10 | -6.67% | 20.0% | 6.2% | -6.77% |
| A_AND_READY | DOWN_EX_2022 | 120d | 10 | -7.45% | 40.0% | 5.7% | -7.55% |
| A_AND_READY | ALL | 20d | 51 | -0.21% | 41.2% | 1.4% | -0.31% |
| A_AND_READY | ALL | 60d | 51 | -1.10% | 45.1% | 6.2% | -1.20% |
| A_AND_READY | ALL | 120d | 51 | -3.37% | 41.2% | 9.8% | -3.47% |

### 对照：全池 / QUALITY_A / ENTRY_READY（60d）

| cohort | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| UNIVERSE | TRAILING_DOWN | 60d | 21 | +1.72% | 71.4% | 14.1% | +1.62% |
| UNIVERSE | TRAILING_UP | 60d | 30 | -0.19% | 50.0% | 12.9% | -0.29% |
| QUALITY_A | TRAILING_DOWN | 60d | 21 | -0.26% | 42.9% | 9.5% | -0.36% |
| QUALITY_A | TRAILING_UP | 60d | 30 | -1.50% | 36.7% | 9.3% | -1.60% |
| ENTRY_READY | TRAILING_DOWN | 60d | 21 | -1.81% | 33.3% | 5.6% | -1.91% |
| ENTRY_READY | TRAILING_UP | 60d | 30 | -1.63% | 33.3% | 7.9% | -1.73% |
| A_AND_READY | TRAILING_DOWN | 60d | 21 | -0.96% | 38.1% | 6.2% | -1.06% |
| A_AND_READY | TRAILING_UP | 60d | 30 | -1.20% | 50.0% | 6.3% | -1.30% |
| A_AND_READY_TOP15 | TRAILING_DOWN | 60d | 21 | -0.79% | 38.1% | 5.7% | -0.89% |
| A_AND_READY_TOP15 | TRAILING_UP | 60d | 30 | -1.57% | 33.3% | 6.9% | -1.67% |

## 4. 关键读数

- **regime down（60d）**：date-level 超额 -0.96%，正日期占比 38.1%，severe-loss 6.2%，n_dates=21；扣 10bps 后 -1.06%。
- **regime up（60d）**：date-level 超额 -1.20%，正日期占比 50.0%，severe-loss 6.3%，n_dates=30；扣 10bps 后 -1.30%。
- **2022 熊市（60d）**：date-level 超额 +3.76%，正日期占比 50.0%，severe-loss 6.8%，n_dates=12；扣 10bps 后 +3.66%。
- **down 且非 2022（60d）**：date-level 超额 -6.67%，正日期占比 20.0%，severe-loss 6.2%，n_dates=10；扣 10bps 后 -6.77%。
- 结论方向：down 与 up 都不为正；这套信号在冻结样本上没有稳定 edge。
- **相对 survivor pool**：同一批 down 日期，全池 60d 超额 +1.72%，A+READY -0.96%；A+READY 的 severe-loss 6.2% vs 全池 14.1%。
- **2022 vs 非 2022**：2022 熊市 60d 超额 +3.76%，但非 2022 的 down 日期 -6.67%（正日期占比 20.0%，n_dates=10）。防御性在 2022 有效，在 2023–2026 的 AI 快速反弹里反而拖累。
- 读法：A+READY 更像“低波动/低回撤过滤器”，不是 alpha 信号；它降低尾部风险，但在反弹里让出上行。
- 样本限制：down 日期里 2022 熊市占多数；60d 窗口重叠；t 值只能当描述性参考，不能当显著性证明。

## 5. 为什么跑输：低波动/低回撤的代价

行级均值（非日期等权），用于解释 cohort 的风险画像；severe-loss 为 60d 原始收益 <= -20%。

| cohort | segment | n_rows | vol_60d | drawdown_52w | SMA200 | 20d | 60d |
|---|---|---:|---:|---:|---:|---:|---:|
| UNIVERSE | ALL | 33276 | 49.1% | 26.3% | 1.016x | +1.52% | +3.32% |
| UNIVERSE | TRAILING_DOWN | 14046 | 50.4% | 32.1% | 0.935x | -2.83% | -6.07% |
| UNIVERSE | DOWN_EX_2022 | 6485 | 47.3% | 26.5% | 1.004x | -2.48% | -2.59% |
| UNIVERSE | BEAR_2022 | 8251 | 53.6% | 36.9% | 0.880x | -2.49% | -8.13% |
| A_AND_READY | ALL | 1104 | 29.3% | 6.3% | 1.162x | +3.60% | +14.61% |
| A_AND_READY | TRAILING_DOWN | 258 | 32.0% | 7.2% | 1.146x | +4.06% | +13.13% |
| A_AND_READY | DOWN_EX_2022 | 176 | 31.4% | 6.7% | 1.164x | +3.91% | +13.98% |
| A_AND_READY | BEAR_2022 | 88 | 33.4% | 8.3% | 1.109x | +4.27% | +11.57% |

## 6. 对当前 regime 的含义

- 当前（2026-11-18）是 **down 且非 2022**；历史同类 bucket 是 `DOWN_EX_2022`：60d 超额 -6.67%，正日期占比 20.0%，n_dates=10。
- 这不是“一定会跌”，是“历史上这个 cohort 在同类 regime 里跑输 survivor pool”。
- 如果目标是“少亏”，A+READY 的 severe-loss 更低；如果目标是“跑赢 QQQ”，这套信号在冻结样本上没有证明。

## 7. 每日期明细

`per_date.csv` 给出每个 signal date、每个 cohort 的 20/60/120d 等权均值，用于检查结果是否被少数日期主导。

## 8. 边界与下一步

- 这是 retrospective replay；不能称为 OOS，也不能自动 promote 生产阈值。
- 本次结果：A+READY 在 down 与 up 都没有正超额；2022 宽熊是唯一正 bucket；当前 down-ex-2022 是最差 bucket。
- 因此：不要把 A+READY 当 alpha 信号；它是低波动/低回撤过滤器，适合“少亏”，不适合“跑赢”。
- 下一步（廉价、可复现）：在现有 51 个日期上做 value overlay 分层（`fcf_yield` / `pe_hist_percentile` / `ps_hist_percentile`），看能否把 down-ex-2022 的 -6.67% 拉回 0 以上；再决定是否进入买入规则。
- 若 overlay 也无效：接受“系统是风险过滤器”，不要再把它当 alpha 用。

## 9. 复现

```bash
.venv/bin/python scripts/audit_a_ready_regime.py \
  --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
  --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv \
  --regime-labels docs/regime_indicator_validation_20261017/per_date_regimes.csv \
  --out-dir docs/a_ready_regime_validation_20261119
```
