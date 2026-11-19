# A+READY momentum / growth overlay（只读审计）

- **问题**：在 A+READY 内部，按 momentum / growth 分档，强档是否跑赢弱档？能否修好 down-ex-2022 的负超额？
- **性质**：retrospective replay，不是 OOS；不是前瞻证据；不自动改变生产行为。
- **决策口径**：复用 `audit_a_ready_regime.py` 的 v2 决策重建；score 在每个 signal date 内做横截面 rank。

## 1. 数据与覆盖

| 输入 | 行数 | 日期数 | SHA256 |
|---|---:|---:|---|
| `base_2023_2026` | 25025 | 39 | `2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e` |
| `bear_2022` | 8251 | 12 | `43e5cd4a440c92857c11106016db0b827202c279e2acfbdc7cb0281ff2f007d6` |

- A+READY 行数：1104；momentum 有 >=2 指标：1104；growth 有 >=2 指标：1104。
- 可做 cohort 三分位的日期：46；可做 cohort 中位对半的日期：48。
- 宇宙口径：冻结数据集是“硬门幸存者”，不是完整 700 家 universe；baseline 为 survivor-pool。

## 2. 方法

- momentum = mean(rank(return_60d), rank(relative_strength_60d_qqq))；growth = mean(rank(revenue_yoy), rank(adjusted_net_income_yoy), rank(operating_cash_flow_yoy))，至少 2/3。
- 三种定义：cohort 内排名、全池排名后取 A+READY 子集、固定绝对阈值；只有三种定义同号才算稳健。
- 主统计量：按日期等权的 strong 档均值；价差 = 同日 strong - weak。
- severe loss = 前向原始收益 <= -20%；成本敏感性 = 10bps round-trip。
- 多重检验：momentum 是主检验，growth 是次级，combined 是探索性；同一批 51 个日期上反复测试会提高假阳性概率。

## 3.1 Momentum

### 60d：strong / mid / weak（cohort 内三分位）

| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| strong | DOWN_EX_2022 | 60d | 10 | -7.83% | 10.0% | 7.1% | -7.93% |
| mid | DOWN_EX_2022 | 60d | 10 | -3.96% | 20.0% | 6.2% | -4.06% |
| weak | DOWN_EX_2022 | 60d | 10 | -8.48% | 20.0% | 5.4% | -8.58% |
| strong | BEAR_2022 | 60d | 8 | -2.50% | 37.5% | 12.5% | -2.60% |
| mid | BEAR_2022 | 60d | 8 | -1.39% | 50.0% | 3.8% | -1.49% |
| weak | BEAR_2022 | 60d | 8 | +3.91% | 75.0% | 4.2% | +3.81% |
| strong | TRAILING_DOWN | 60d | 17 | -5.15% | 23.5% | 7.7% | -5.25% |
| mid | TRAILING_DOWN | 60d | 17 | -2.82% | 35.3% | 5.7% | -2.92% |
| weak | TRAILING_DOWN | 60d | 17 | -3.68% | 41.2% | 5.1% | -3.78% |
| strong | TRAILING_UP | 60d | 29 | -1.03% | 41.4% | 8.4% | -1.13% |
| mid | TRAILING_UP | 60d | 29 | -1.29% | 51.7% | 6.1% | -1.39% |
| weak | TRAILING_UP | 60d | 29 | -2.11% | 37.9% | 4.4% | -2.21% |
| strong | ALL | 60d | 46 | -2.55% | 34.8% | 8.2% | -2.65% |
| mid | ALL | 60d | 46 | -1.86% | 45.7% | 6.0% | -1.96% |
| weak | ALL | 60d | 46 | -2.69% | 39.1% | 4.5% | -2.79% |

### 价差：strong - weak（三种定义，60d）

| definition | segment | horizon | n_dates | mean_spread | positive_share | t_stat | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| cohort | DOWN_EX_2022 | 60d | 10 | +0.65% | 50.0% | 0.21 | +0.55% |
| cohort | BEAR_2022 | 60d | 8 | -6.41% | 37.5% | -1.52 | -6.51% |
| cohort | TRAILING_DOWN | 60d | 17 | -1.46% | 47.1% | -0.58 | -1.56% |
| cohort | TRAILING_UP | 60d | 29 | +1.08% | 48.3% | 0.64 | +0.98% |
| cohort | ALL | 60d | 46 | +0.14% | 47.8% | 0.10 | +0.04% |
| universe | DOWN_EX_2022 | 60d | 10 | -5.41% | 30.0% | -1.07 | -5.51% |
| universe | BEAR_2022 | 60d | 12 | -0.19% | 41.7% | -0.06 | -0.29% |
| universe | TRAILING_DOWN | 60d | 21 | -2.04% | 38.1% | -0.69 | -2.14% |
| universe | TRAILING_UP | 60d | 30 | +2.82% | 70.0% | 1.49 | +2.72% |
| universe | ALL | 60d | 51 | +0.82% | 56.9% | 0.49 | +0.72% |
| absolute | DOWN_EX_2022 | 60d | 10 | -2.88% | 30.0% | -0.73 | -2.98% |

## 3.2 Growth

### 60d：strong / mid / weak（cohort 内三分位）

| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| strong | DOWN_EX_2022 | 60d | 10 | -8.14% | 20.0% | 10.7% | -8.24% |
| mid | DOWN_EX_2022 | 60d | 10 | -5.06% | 30.0% | 6.2% | -5.16% |
| weak | DOWN_EX_2022 | 60d | 10 | -6.65% | 20.0% | 1.8% | -6.75% |
| strong | BEAR_2022 | 60d | 8 | -0.07% | 50.0% | 12.5% | -0.17% |
| mid | BEAR_2022 | 60d | 8 | -0.72% | 62.5% | 7.7% | -0.82% |
| weak | BEAR_2022 | 60d | 8 | +0.85% | 50.0% | 0.0% | +0.75% |
| strong | TRAILING_DOWN | 60d | 17 | -4.19% | 35.3% | 10.3% | -4.29% |
| mid | TRAILING_DOWN | 60d | 17 | -3.49% | 41.2% | 6.8% | -3.59% |
| weak | TRAILING_DOWN | 60d | 17 | -3.70% | 29.4% | 1.3% | -3.80% |
| strong | TRAILING_UP | 60d | 29 | -1.17% | 44.8% | 8.4% | -1.27% |
| mid | TRAILING_UP | 60d | 29 | -1.94% | 44.8% | 4.4% | -2.04% |
| weak | TRAILING_UP | 60d | 29 | -1.12% | 37.9% | 6.2% | -1.22% |
| strong | ALL | 60d | 46 | -2.29% | 41.3% | 8.8% | -2.39% |
| mid | ALL | 60d | 46 | -2.51% | 43.5% | 5.0% | -2.61% |
| weak | ALL | 60d | 46 | -2.08% | 34.8% | 5.1% | -2.18% |

### 价差：strong - weak（三种定义，60d）

| definition | segment | horizon | n_dates | mean_spread | positive_share | t_stat | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| cohort | DOWN_EX_2022 | 60d | 10 | -1.49% | 40.0% | -0.46 | -1.59% |
| cohort | BEAR_2022 | 60d | 8 | -0.92% | 50.0% | -0.30 | -1.02% |
| cohort | TRAILING_DOWN | 60d | 17 | -0.48% | 47.1% | -0.22 | -0.58% |
| cohort | TRAILING_UP | 60d | 29 | -0.05% | 51.7% | -0.03 | -0.15% |
| cohort | ALL | 60d | 46 | -0.21% | 50.0% | -0.15 | -0.31% |
| universe | DOWN_EX_2022 | 60d | 10 | +1.75% | 50.0% | 0.86 | +1.65% |
| universe | BEAR_2022 | 60d | 12 | -3.68% | 16.7% | -3.29 | -3.78% |
| universe | TRAILING_DOWN | 60d | 21 | -1.30% | 28.6% | -1.01 | -1.40% |
| universe | TRAILING_UP | 60d | 30 | +0.94% | 50.0% | 0.96 | +0.84% |
| universe | ALL | 60d | 51 | +0.02% | 41.2% | 0.02 | -0.08% |
| absolute | DOWN_EX_2022 | 60d | 10 | +2.21% | 50.0% | 1.21 | +2.11% |

## 3.3 Momentum+Growth（探索性）

### 60d：strong / mid / weak（cohort 内三分位）

| bucket | segment | horizon | n_dates | date_mean_excess | positive_date_share | severe_loss | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| strong | DOWN_EX_2022 | 60d | 10 | -6.63% | 20.0% | 8.9% | -6.73% |
| mid | DOWN_EX_2022 | 60d | 10 | -6.69% | 10.0% | 6.2% | -6.79% |
| weak | DOWN_EX_2022 | 60d | 10 | -6.18% | 30.0% | 3.6% | -6.28% |
| strong | BEAR_2022 | 60d | 8 | +1.41% | 50.0% | 12.5% | +1.31% |
| mid | BEAR_2022 | 60d | 8 | -0.15% | 50.0% | 3.8% | -0.25% |
| weak | BEAR_2022 | 60d | 8 | -1.37% | 50.0% | 4.2% | -1.47% |
| strong | TRAILING_DOWN | 60d | 17 | -2.61% | 35.3% | 9.0% | -2.71% |
| mid | TRAILING_DOWN | 60d | 17 | -3.84% | 29.4% | 5.7% | -3.94% |
| weak | TRAILING_DOWN | 60d | 17 | -4.82% | 35.3% | 3.8% | -4.92% |
| strong | TRAILING_UP | 60d | 29 | -1.21% | 41.4% | 9.1% | -1.31% |
| mid | TRAILING_UP | 60d | 29 | -0.75% | 34.5% | 4.7% | -0.85% |
| weak | TRAILING_UP | 60d | 29 | -2.40% | 27.6% | 5.1% | -2.50% |
| strong | ALL | 60d | 46 | -1.73% | 39.1% | 9.1% | -1.83% |
| mid | ALL | 60d | 46 | -1.89% | 32.6% | 5.0% | -1.99% |
| weak | ALL | 60d | 46 | -3.29% | 30.4% | 4.8% | -3.39% |

### 价差：strong - weak（三种定义，60d）

| definition | segment | horizon | n_dates | mean_spread | positive_share | t_stat | net_10bps |
|---|---|---|---:|---:|---:|---:|---:|
| cohort | DOWN_EX_2022 | 60d | 10 | -0.45% | 40.0% | -0.12 | -0.55% |
| cohort | BEAR_2022 | 60d | 8 | +2.77% | 75.0% | 0.66 | +2.67% |
| cohort | TRAILING_DOWN | 60d | 17 | +2.21% | 58.8% | 0.84 | +2.11% |
| cohort | TRAILING_UP | 60d | 29 | +1.19% | 41.4% | 0.65 | +1.09% |
| cohort | ALL | 60d | 46 | +1.56% | 47.8% | 1.04 | +1.46% |
| universe | DOWN_EX_2022 | 60d | 10 | -1.73% | 40.0% | -0.57 | -1.83% |
| universe | BEAR_2022 | 60d | 12 | -1.92% | 25.0% | -1.58 | -2.02% |
| universe | TRAILING_DOWN | 60d | 21 | -1.80% | 33.3% | -1.16 | -1.90% |
| universe | TRAILING_UP | 60d | 30 | +2.91% | 70.0% | 2.51 | +2.81% |
| universe | ALL | 60d | 51 | +0.97% | 54.9% | 0.99 | +0.87% |

## 4. 关键读数

- **Momentum（down-ex-2022, 60d）**：cohort +0.65%；universe -5.41%；absolute -2.88%。符号不一致 → 不稳健。
- **Growth（down-ex-2022, 60d）**：cohort -1.49%；universe +1.75%；absolute +2.21%。符号不一致 → 不稳健。
- **Momentum+Growth（探索性）（down-ex-2022, 60d）**：cohort -0.45%；universe -1.73%。符号不一致 → 不稳健。
- 多重检验警告：同一批 51 个日期上测试了 momentum / growth / combined，任何单一正结果都不能直接 promote；需要前瞻或独立样本复核。
- 样本限制：cohort 三分位在小日期上只有 2-3 个名字；60d 窗口重叠；t 值只能当描述性参考。

## 5. 边界与下一步

- 这是 retrospective replay；不能称为 OOS，也不能自动 promote 生产阈值。
- 若某个因子三种定义同为正：写成候选规则，用前瞻 immutable snapshot 复核。
- 若都不稳健：停止在这批数据上继续加因子，避免过拟合；接受 A+READY 是风险过滤器。

## 6. 复现

```bash
.venv/bin/python scripts/audit_a_ready_momentum_growth_overlay.py \
  --base-dataset outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv \
  --bear-2022-dataset outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv \
  --regime-labels docs/regime_indicator_validation_20261017/per_date_regimes.csv \
  --out-dir docs/a_ready_momentum_growth_overlay_20261119
```
