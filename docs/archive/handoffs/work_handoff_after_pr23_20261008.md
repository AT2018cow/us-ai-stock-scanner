# 工作交接：PR #23 后结束模块化重构，转入选股能力优化

日期：2026-10-08  
PR #22 合并后的代码基线：`f80d8d735be343c7f6360f3af9ec4adeff631ae7`  
PR #23：closure / handoff，仅文档与审计收尾  
PR #22 合并后 GitHub Actions：**367 tests / OK**  
PR #23 closure CI：**374 tests / OK**  
项目：`AT2018cow/us-ai-stock-scanner`

> **本文取代 `docs/work_handoff_after_pr8_20261006.md`，作为后续工作的主交接入口。**
>
> 当前决定非常明确：**模块化重构到 PR #23 为止。除非发现真实 correctness bug 或某个边界直接阻碍 alpha 研究，否则不再继续拆 scanner/backtest，不再为了“架构更漂亮”新增重构 PR。下一阶段的主目标是提高选股能力、样本外超额收益和研究可信度。**

---

## 1. 下一阶段唯一主目标

接下来的工作重点是：

> **验证哪些信号真的能稳定提高样本外选股表现，并据此优化 risk_on / risk_off、各 list type、各 channel 的排序与筛选。**

模块化已经完成到足以支持这一目标的程度。未来的工程改动必须服务于以下至少一项：

1. 提高 scanner / replay / tuner 的研究一致性；
2. 提高 OOS 评价可信度；
3. 提高实验速度；
4. 提高选股效果；
5. 修复真实 correctness 问题。

**不再把“继续拆模块”本身当作目标。**

项目边界继续保持：

- 选股；
- 历史研究 / 回放；
- 人工交易参考；
- theme / venture paper observation。

当前仍然**不是**：

- 自动交易系统；
- 券商账户状态机；
- 真实账户 NAV 模拟器；
- 自动下单 / 自动止损系统。

---

# 2. PR #22 合并后的最终架构

当前主要代码边界已经形成：

```text
src/ai_value_scanner/
├── config.py
│
├── fundamentals/
│   ├── accounting.py
│   ├── facts.py
│   ├── reconstruction.py
│   └── shares.py
│
├── features/
│   ├── ai_link.py
│   ├── derived.py
│   ├── peer_valuation.py
│   ├── price.py
│   └── valuation.py
│
├── strategy/
│   ├── filtering.py
│   ├── research.py
│   ├── rules.py
│   ├── scoring.py
│   └── selection.py
│
├── evaluation/
│   └── backtest.py
│
├── reporting/
│   ├── scan.py
│   └── backtest.py
│
├── validation/
│   └── snapshots.py
│
├── scanner.py
└── backtest.py
```

### 2.1 模块职责

**`config.py`**

- runtime config schema；
- strategy style；
- defaults；
- type/range/cross-field validation；
- channel-profile resolution。

**`fundamentals/`**

- SEC fact typed records；
- filing/PIT visibility；
- quarter / YTD / annual / TTM reconstruction；
- year-ago selection；
- accounting derivation；
- share-count freshness / unit reconciliation。

**`features/`**

- historical valuation percentile；
- peer valuation；
- AI-link；
- price/range/momentum/liquidity；
- expectation/cycle/slippage derived features。

**`strategy/`**

- hard/soft filtering；
- filter rule definitions；
- normalization/scoring；
- channel/group caps/top-N/dedupe；
- research assessment；
- triage。

**`evaluation/`**

- forward-return labels；
- event evaluation；
- benchmark comparison；
- delist assumption；
- non-overlapping sampling diagnostic；
- aggregate / segment summaries；
- signal diagnostics。

**`reporting/`**

- scanner output paths / atomic CSV / markdown；
- backtest output paths / markdown。

**`validation/`**

- deterministic pre-strategy feature snapshots；
- fast offline strategy gate。

**`scanner.py` / `backtest.py`**

继续保留：

- data/client/cache adapters；
- current-view / historical-asof adapter orchestration；
- CLI / workflow entry；
- compatibility re-exports。

它们仍然很大，但现在主要是 orchestration 与 adapter 容器。**不要为了继续缩短文件而再拆。**

### 2.2 依赖方向审查

PR #22 合并后检查：

- `fundamentals/`
- `features/`
- `strategy/`
- `evaluation/`
- `reporting/`
- `validation/`

没有从 `src/` 反向 import `ai_value_scanner.scanner` 或 `ai_value_scanner.backtest`。

因此 canonical core → workflow facade 的反向依赖已经清除。

兼容性仍允许外部旧代码：

```python
from ai_value_scanner.scanner import ...
from ai_value_scanner.backtest import ...
```

但新代码应该优先从 canonical module import。

---

# 3. 23 个 PR 做了什么

下面按“correctness / evidence / modularization / validation / closure”顺序记录。后续不要重新阅读二十多个 PR 才理解系统。

## PR #1 — Fix execution safety guards before modular refactor
Merge: `21967aca`

类型：**correctness / execution safety**

完成：

- QQQ bear-regime breaker fail-closed；
- trade-plan reference 需要新鲜且 style 匹配的双报告；
- daily runner 不再默认每天产生 trade plan；
- tuner promotion 变为显式且 style-scoped；
- parsed fundamentals cache 绑定 SEC accession state；
- theme/venture child failure 正确向上返回非零状态；
- 建立 GitHub Actions unittest。

意义：先阻止运行层错误污染后续研究。

---

## PR #2 — Add true OOS walk-forward tuning and lock research-only execution semantics
Merge: `7e6387dd`

类型：**research correctness**

完成：

- tuner 默认 anchored chronological walk-forward；
- 2023→2024、2023+2024→2025、2023+2024+2025→2026YTD；
- forward-label purge，防止 60d/120d 标签跨入 held-out；
- pooled mode 只用于研究，不可直接 promote；
- promotion 只在最终 held-out pass 后显式执行；
- 明确项目是 research / selection 工具，不是自动交易系统。

意义：这是后续选股优化必须继续遵守的 OOS 纪律。

---

## PR #3 — Fix E02 config contracts and D03 market-data provenance
Merge: `6b21299e`

类型：**correctness / config contract**

完成：

- `config_schema_version=1`；
- 显式 `strategy_style`；
- unknown config keys fail-fast；
- hard/soft partition 不再通过阈值名猜 style；
- scanner report 输出 style provenance；
- Alpaca source/feed/data-asof/cache-age/degradation provenance；
- stale cache 不再伪装 fresh。

意义：后续实验必须明确知道“用了什么配置和什么数据状态”。

---

## PR #4 — Close pre-E01 theme evaluation and runner semantics
Merge: `407cd879`

类型：**paper-evaluation correctness**

完成：

- daily observation 与 weekly frozen cohort 分离；
- first-freeze-wins；
- 120d absolute / QQQ / theme benchmark 评价；
- unresolved-price 状态；
- runner calendar / summary semantics 收口。

意义：清理 theme/venture 研究噪声，不让它们阻塞主 AI 选股研究。

---

## PR #5 — Add reproducible post-correctness baseline gate for E01
Merge: `f39d06fe`

类型：**evidence / baseline infrastructure**

完成：

- `scripts/refactor_baseline.py capture|compare`；
- frozen watchlist + history；
- risk_off / risk_on replay contract；
- calculation characterization tests；
- deterministic artifact manifest。

Canonical evidence：

```text
evidence/baselines/pre_e01_f39d06f/
```

意义：建立“机械重构不能随意改变行为”的初始基线。

---

## PR #6 — Make E01 baseline comparison portable across evidence paths
Merge: `66812a76`

类型：**evidence tooling**

完成：

- frozen input 文件路径只作为 provenance；
- input identity 继续由 SHA256 严格约束；
- evidence 可搬到 canonical evidence 目录而不产生假 mismatch。

---

## PR #7 — Extract canonical config module without behavior changes
Merge: `55f746b6`

类型：**modularization**

建立：

```text
ai_value_scanner/config.py
```

scanner 保留兼容 re-export；backtest 直接依赖 canonical config。

---

## PR #8 — Unify pure accounting derivations across scanner and replay
Merge: `9e730a5a`

类型：**modularization**

建立：

```text
fundamentals/accounting.py
```

共享：

- adjusted NI / EBIT / EBITDA；
- FCF；
- debt/net debt；
- YoY；
- coverage/leverage；
- current ratio；
- OCF/NI；
- accrual；
- receivable/inventory gap；
- fundamental quality。

### 仍然存在的已知差异

scanner 当前路径历史上会在进入 shared arithmetic 前同时 cap non-recurring addback **和 gain**；replay 通过 `compute_adjusted_metrics(cap_ratio=...)` 保留原来的 cap 语义。

这是 PR #8 明确保留的历史 policy 差异，直到 PR #23 仍存在。

**下一阶段如要统一，必须作为 accounting-policy / correctness 实验独立处理，不能夹在 alpha 调参里偷偷改变。**

---

## PR #9 — Add shared fact and reconstruction core
Merge: `4c68a4cf`

类型：**fundamental semantic core**

建立：

```text
fundamentals/facts.py
fundamentals/reconstruction.py
```

完成：

- typed FactRecord；
- period end / filed / accession / form / tag priority；
- quarter/YTD/annual/TTM reconstruction；
- current-view / PIT cutoff；
- 320–410 day year-ago window；
- amendment/revision semantics；
- independent synthetic golden tests。

生产 adapter 尚未迁移，这是有意的 9A。

---

## PR #10 — Wire scanner and replay to shared fundamental reconstruction
Merge: `7f0bfa5f`

类型：**modularization + correctness**

scanner / replay 都转入 shared reconstruction。

重要 correctness 变化：

- historical replay 不再受未来事实影响；
- amendments/restatements 从 filing date 起生效；
- level YoY 必须使用真实 year-ago period；
- missing filing provenance 不进入 PIT；
- parsed-fund cache version bump。

意义：这是 scanner/replay 财务事实解释一致性的核心 PR。

---

## PR #11 — Record PR10 replay gate audit manifest
Merge: `72ec4371`

类型：**audit-only**

记录：

- exact base/head/merge commits；
- replay gate coverage；
- 哪些原始 artifacts/cache 没有归档；
- 不制造不存在的 hash。

无生产行为变化。

---

## PR #12 — Extract shared valuation and AI-link feature primitives
Merge: `ae0d481d`

类型：**features modularization**

建立：

```text
features/valuation.py
features/ai_link.py
```

共享：

- historical own valuation percentile；
- lookup helpers；
- vectorized safe_divide；
- ETF consensus；
- market link；
- config-weighted AI-link。

same-data-state gate：zero drift。

---

## PR #13 — Unify price history features across scanner and replay
Merge: `87dfded2`

类型：**features modularization + correctness**

建立：

```text
features/price.py
```

共享：

- drawdown/range；
- SMA200；
- days below SMA200；
- 20d/60d returns；
- 60d vol；
- ADV20。

correctness fixes：

1. SMA200 只有 ≥200 closes 才有效；
2. replay `price_lookback_days` 改为 calendar-day contract，而不是 trading-row count。

---

## PR #14 — Extract shared expectation, cycle and slippage feature core
Merge: `b4e045b3`

类型：**features modularization**

建立：

```text
features/derived.py
```

共享：

- expectation_proxy；
- cycle_proxy；
- adv_participation；
- estimated_slippage_bps。

same-data-state gate：zero drift。

---

## PR #15 — Unify share-count integrity across scanner and replay
Merge: `add3454b`

类型：**fundamental correctness**

建立：

```text
fundamentals/shares.py
```

共享：

- EPS + NI same-period share-unit reconciliation；
- ~1,000x / ~1,000,000x unit correction；
- share-count >400 days stale protection；
- historical PIT share integrity；
- `shares_asof_end` / `shares_stale` diagnostics。

实际历史影响包括 BIDU/BKR/MBLY 等 share-integrity 变化；benchmark 不受影响，diff 已因果归因。

---

## PR #16 — Unify SIC peer valuation across scanner and replay
Merge: `158fbb43`

类型：**features modularization + correctness**

建立：

```text
features/peer_valuation.py
```

canonical cohort：

- metric-specific P/S、P/E；
- finite + positive；
- non-null SIC；
- non-stale shares；
- peer median；
- cohort ≥5 才算 percentile；
- 小 cohort / invalid row 回退 0.5。

replay 从原来的宽松排名语义对齐 scanner。

---

## PR #17 — Add fast frozen feature-snapshot refactor gate
Merge: `10e8e66c`

类型：**validation performance infrastructure**

建立：

```text
validation/snapshots.py
scripts/fast_strategy_gate.py
```

支持：

- 只抓 6–12 个 representative asof；
- deterministic cross-section snapshots；
- manifest/hash；
- strategy 旧/新代码离线 A/B；
- 不访问 SEC/Alpaca；
- 不重建 PIT/price history；
- 不跑 forward-return backtest。

意义：之后 strategy 改动不再需要每个 PR 重跑数小时 historical replay。

---

## PR #18 — Extract shared scoring core
Merge: `0f772256`

类型：**strategy modularization**

建立：

```text
strategy/scoring.py
```

共享：

- robust normalization；
- component transforms；
- default weights；
- soft-pass contribution；
- PE cash-backing haircut；
- overvaluation penalty；
- deterioration penalty；
- composite score/sort。

zero-drift mechanical extraction。

---

## PR #19 — Unify filtering and selection strategy core
Merge: `d437eb76`

类型：**strategy modularization + correctness**

建立：

```text
strategy/filtering.py
strategy/selection.py
```

共享：

- hard/soft partition；
- filter execution；
- first-fail/near-miss diagnostics；
- sector/ETF caps；
- symbol/channel dedupe；
- per-channel/global top-N。

correctness fixes：

1. replay 以前漏掉 production sector/group caps；
2. replay low-value 以前漏掉 production research gate；
3. replay channel dedupe 对齐 scanner best-channel semantics。

这是最后一组重要 selection parity 修复。

---

## PR #20 — Extract shared strategy rules and research core
Merge: `c61b1582`

类型：**strategy modularization**

建立：

```text
strategy/rules.py
strategy/research.py
```

共享：

- filter-step builders；
- trend/momentum rules；
- professional metric policy；
- benchmark breaker；
- watchlist/channel/SIC masks；
- research assessment；
- low-value research gate；
- triage。

### PR #20 的已知机械迁移回归

抽取行范围过宽，把 reporting / CLI helper 误搬进 `strategy/research.py`。

这在 PR #21 完整修复。

---

## PR #21 — Restore scanner CLI wiring and extract reporting boundary
Merge: `3ca644f5`

类型：**correctness repair + reporting boundary**

建立：

```text
reporting/scan.py
```

修复：

- scanner `build_parser` 恢复；
- `run_scan()` reporting globals 显式 wiring；
- research module 只保留 research/triage；
- output path / atomic CSV / markdown/report logging 移入 reporting。

新增 workflow-global wiring tests，防止“import 正常但真实入口 NameError”。

---

## PR #22 — Extract backtest evaluation and reporting boundaries
Merge: `f80d8d73`

类型：**evaluation/reporting modularization**

建立：

```text
evaluation/backtest.py
reporting/backtest.py
```

共享/迁出：

- forward-return；
- label-end；
- event evaluation；
- delist assumption；
- non-overlapping diagnostic；
- aggregate / segment summary；
- signal diagnostics；
- output path；
- markdown report。

同时修正：

- `scripts/extract_weight_dataset.py` 不再依赖 backtest entry facade 的私有 evaluation helper；
- 保留 compatibility re-export。

合并后：**367 tests / OK**。

---

## PR #23 — Close modular refactor and hand off to stock-selection optimization

类型：**closure / documentation only**

目的：

- 正式结束本轮模块化；
- 记录最终架构与依赖边界；
- 汇总 PR #1–#23；
- 明确已知但非阻塞差异；
- 明确高效验证协议；
- 把下一阶段工作切到 stock-selection / alpha optimization。

**PR #23 不修改策略、features、fundamentals、evaluation、config 或 runtime behavior。**

---

# 4. 本轮重构真正改变了哪些业务语义

后续做 alpha 对比时不能把“PR #5 baseline”和“当前 main”简单视为纯架构等价，因为中间确实修过 correctness。

必须记住的主要 intentional changes：

1. PR #2：true anchored OOS + label purge；
2. PR #10：PIT facts / amendments / genuine year-ago reconstruction；
3. PR #13：true SMA200 + calendar-day lookback；
4. PR #15：share-unit reconciliation + stale shares；
5. PR #16：peer cohort eligibility + ≥5 percentile neutral fallback；
6. PR #19：replay group caps + low-value research gate + channel dedupe parity；
7. PR #21：scanner CLI/reporting wiring repair。

因此：

> **下一阶段的“当前策略 baseline”必须从 PR #22/PR #23 后的 main 重新建立。不要把 pre-E01 的收益数字直接作为当前策略性能基线。**

pre-E01 evidence 继续用于审计重构历史，不作为未来 alpha 优化的性能基准。

---

# 5. 当前验证协议：以后不要再做无必要的长 replay

PR #17 之后，验证必须按风险分层。

## 5.1 纯结构 / reporting / docs

使用：

- unit tests；
- golden / identity / workflow wiring tests。

**不跑历史 replay。**

## 5.2 strategy/scoring/filter/ranking 的机械改动

使用：

- unit/golden；
- existing frozen feature snapshots；
- `scripts/fast_strategy_gate.py`。

机械迁移要求 `FAST_GATE_MATCH`。

## 5.3 strategy 的有意优化

这里**不要求 MATCH**。

使用同一 snapshot 或同一 OOS dataset 做：

- old/new ranking；
- selected symbols；
- score distribution；
- channel/list-level diagnostics；
- forward OOS metrics。

重点是解释为什么更好，而不是证明“不变”。

## 5.4 feature / fundamental correctness

使用：

- synthetic golden；
- PIT visibility tests；
- targeted symbols；
- 少量 representative asof；
- 必要时短窗口 Medium gate。

只有影响范围大或出现无法解释的 drift 才升级。

## 5.5 Full historical replay

只在以下情况做：

- 大型 correctness checkpoint；
- final candidate promotion 前；
- 发现 targeted/Medium 无法解释的 broad drift。

**不要每个 PR 都跑。**

---

# 6. 已知但非阻塞项

这些问题已经知道，但它们不阻塞进入选股优化。

## 6.1 non-recurring adjustment cap policy 差异

如 PR #8 所述：

- scanner live path：历史上会预先 cap addback 和 gain；
- replay shared adjustment path：保留原有 `cap_ratio` policy。

这是目前最明确的 remaining scanner/replay accounting-policy difference。

处理方式：

- 不要在普通调参 PR 中顺手修；
- 若 attribution 显示它影响样本，应单独立项；
- 写 golden + impact study 后决定 canonical policy。

## 6.2 historical universe approximation

继续接受：

- fixed-current candidate pool；
- frozen/current watchlist；
- pre-snapshot union approximation。

**不要建设 historical ETF constituent archaeology。**

## 6.3 non-overlapping cumulative 不是账户 NAV

它是 sampling diagnostic。

不要把它解释为真实账户 equity curve / drawdown。

## 6.4 scanner.py / backtest.py 仍然大

这是接受的。

它们仍含：

- data-client adapter；
- cache/network；
- replay orchestration；
- CLI/workflow；
- compatibility facades。

除非这些内容直接阻碍 alpha 工作，否则**不继续拆**。

## 6.5 theme / venture

继续作为 paper observation。

不要让主题工具重构阻塞 AI stock-selection 主线。

---

# 7. 下一阶段：选股能力优化的推荐路线

下一阶段不要先“大规模调参”。先建立证据。

## Phase A — 建立当前策略 OOS baseline

以 PR #23 后 main 为唯一代码基线。

**必须区分两种证据：**固定现有配置跑多年 historical replay 得到的是 *current-config retrospective baseline*；它本身不保证该配置未在相同历史区间中被选择、调优或观察过，**不能仅因为按历史日期计算就标成 OOS**。只有严格采用 PR #2 的先前窗口选择参数、forward-label purge、后续窗口 held-out 评价，且 held-out 未被用于选型时，才能称为 *anchored OOS baseline*。两类结果应分别命名和保存，不能混在同一张“样本外”结论表里。

分别运行：

- risk_off；
- risk_on。

至少按以下维度保存：

- list_type：
  - low_value
  - momentum
  - industry_trend
  - research_pool
- channel：
  - core_ai
  - ai_enabler
  - ai_peripheral
- horizon：
  - 20d
  - 60d
  - 120d
- regime；
- calendar fold / year。

主要指标：

- n_events_total / valid；
- avg / median return；
- win rate；
- excess vs QQQ；
- non-overlapping cumulative diagnostic；
- top-N stability；
- sector concentration；
- selected-symbol concentration。

不要只看 aggregate average。

---

## Phase B — risk_on vs risk_off attribution

这是第一优先研究问题。

要回答：

1. risk_on 真正更强吗，还是被少数 mega winners 拉高？
2. 差异来自：
   - momentum；
   - trend；
   - valuation；
   - quality；
   - balance sheet；
   - AI-link；
   - research gate；
   - sector cap；
   - channel composition；
   的哪一项？
3. 不同 regime 下是否反转？

推荐输出：

```text
full risk_on
full risk_off
risk_on with one block removed
risk_off with one block removed
```

做 held-out attribution，不要用 pooled in-sample 结论决定生产配置。

---

## Phase C — feature ablation

固定 anchored OOS framework，依次测试：

- minus momentum；
- minus trend；
- minus valuation percentile；
- minus peer discount；
- minus AI-link；
- minus quality；
- minus leverage/balance-sheet；
- minus deterioration penalty；
- minus PE cash-backing haircut；
- minus research gate。

每个 ablation 至少看：

- total OOS excess；
- fold stability；
- list/channel split；
- top-N turnover；
- false-positive change。

---

## Phase D — ranking monotonicity

比继续增加硬 gate 更重要。

研究：

- score decile/quintile future return；
- rank IC；
- top-5 / top-10 / top-20；
- composite score 与未来 excess 的单调性；
- 每个 component 的单调性；
- low_value / momentum / industry_trend 是否需要独立 score scale。

如果高分不单调优于中低分，继续微调阈值没有意义。

---

## Phase E — false-positive / false-negative analysis

系统分析：

### 高分失败样本

标签：

- valuation trap；
- earnings deterioration；
- dilution；
- debt/leverage；
- cyclical peak；
- AI narrative/hype；
- post-earnings gap；
- momentum exhaustion；
- sector shock。

只使用**事前可观察信息**寻找共同特征。

### 被过滤但后来大涨的样本

检查：

- 哪个 first-fail；
- 是否 gate 太硬；
- 是否 neutral/missing semantics 过度惩罚；
- 是否 sector/group cap 截掉了真正赢家；
- 是否 research gate 过于保守。

这类分析往往比盲目扩大参数 sweep 更有价值。

---

## Phase F — 再做权重/阈值优化

只有 Phase A–E 有稳定证据后再做。

原则：

- risk_on / risk_off 分开；
- list_type 必要时分开；
- anchored chronological walk-forward；
- label purge；
- pooled 只做诊断；
- final held-out pass 才能考虑 promote；
- 不因为单一 2026YTD 表现好就 promote；
- 控制参数自由度，避免“搜索空间本身制造 alpha”。

已有：

```text
scripts/extract_weight_dataset.py
scripts/fast_strategy_gate.py
```

可以优先离线扫描 ranking/weights，不要每个候选都重建 PIT。

---

# 8. 下一阶段的推荐第一个任务

**不要再开架构 PR。**

建议第一个 alpha 任务：

> **建立 PR #23 后 risk_on vs risk_off 的 current OOS baseline，并做 list_type × channel × horizon × regime attribution。**

具体顺序：

1. 固定当前 main；
2. 使用现有 anchored walk-forward / replay infrastructure；
3. 输出两种 style 的 OOS summary；
4. 分拆 low_value / momentum / industry_trend / research_pool；
5. 分拆 channel；
6. 统计 top contributors / worst failures；
7. 检查是否依赖少数股票；
8. 再决定第一轮 ablation。

只有完成这一步，才知道最值得优化的是：

- filters；
- score weights；
- list-specific strategy；
- AI-link；
- valuation；
- momentum；
- research gate；
- regime switch。

### 第一轮交付契约（新对话可直接执行）

**入口与冻结规则**

1. 只有 PR #23 实际合并后，才从最新 `main` 固定新基线的完整 commit SHA。旧的 `f80d8d7` 是 PR #22 后基线，不能误写成 PR #23 merge SHA。
2. 开工先执行 `git status --short`、`git rev-parse HEAD`、`python -m unittest discover -s tests`；保留准确的 SHA 和测试结果。
3. 优先检查是否已有**与该 SHA/配置/输入哈希一致**的风险风格基线；若没有，再在相同冻结数据状态下一次性计算 risk_off/risk_on。冻结 `configs/config.risk_off.json`、`configs/config.risk_on.json`、当前 watchlist、watchlist-history、theme source、历史窗口、rebalance frequency、交易成本、entry/exit 模式及 `max_symbols`。记录 SEC/Alpaca cache/data-asof/provenance；关闭 latest-watchlist fallback。
4. 冻结 baseline **只需生成一次**并在后续假设实验中复用，不要每个权重/阈值候选重做全套 PIT。可复用 PR #17 snapshots 验证离线选股变化，但 snapshots 的 Fast Gate **不是前瞻收益或 OOS 有效性证明**。
5. `AGENTS.md` 是完整运行说明；`docs/refactor_baseline_protocol.md` 的 replay 命令可作为 CLI 示例，但它是 **pre-E01 结构对照协议**，不得把它的旧收益或旧 SHA 当作新策略 OOS 证据。

**必须保存的最小证据**

- `baseline_manifest.json`：完整 SHA、dirty 状态、两个配置 hash、冻结候选池与历史快照 hash、feature/schema 版本、行情 feed、cache provenance、研究起止日期、信号日范围、价格标签成熟度、OOS fold 和 purge 边界。
- `current_config_replay_summary`：当前固定参数的 retrospective 诊断；明确注明 **not automatically OOS**。
- `anchored_oos_fold_summary`：按先前训练窗口选型、后续 held-out 评价；每个 fold 明确 `train_end`、`test_start/end`、purged label 数、实际有效样本量及 20/60/120d 标签是否成熟。
- `selection_attribution`：按 `strategy_style × list_type × channel × horizon × regime × fold` 分组的选中数、可定价数、unpriced/no-signal、收益/excess vs QQQ、集中度和主要贡献/拖累股票；样本量太小时只报告描述统计，不做优胜宣称。
- `research_decision.md`：数据覆盖/偏差说明、最值得验证的 1–2 个机制、下一步 ablation 假设；**不修改生产参数、不自动 promote**。

这些是**建议的新阶段产物名称/契约**，不是声称仓库已经生成过这些文件。研究产物可先保存在 gitignored `outputs/`，再根据需要提交脱敏的 manifest/摘要作为 PR evidence，禁止编造缺失原始 artifact 的 hash。

**不能忽略的研究边界**

- historical universe 是 fixed-current pool / union approximation，存在 survivor/universe 偏差；ETF 成分及 watchlist 统计不自动变成历史 PIT 特征。
- Alpaca IEX 交易量只是部分市场成交的代理，美元流动性、ADV/slippage 不应直接理解为全市场真实成交额或可下单容量；更换 feed 会改变过滤口径，必须单独验证。
- 评价时分别报告无信号、unpriced、label 未成熟和 delist 假设；non-overlapping cumulative 只是取样诊断，**不是账户 NAV**。
- 对两种风格做**配对**比较：使用相同冻结候选池、日期、成本、benchmark 和成熟标签；检查差异是否由少数 mega-cap 股票或单个年份驱动，不因汇总收益高就马上调参。
- 如果数据不足以构造真正 held-out 的 anchored OOS，不要把 retrospective replay 冒称样本外；应明确标记证据等级和阻塞点。

**第一个优化 PR 的 Definition of Done：**上述 manifest、双风格 baseline、按层归因、风险与数据限制、下一实验假设齐备；生产配置不变。评估有效性后再决定是否做 feature ablation/weights 调整，而不是再开一个纯架构 PR。

---

# 9. 下一阶段 PR 规则

以后不再用“一个小函数一个 PR”的粒度。

建议：

### 一个 PR 可以包含

同一个研究假设下的：

- experiment script；
- diagnostic output；
- guarded config/code change；
- tests；
- evidence。

例如：

> “验证并改进 momentum component 的 OOS monotonicity”

可以是一个完整 PR，而不是拆成 4–5 个机械 PR。

### 只有以下情况单拆 correctness PR

- PIT/lookahead；
- accounting semantics；
- data freshness/provenance；
- scanner/replay parity；
- OOS leakage；
- runtime fail-closed。

---

# 10. 后续工作明确不要做什么

除非有新证据，不要：

- 再拆 scanner/backtest 只为了减行数；
- 建历史 ETF holdings reconstruction；
- 扩成自动交易系统；
- 建账户/order state machine；
- 把 non-overlapping diagnostic 包装成 NAV；
- pooled tuning 后直接 promote；
- 在同一个 PR 中偷偷改变 accounting policy；
- 每个 strategy 实验都跑完整多年 replay；
- 因为某个单一窗口收益更高就改 production config。

---

# 11. 后续新对话的起手说明

建议直接使用：

> 阅读 `AGENTS.md` 和 `docs/work_handoff_after_pr23_20261008.md`。  
> 模块化重构已在 PR #23 正式结束，不再继续拆架构。  
> 当前主目标是选股能力优化。先建立当前 risk_on / risk_off 的 anchored OOS baseline，并做 list_type × channel × horizon × regime attribution；不要修改生产参数，先产出证据。  
> 所有优化继续遵守 PR #2 的 OOS / label-purge / explicit-promotion 规则，并使用 PR #17 的 fast snapshot infrastructure 降低验证成本。

---

# 12. 最终结论

PR #1–#22 的工作解决了两类问题：

### Correctness

- execution safety；
- OOS leakage；
- config/style contract；
- data provenance；
- PIT reconstruction；
- share integrity；
- price-window semantics；
- peer cohort semantics；
- replay selection parity；
- CLI/workflow wiring。

### Architecture

scanner 与 historical replay 现在共享：

```text
config
  ↓
fact/PIT reconstruction
  ↓
accounting/share integrity
  ↓
features
  ↓
strategy rules/filtering/scoring/selection/research
  ↓
evaluation
  ↓
reporting
```

这已经足够支撑可信的 alpha 研究。

从 PR #23 起，评价工程工作的标准不再是：

> “模块是不是还能拆得更漂亮？”

而是：

> **“这项工作是否让我们更可靠、更快地判断哪些股票选择信号能产生样本外超额收益？”**

这是下一阶段的唯一主线。
