> **已被取代：** 模块化重构完成后请阅读 `docs/work_handoff_after_pr23_20261008.md`。本文保留为 PR #8 时点的历史交接记录，不再作为当前工作计划。\n\n# 工作交接：PR #8 后的最小必要重构与选股研究路线

日期：2026-10-06  
PR #8 代码基线：`9e730a5a319f0e38ba9e4dbd61f1703449996eda`  
交接文档加入后的当前 `main` HEAD：`b9baaa0154d7d6b5a420052258060eb71401f805`  
当前测试基线：**276 tests / OK**  
项目：`AT2018cow/us-ai-stock-scanner`

> 本文是后续新对话的工作交接入口。继续开发前先阅读 `AGENTS.md`、本文、`docs/modular_refactoring_plan_20261003.md` 和 `docs/refactor_baseline_protocol.md`。如本文与更早的完整模块化计划在优先级上冲突，以本文的“最小必要重构 + 尽快回到 alpha 研究”路线为当前决策。

---

## 1. 当前首要目标与项目边界

用户的首要目标是：**提高选股质量并最终赚钱**。

模块化重构不是目标本身。当前只做能够明显提高研究可信度、减少 scanner / backtest 漂移、加快 alpha 迭代的最小重构。

### 明确的产品边界

本项目本质上是：

- 选股程序；
- 历史研究 / 回测工具；
- 人工交易参考报告；
- theme / venture 的 paper observation 工具。

本项目当前**不是**：

- 自动交易系统；
- 券商账户管理系统；
- 持仓/订单状态机；
- 自动止损执行器；
- 真实账户 NAV 模拟器。

`trade_plan` 的历史文件名保留，但输出只是给不想阅读完整扫描报告的用户提供快速人工参考，不是交易指令。

### ETF 原则

ETF holdings 只是快速构建**当前选股底单**和主题桶的捷径，不是策略本身，也不是历史数据依赖。

不要为了回测或 walk-forward 去建设历史 ETF constituent reconstruction。历史 replay 使用 fixed-current candidate pool；PIT 隔离主要作用于市场/财务事实、标签和参数选择，而不是 ETF membership archaeology。

---

## 2. 当前主分支状态

PR #8 已合并：

- PR：#8 `Unify pure accounting derivations across scanner and replay`
- merge commit：`9e730a5a319f0e38ba9e4dbd61f1703449996eda`
- GitHub Actions：**276 tests / OK**
- 当前：
  - `scanner.py` 约 6,408 行；
  - `backtest.py` 约 4,147 行。

最小重构已经开始形成真实模块边界：

```text
src/ai_value_scanner/
├── config.py
├── fundamentals/
│   ├── __init__.py
│   └── accounting.py
├── scanner.py
└── backtest.py
```

完整模块化仍是长期路线图，不是当前短期目标。

---

## 3. 已完成的 PR #1–#8

### PR #1 — execution/reference safety

`Fix execution safety guards before modular refactor`

主要关闭运行失败传播、双风格报告配对和 reference-plan 安全问题。后续又明确项目不是自动交易系统，因此账户/订单闭环不属于当前 correctness 要求。

### PR #2 — true OOS walk-forward

`Add true OOS walk-forward tuning and lock research-only execution semantics`

关键结果：

- tuner 默认使用 anchored chronological walk-forward；
- 训练数据在 held-out 边界做 forward-label purge；
- promotion 不再默认发生；
- pooled selection 是 research-only；
- promotion 只能显式执行且只能写回同一 strategy style。

### PR #3 — config contract + market provenance

`Fix E02 config contracts and D03 market-data provenance`

完成：

- `config_schema_version=1`；
- 显式 `strategy_style`；
- config fail-fast 校验；
- scanner/backtest hard/soft partition 不再靠阈值名猜 style；
- Alpaca source/feed/data-asof/cache-age/degradation provenance；
- stale cache fallback 不再刷新 mtime 伪装 fresh。

### PR #4 — pre-E01 correctness closure

`Close pre-E01 theme evaluation and runner semantics`

完成：

- daily theme/venture scan = observation；
- Friday = weekly paper cohort first-freeze；
- 120d absolute / vs QQQ / vs theme basket 评价；
- `unresolved_price`；
- `America/New_York` runner calendar；
- 实际 runner summary log。

### PR #5 — reproducible E01 baseline

`Add reproducible post-correctness baseline gate for E01`

加入：

- `scripts/refactor_baseline.py capture|compare`；
- frozen watchlist + watchlist-history；
- risk_off/risk_on 固定历史 replay；
- 小型 anchored walk-forward tuner smoke；
- calculation characterization tests。

正式 baseline：

```text
evidence/baselines/pre_e01_f39d06f/
```

### PR #6 — portable baseline paths

`Make E01 baseline comparison portable across evidence paths`

输入文件位置不是 identity；输入内容仍由 SHA256 严格比较。canonical evidence 可以直接从 `evidence/` 使用。

### PR #7 — config extraction

`Extract canonical config module without behavior changes`

完成：

```text
ai_value_scanner/config.py
├── ScanConfig
├── defaults
├── validation
├── load_config
└── resolve_channel_profile
```

`scanner.py` 保留 compatibility re-export；`backtest.py` 直接依赖 canonical config module。

同一数据状态下 old/new replay 已证明行为等价。

### PR #8 — shared pure accounting core

`Unify pure accounting derivations across scanner and replay`

完成：

```text
ai_value_scanner/fundamentals/accounting.py
├── safe_yoy
├── clamp01
├── fundamental_quality_score_from_metrics
├── compute_adjusted_metrics
└── derive_accounting_metrics
```

共享派生内容包括：

- adjusted NI / EBIT / EBITDA；
- FCF；
- total debt / net debt；
- YoY；
- interest coverage；
- net debt / EBITDA；
- current ratio；
- current-debt ratio + inference；
- OCF / adjusted net income；
- accrual ratio；
- receivables/inventory growth gap；
- fundamental-quality score。

scanner / replay 已删除对应重复实现并调用共享 core。

---

## 4. PR #8 审查结论

结论：**PR #8 可以接受，合并后状态健康，可以继续下一步。**

检查结果：

- 主分支 CI：276 tests / OK；
- `safe_yoy` 不再在 scanner/backtest 内重复定义；
- `fundamental_quality_score_from_metrics` 只有 canonical accounting 实现；
- replay 原来的 `compute_adjusted_metrics` 重复实现已经删除；
- scanner 和 backtest 都依赖 `fundamentals/accounting.py`；
- 新增独立 golden-value tests，不只是“新代码等于旧代码”的同源测试；
- PR merge 记录已经包含 same-data-state old/new replay 验证，events / benchmarks / summary byte-identical。

### PR #8 刻意没有处理的差异

当前 scanner 与 replay 在 non-recurring adjustment cap 语义上仍有一个**历史差异**：

- scanner：在进入 shared adjustment arithmetic 前，当前路径会对 addback **和 gain** 做 revenue cap；
- replay：shared `compute_adjusted_metrics(..., cap_ratio=...)` 保留原有行为，只 cap addback。

PR #8 为保持行为中性，没有顺手统一这项语义。

**后续不能在机械重构 PR 中偷偷改它。**  
如要统一，必须单独作为 correctness / accounting-policy 决策：

1. 先明确业务/会计意图；
2. 写独立 golden tests；
3. 量化历史影响；
4. 再决定 scanner 或 replay 哪一方改变。

---

## 5. 为什么 baseline 不能机械地跨天比较

PR #7 验证期间发现过一次重要现象：

- risk_off old/new 全窗口保持一致；
- risk_on 对历史 baseline manifest 出现 mismatch；
- 排查后发现 GOOGL 新 SEC filing 导致 companyfacts 更新；
- 新事实改变了大量 historical per-date 特征；
- baseline 捕获时的活数据状态已经无法原样恢复。

因此：

> **跨天 baseline hash mismatch 不等价于代码回归。**

以后 E01 的验证必须分成两层。

### 层 1：长期 canonical baseline

用于冻结：

- config hash；
- frozen watchlist / history hash；
- replay window；
- horizons；
- list types；
- rebalance；
- tuner settings；
- output contracts。

路径：

```text
evidence/baselines/pre_e01_f39d06f/
```

### 层 2：同一数据状态 old/new 背靠背

对机械迁移最重要。

流程：

1. 在同一个 SEC/cache/data 状态下运行 old；
2. 不刷新数据；
3. checkout / run new；
4. 比较 accounting/features/events/summary；
5. 必要时逐字段比较。

这才真正隔离：

```text
代码变化
vs
外部 EDGAR / market-data 更新
```

下一轮 fundamentals / features 重构必须使用这一方法。

---

# 6. 当前决定：只完成“最小必要重构”

完整模块化计划仍保留，但当前不打算依次完成 data/reporting/workflow 等所有拆分。

### 最小重构的 stop condition

当 scanner 和 historical replay 已经共享：

```text
config
  ↓
fact / period reconstruction / PIT rules
  ↓
accounting
  ↓
features
  ↓
scoring / selection
```

之后**停止结构重构**，立即转回 alpha 研究。

不因为“已经重构一半”而继续拆：

- reporting；
- workflows；
- CLI；
- daily runner；
- Alpaca/SEC client；
- cache；
- theme tooling；

除非这些东西后来实际阻碍研究。

---

# 7. 下一步：PR #9 — fact reconstruction / TTM / PIT

这是下一对话应优先开展的工作。

但不要把它做成“大一统 fundamentals PR”。风险比 PR #8 高，建议按纯函数边界拆开。

## 7.1 目标

统一“事实已经从 SEC JSON 中解析出来以后，如何保留期间/披露版本并构造可用财务期间”。

重点包括：

- flow fact period representation；
- quarter reconstruction；
- annual / YTD / discrete-quarter 关系；
- TTM reconstruction；
- latest TTM + year-ago TTM；
- level fact current + year-ago；
- PIT `asof` 可见性；
- filing / accession / period-end 信息保留。

最终希望 scanner 和 replay 不再各自维护不同的“期间解释算法”。

## 7.2 明确 out-of-scope

PR #9 不应顺手移动：

- `SecClient`；
- HTTP session；
- retry / rate limiter；
- submissions/companyfacts cache；
- accession refresh policy；
- Alpaca；
- market-data cache；
- reporting；
- scoring；
- strategy filters。

数据获取和“拿到 JSON 后如何解释事实”必须分开。

## 7.3 当前需要重点梳理的函数

scanner 侧需要重点阅读：

- `_reconstruct_flow_periods`
- `pick_latest_and_prev_ttm`
- 相关 level / year-ago helpers
- `load_one_fundamental` 中从 raw facts 到 period values 的部分

backtest 侧需要重点阅读：

- `extract_metric_points`
- `build_flow_ttm_or_annual_series`
- `latest_and_prev_asof`
- `load_symbol_fundamental_pti`
- `build_cross_section_asof` 中 period/PIT adapter 部分

**不要因为名字相似就直接合并。** scanner 是 current-view；historical replay 有 `asof` visibility，因此必须先建共同事实模型，再让两边以不同 asof 调共享算法。

## 7.4 推荐模块形态

可考虑：

```text
fundamentals/
├── accounting.py          # 已完成
├── facts.py               # typed fact/period records
└── reconstruction.py      # quarter / TTM / year-ago / PIT selection
```

避免创建一个通用 `utils.py`。

## 7.5 PR #9 推荐拆法

如果单 PR 过大，优先拆：

### PR #9A — shared fact/period data structures + pure reconstruction

只把“给定 fact rows 如何重建 quarter/TTM/year-ago”做成纯函数。

不改 SEC client，不改 cache。

### PR #9B — scanner/replay adapters

scanner/current path 和 historical replay 都转为调用 shared reconstruction。

这一步才真正删除旧重复实现。

是否拆成 9A/9B，视 diff 大小决定；不要为了 PR 编号强行一次完成。

---

# 8. PR #9 的正确性要求

这是高风险迁移，要求高于 PR #7/#8。

至少需要：

### 8.1 独立 synthetic golden tests

必须覆盖：

- 标准季度；
- YTD facts 转 discrete quarter；
- 年报 closure；
- 52/53-week fiscal year；
- 缺季度；
- duplicate facts / amended filings；
- 同 period 不同 accession；
- 同 filing date 不同 accession；
- year-ago 320–410 天窗口；
- 没有合法同比基数时返回 missing，而不是拿次新值冒充 YoY。

### 8.2 PIT tests

构造：

```text
period end
filing date
accession
asof A
asof B
```

验证：

- A 时不可见的事实绝不能进入 A；
- B 时新 accession 可以覆盖旧版本；
- historical replay 不使用未来重述；
- same-day accession change 仍按 accession 状态处理。

### 8.3 scanner/replay parity

给定**同一组可见 fact records**和同一 asof：

- revenue TTM；
- NI TTM；
- EBIT；
- OCF；
- D&A；
- year-ago values；
- derived accounting inputs

应一致。

### 8.4 same-data-state replay

至少：

- risk_off 一个固定短窗口；
- risk_on 一个固定短窗口；

old/new 背靠背，不刷新 SEC/cache。

优先比较：

- reconstructed raw fundamental fields；
- accounting fields；
- events；
- summary。

### 8.5 full tests

不能低于当前 **276 tests**，并应增加新的 reconstruction/PIT golden tests。

---

# 9. PR #9 后的最小重构路线

## 下一阶段：shared features

PR #9 后优先统一真正影响选股的 feature calculations。

候选范围：

- AI-link score；
- valuation / valuation percentile；
- industry-relative valuation；
- historical valuation percentile；
- price trend；
- momentum；
- range / drawdown；
- liquidity/slippage-derived features；
- normalization。

目标：

```text
scanner ─┐
         ├── shared features
replay  ─┘
```

不要同时拆 reporting/workflow。

## 再下一阶段：scoring / selection

统一：

- hard vs soft gates；
- composite score；
- score weights；
- triage；
- channel-specific scoring；
- ranking；
- top-N；
- dedupe / caps；
- research_pool semantics。

如果 features 完成后重复已经很少，可以只抽 scoring；不要为了“架构完整”机械拆所有 selection functions。

---

# 10. 重构停止条件

满足以下条件后立即停止 E01：

1. config 已共享 —— **已完成 PR #7**；
2. pure accounting 已共享 —— **已完成 PR #8**；
3. fact/TTM/PIT reconstruction 已共享；
4. features 已共享；
5. scoring/selection 不再存在会导致 scanner/replay 算法漂移的双实现。

之后进入 alpha 研究。

**不要继续优先做完整 data/http/cache/reporting/workflow 模块化。**

---

# 11. 最小重构完成后的 alpha 研究顺序

用户的首要目标是选股赚钱。完成最小重构后，主要工作应切回策略证据。

## 11.1 第一优先级：为什么 risk_on 明显强于 risk_off

基线历史 replay 已显示 risk_on 在部分 list / 120d excess 上明显优于 risk_off。

需要做 attribution：

- 哪些 gates 造成差异；
- momentum/trend 是否是主要来源；
- quality gate 是否贡献 alpha；
- valuation constraints 是增益还是拖累；
- AI-link 是否真正提供增量；
- sector concentration；
- 是否靠少数 mega winners。

## 11.2 feature ablation

固定 OOS framework：

```text
full model
- momentum
- quality
- valuation percentile
- AI-link
- balance-sheet gates
...
```

比较 held-out performance，不用 pooled in-sample 结果决定结论。

## 11.3 ranking monotonicity

比“过不过 filter”更重要。

研究：

- score decile / quintile future returns；
- rank IC；
- top-k excess；
- low_value / momentum / research_pool 内部 monotonicity；
- 不同 channel 是否能共用 score scale。

## 11.4 regime dependence

按市场环境拆：

- QQQ > / < SMA200；
- bull / bear；
- volatility；
- rate regime；
- sector regime。

目标是判断风险开关是否真的提高 OOS，而不是继续凭经验增加 gate。

## 11.5 false-positive analysis

系统化研究历史高分失败样本：

- valuation trap；
- earnings deterioration；
- dilution；
- leverage；
- hype / AI narrative；
- cyclical peak；
- post-earnings gap；
- momentum exhaustion。

优先找**事前可观察**的共同特征。

## 11.6 最后才重新大规模调参 / promote

只有 attribution / ablation / OOS robustness 有充分证据后，再跑更大 candidate sweep。

不要因为某次 baseline replay 看起来更好就直接修改生产配置。

---

# 12. 已知非阻塞项 / 不应误开项目

以下项目不要阻塞当前最小重构：

### R01 / R02

fixed-current candidate pool + pre-snapshot union 是项目明确接受的历史 universe approximation。

不要做历史 ETF holdings reconstruction。

### R05

non-overlapping drawdown 是 sampling diagnostic，不是账户 NAV。

本项目当前不需要真实账户 simulator。

### T04

theme 仍继承部分 AI assumptions，需要未来研究校准，但 theme 是 P0 paper，不阻塞 AI 主模型最小重构。

### E04

missing / neutral-score semantics 仍可研究，但机械重构阶段应先冻结现状，不顺手改变。

### E05

IEX liquidity 是研究刻度，不是“真实账户可成交规模”。

### trade plan / live pilot

全部是人工参考/研究协议，不要重新把项目扩张成自动执行系统。

---

# 13. 下一对话的推荐起手动作

新对话建议直接说明：

> 阅读 `AGENTS.md` 和 `docs/work_handoff_after_pr8_20261006.md`。  
> 当前 main 是 PR #8 后基线。继续最小必要重构，先审查并设计 PR #9 的 fact reconstruction / TTM / PIT 共享层；不要进行完整 data/reporting/workflow 模块化，也不要改变策略参数。

然后：

1. 确认最新 `main` 没有新提交；
2. 重新阅读 scanner/backtest 期间重建函数；
3. 先列出 current-vs-PIT 的语义矩阵；
4. 决定 PR #9 是否拆为 9A/9B；
5. 先写 independent reconstruction golden tests；
6. 再迁代码；
7. full CI；
8. same-data-state old/new 背靠背验证。

---

# 14. 当前关键文件

```text
AGENTS.md
docs/design_and_calculation_review_20261003.md
docs/modular_refactoring_plan_20261003.md
docs/refactor_baseline_protocol.md
docs/theme_observation_protocol.md

evidence/baselines/pre_e01_f39d06f/

src/ai_value_scanner/config.py
src/ai_value_scanner/fundamentals/accounting.py
src/ai_value_scanner/scanner.py
src/ai_value_scanner/backtest.py

tests/test_config_validation.py
tests/test_accounting_core.py
tests/test_refactor_characterization.py
tests/test_review_p0_fixes.py
```

---

## 最终方向

当前工程工作的最终目的不是“把 monolith 拆得漂亮”，而是：

> **让历史研究和今天的实际选股使用同一套财务事实解释、同一套 accounting、同一套 features、同一套 scoring，从而提高 alpha 研究可信度。**

完成这个最小目标后，应停止架构工作，把主要精力重新放到：

> **哪些信号真正能稳定地产生样本外超额收益。**
