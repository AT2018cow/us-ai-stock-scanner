# A+READY value overlay：便宜档 vs 贵档（只读审计）

- **问题**：在 A+READY 内部，按估值分档（FCF yield / PE 历史分位 / PS 历史分位），便宜档是否跑赢贵档？在 down-ex-2022 是否成立？
- **性质**：retrospective replay，不是 OOS；不是前瞻证据；不自动改变生产行为。
- **决策口径**：复用 `audit_a_ready_regime.py` 的 v2 决策重建；value score 在每个 signal date 内做横截面 rank。

## 1. 数据与覆盖

| 输入 | 行数 | 日期数 | SHA256 |
|---|---:|---:|---|
| `base_2023_2026` | 25025 | 39 | `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e` |
| `bear_2022` | 8251 | 12 | `43e5cd4a440c92857c11106016db0b827202c279e2acfbdc7cb0281ff2f007d6` |

- A+READY 行数：1104；其中有 >=2 个估值指标：1104（100.0%）。
- 可做 cohort 三分位的日期：45；可做 cohort 中位对半的日期：48。
- 三分位要求单日 A+READY 有 >=6 个有估值指标的名字；中位对半要求 >=4 个。
- 宇宙口径：冻结数据集是“硬门幸存者”，不是完整 700 家 universe；baseline 为 survivor-pool。

## 2. 方法

- `value_score = mean(rank(fcf_yield), rank(-pe_hist_percentile), rank(-ps_hist_percentile))`，越高越便宜；至少 2/3 指标可用。
- 主切分：在 A+READY 内部按日期排名（cohort）；稳健性切分：在当日全池排名后取 A+READY 子集（universe）。
- 主统计量：按日期等权的 cheap 档均值；价差 = 同日 cheap 均值 - expensive 均值。
- severe loss = 前向原始收益 <= -20%；成本敏感性 = 10bps round-trip。

## 3. 主结果：A+READY 内部三分位（60d）

| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| cheap | DOWN_EX_2022 | 60d | 9 | -1.81% | 44.4% | 7.5% | -1.91% |
| mid | DOWN_EX_2022 | 60d | 9 | -7.97% | 11.1% | 6.7% | -8.07% |
| expensive | DOWN_EX_2022 | 60d | 9 | -9.37% | 22.2% | 5.7% | -9.47% |
| cheap | BEAR_2022 | 60d | 8 | -3.99% | 50.0% | 12.5% | -4.09% |
| mid | BEAR_2022 | 60d | 8 | +4.87% | 75.0% | 3.8% | +4.77% |
| expensive | BEAR_2022 | 60d | 8 | -1.27% | 37.5% | 4.2% | -1.37% |
| cheap | TRAILING_DOWN | 60d | 16 | -2.48% | 50.0% | 8.0% | -2.58% |
| mid | TRAILING_DOWN | 60d | 16 | -2.62% | 37.5% | 6.0% | -2.72% |
| expensive | TRAILING_DOWN | 60d | 16 | -5.59% | 31.2% | 5.3% | -5.69% |
| cheap | TRAILING_UP | 60d | 29 | -1.05% | 48.3% | 7.4% | -1.15% |
| mid | TRAILING_UP | 60d | 29 | -3.53% | 34.5% | 7.6% | -3.63% |
| expensive | TRAILING_UP | 60d | 29 | -0.11% | 51.7% | 3.7% | -0.21% |
| cheap | ALL | 60d | 45 | -1.56% | 48.9% | 7.6% | -1.66% |
| mid | ALL | 60d | 45 | -3.21% | 35.6% | 7.2% | -3.31% |
| expensive | ALL | 60d | 45 | -2.06% | 44.4% | 4.1% | -2.16% |

### 价差：cheap - expensive（按日期）

| segment | horizon | n_dates | mean_spread | positive_share | t_stat | net_10bps |
|---|---|---:|---:|---:|---:|---:|
| DOWN_EX_2022 | 20d | 9 | -1.91% | 44.4% | -1.04 | -2.01% |
| DOWN_EX_2022 | 60d | 9 | +7.56% | 77.8% | 2.33 | +7.46% |
| DOWN_EX_2022 | 120d | 9 | +7.52% | 77.8% | 2.00 | +7.42% |
| BEAR_2022 | 20d | 8 | -3.07% | 25.0% | -1.16 | -3.17% |
| BEAR_2022 | 60d | 8 | -2.73% | 37.5% | -1.08 | -2.83% |
| BEAR_2022 | 120d | 8 | -5.10% | 62.5% | -1.06 | -5.20% |
| TRAILING_DOWN | 20d | 16 | -2.22% | 37.5% | -1.37 | -2.32% |
| TRAILING_DOWN | 60d | 16 | +3.10% | 62.5% | 1.23 | +3.00% |
| TRAILING_DOWN | 120d | 16 | +2.59% | 75.0% | 0.77 | +2.49% |
| TRAILING_UP | 20d | 29 | -0.85% | 37.9% | -1.07 | -0.95% |
| TRAILING_UP | 60d | 29 | -0.94% | 41.4% | -0.86 | -1.04% |
| TRAILING_UP | 120d | 29 | -0.96% | 44.8% | -0.35 | -1.06% |
| ALL | 20d | 45 | -1.34% | 37.8% | -1.75 | -1.44% |
| ALL | 60d | 45 | +0.50% | 48.9% | 0.43 | +0.40% |
| ALL | 120d | 45 | +0.30% | 55.6% | 0.14 | +0.20% |

### 稳健性：全池排名后取 A+READY 子集（60d）

| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| cheap | DOWN_EX_2022 | 60d | 10 | -2.28% | 30.0% | 7.1% | -2.38% |
| expensive | DOWN_EX_2022 | 60d | 10 | +6.50% | 90.0% | 4.8% | +6.40% |
| cheap | BEAR_2022 | 60d | 12 | +3.03% | 75.0% | 12.0% | +2.93% |
| expensive | BEAR_2022 | 60d | 12 | +0.50% | 66.7% | 16.2% | +0.40% |
| cheap | TRAILING_DOWN | 60d | 21 | +0.45% | 52.4% | 10.0% | +0.35% |
| expensive | TRAILING_DOWN | 60d | 21 | +3.34% | 76.2% | 11.1% | +3.24% |
| cheap | TRAILING_UP | 60d | 30 | -2.26% | 30.0% | 11.6% | -2.36% |
| expensive | TRAILING_UP | 60d | 30 | +0.79% | 50.0% | 13.6% | +0.69% |

### 中位对半（更抗小样本）

| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| cheap | DOWN_EX_2022 | 60d | 10 | -3.11% | 40.0% | 8.3% | -3.21% |
| expensive | DOWN_EX_2022 | 60d | 10 | -9.66% | 0.0% | 4.6% | -9.76% |
| cheap | BEAR_2022 | 60d | 10 | +3.11% | 50.0% | 7.7% | +3.01% |
| expensive | BEAR_2022 | 60d | 10 | +3.13% | 40.0% | 4.7% | +3.03% |
| cheap | TRAILING_DOWN | 60d | 19 | +0.01% | 47.4% | 7.5% | -0.09% |
| expensive | TRAILING_DOWN | 60d | 19 | -3.29% | 21.1% | 4.7% | -3.39% |
| cheap | TRAILING_UP | 60d | 29 | -2.27% | 37.9% | 7.1% | -2.37% |
| expensive | TRAILING_UP | 60d | 29 | -0.97% | 48.3% | 5.4% | -1.07% |

### 绝对估值阈值（固定阈值，不依赖排名宇宙）

cheap = FCF yield >= 5% 或 PE/PS 历史分位 <= 30%；expensive = FCF yield <= 2% 或 PE/PS 历史分位 >= 70%；至少 2 个指标。

| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| cheap | DOWN_EX_2022 | 60d | 10 | -1.91% | 40.0% | 6.3% | -2.01% |
| mid | DOWN_EX_2022 | 60d | 10 | +4.24% | 80.0% | 7.8% | +4.14% |
| expensive | DOWN_EX_2022 | 60d | 10 | +6.32% | 90.0% | 6.2% | +6.22% |
| cheap | BEAR_2022 | 60d | 12 | +2.85% | 75.0% | 11.7% | +2.75% |
| mid | BEAR_2022 | 60d | 12 | -0.75% | 25.0% | 27.0% | -0.85% |
| expensive | BEAR_2022 | 60d | 12 | +0.23% | 50.0% | 23.2% | +0.13% |
| cheap | TRAILING_DOWN | 60d | 21 | +0.61% | 57.1% | 9.9% | +0.51% |
| mid | TRAILING_DOWN | 60d | 21 | +1.00% | 47.6% | 20.4% | +0.90% |
| expensive | TRAILING_DOWN | 60d | 21 | +2.91% | 66.7% | 13.6% | +2.81% |
| cheap | TRAILING_UP | 60d | 30 | -2.42% | 30.0% | 11.2% | -2.52% |
| mid | TRAILING_UP | 60d | 30 | +0.20% | 60.0% | 13.0% | +0.10% |
| expensive | TRAILING_UP | 60d | 30 | +1.24% | 50.0% | 14.0% | +1.14% |

### 绝对阈值价差：cheap - expensive

| segment | horizon | n_dates | mean_spread | positive_share | t_stat | net_10bps |
|---|---|---:|---:|---:|---:|---:|
| DOWN_EX_2022 | 20d | 10 | -2.90% | 30.0% | -1.65 | -3.00% |
| DOWN_EX_2022 | 60d | 10 | -8.24% | 10.0% | -3.80 | -8.34% |
| DOWN_EX_2022 | 120d | 10 | -5.60% | 30.0% | -1.26 | -5.70% |
| BEAR_2022 | 20d | 12 | +0.96% | 58.3% | 0.94 | +0.86% |
| BEAR_2022 | 60d | 12 | +2.61% | 58.3% | 1.46 | +2.51% |
| BEAR_2022 | 120d | 12 | +4.00% | 83.3% | 1.98 | +3.90% |
| TRAILING_DOWN | 20d | 21 | -0.85% | 42.9% | -0.78 | -0.95% |
| TRAILING_DOWN | 60d | 21 | -2.30% | 38.1% | -1.22 | -2.40% |
| TRAILING_DOWN | 120d | 21 | -0.26% | 61.9% | -0.10 | -0.36% |
| TRAILING_UP | 20d | 30 | -1.43% | 40.0% | -1.88 | -1.53% |
| TRAILING_UP | 60d | 30 | -3.65% | 30.0% | -3.16 | -3.75% |
| TRAILING_UP | 120d | 30 | -9.28% | 16.7% | -4.32 | -9.38% |
| ALL | 20d | 51 | -1.19% | 41.2% | -1.90 | -1.29% |
| ALL | 60d | 51 | -3.10% | 33.3% | -3.02 | -3.20% |
| ALL | 120d | 51 | -5.56% | 35.3% | -3.18 | -5.66% |

## 4. 关键读数

- **结论先行**：value overlay 不稳健——cohort 内排名为正，但全池排名与绝对阈值均为负；不能据此建立买入规则。
- **down-ex-2022（60d）**：cheap -1.81% vs expensive -9.37%；cheap 正日期占比 44.4%，n_dates=9。
- **价差（down-ex-2022, 60d, cohort 三分位）**：cheap - expensive +7.56%，正日期占比 77.8%，t=2.33，扣 10bps 后 +7.46%。
- **定义敏感性（down-ex-2022, 60d）**：cohort 三分位 +7.56%；全池三分位 -8.78%（正日期 0.0%）；绝对阈值 -8.24%（正日期 10.0%）。
- **结论：value overlay 不稳健**——cohort 内排名为正，全池排名为负；符号取决于排名宇宙，不能直接当买入规则。
- **全样本（60d）**：cheap -1.56% vs expensive -2.06%；价差 +0.50%。
- 结论方向：**定义冲突**；不能判定 value overlay 有效，不要据此建立买入规则。
- 样本限制：cohort 三分位在小日期上只有 2-3 个名字；60d 窗口重叠；t 值只能当描述性参考。

## 5. 每日期明细

`per_date_value.csv` 给出每个日期、每个 bucket 的 60d 均值与 cheap-expensive 价差，用于检查结果是否被少数日期主导。

## 6. 边界与下一步

- 这是 retrospective replay；不能称为 OOS，也不能自动 promote 生产阈值。
- 若 value overlay 有效：把它写成候选规则，再用前瞻 immutable snapshot 复核。
- 若无效：接受 A+READY 是风险过滤器，不要继续在它身上叠加因子直到过拟合。

## 7. 复现

```bash
.venv/bin/python scripts/audit_a_ready_value_overlay.py \
  --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
  --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv \
  --regime-labels docs/regime_indicator_validation_20261017/per_date_regimes.csv \
  --out-dir docs/a_ready_value_overlay_20261119
```
