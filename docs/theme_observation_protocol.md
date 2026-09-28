# 五主题观察协议（预注册，P0 纸面）

> 状态：生效（2026-09-28）
> 观察对象：nuclear / quantum / biotech / rare_earth / critical_minerals 五条主题 sleeve
> 依据：docs/multi_theme_expansion.md（阶段 2 引擎已上线，本协议为阶段 3 的 P0 纸面接入）

## 1. 原则

- **零资本**：所有主题只做纸面观察，不进入 generate_trade_plan，不与 AI 试点共享任何资金规则
- **隔离**：主题扫描不归档 AI PIT 快照（`archive_watchlist_snapshots=false`），watchlist 独立，
  报告以 `Config:` 头识别，与 AI 双风格的观察并行互不干扰
- **同构评价**：cohort 机制与 AI 试点一致——120 个交易日持有、重叠月度 cohort、
  绝对收益 + 超额 vs QQQ + 超额 vs 主题基准篮三口径
- **不继承证据**：AI 主题的 IC 证据（t=3~7）不自动适用于新主题；"主题中心度泛化"
  假设由本观察检验

## 2. 执行节奏

每期（至少每周一次）：

```bash
.venv/bin/python scripts/theme_observation_scan.py            # 五主题扫描 + cohort 归档
.venv/bin/python scripts/theme_observation_scan.py --evaluate  # 结算到期 cohort（120 交易日后）
.venv/bin/python scripts/build_theme_universe.py              # 周度刷新主题篮 + 新成员 diff（L2 信号）
.venv/bin/python scripts/build_venture_universe.py --fts      # venture 三层底单（并行积累）
```

## 3. 预注册指标（每期记录）

| 指标 | 来源 | 说明 |
|---|---|---|
| 各主题 shortlist 数量 | `theme_observation_scan.py` 输出 | 连续 3 期零信号 = 主题配置审查触发 |
| 篮子新成员事件 | `data/theme_history/<theme>/` diff | 机构论点形成信号（L2） |
| 120d 纸面收益（cohort 结算） | `data/theme_cohorts.csv` | 每 theme × list_type 独立结算 |
| 超额 vs 主题基准篮 | cohort 结算时的 basket 中位 | 主题自身的 β 之外才是主题选择能力 |

## 4. 预注册观察问题（防事后合理化）

- **Q1 量子纯度**：量子 cohort 的收益是否被 NVDA/MSFT 主导？（若是，考虑纯净度过滤或双主题成员记账）
- **Q2 生物研究分刻度**：biotech 的研究分分布是否稳定到可重新校准 low_value 门槛（当前 3.0）
- **Q3 主题中心度泛化**：theme_link 与 120d 纸面收益的截面 IC 是否为正（AI 主题里 etf_consensus 是最强信号 t=11~13，新主题待检验）
- **Q4 单 ETF 主题区分度**：稀土/量子（saturation=1）的排序能力是否只来自 market_link/backlog/价值质量——可接受但需记录

## 5. 审查触发条件

1. 任意主题连续 3 期零信号（含 no_signal 归档）
2. 主题篮子源 ETF 页面结构变化导致持仓抓取失败
3. 单主题成熟 cohort 均值 120d < -20%（配置校准问题的信号）
4. 主题基准篮数据缺失（NLR/QTUM 等 bars 断供）

**未触发审查条件**：某期纸面收益为负、某主题当期空仓、主题间收益差异大。

## 6. 进入实盘（P1）的前置条件（预注册，不提前松动）

1. **≥2 个季度**的成熟 cohort 数据（约 26 个周度 cohort × 120d 结算）
2. 主题 cohort 均值 120d 超额 **vs 主题基准篮 > 0**（主题 β 之外的选股能力）
3. 校准积压项（docs/multi_theme_expansion.md §阶段2 校准清单）中影响评价的项目已解决
4. 与 AI 试点一样按试点协议分级（P1 起步 25%×该主题目标配额），不跳级

## 7. 与 AI 观察、Venture Sleeve 的关系

- AI 双风格：docs/two_style_observation_protocol.md（已运行）
- 五主题：本协议（P0 纸面，2026-09-28 起）
- Venture Sleeve：docs/multi_theme_expansion.md §6（底单三层漏斗已建成；扫描配置在五主题
  机制接入后构建，**同样以 P0 纸面进入观察**——不与主题观察串联阻塞，三套观察流并行，
  各自用自己的 cohort 数据申请晋级）
