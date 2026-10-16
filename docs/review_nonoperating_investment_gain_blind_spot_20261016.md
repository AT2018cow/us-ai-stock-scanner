# Review 意见：非经营性投资利得污染 Quality 打分的系统性盲区（GOOG/Anthropic $99B 实证）

> 日期：2026-10-16 · 评审对象：2026-10-15 每日 MVP v2 报告（decision_date 2026-10-15）
> 发现人：报告评审（人工复核）· 状态：**待 architect 立项修复**，生产报告解读时需人工折扣
> 关联工作：PR #86（财报窗口/动量/拆股）之后发现的第 4 个盲区；前三者污染的是排序与展示，本项污染的是 **Quality 基本面打分本身**

---

## 1. 一句话结论

GOOG（Alphabet）2026 年 Q2 单季 **$99.0B 权益证券利得**（主要系 Anthropic 持仓重估）几乎被管线全额计入"经营质量"：
`net_margin 55.7% → strong`、`adjusted_net_income_yoy +114.7% → strong`，最终 **Quality A（0.79）/ confidence 0.95**。
三层既有防线（非经常性调整、PE 现金支撑修剪、OCF/NI·应计警报）**逐层失效**，且 confidence 0.95 给出了虚假确信。
在修复落地前，所有含巨额 `EquitySecuritiesFvNi*` 利得公司的 Quality 等级与确信度均不可直接采信。

---

## 2. 美元级证据（全部来自本仓库 SEC 缓存，可复现）

取数路径：`cache/facts_0001652044.json`（Alphabet CIK 1652044），us-gaap 口径，季度事实（duration ≈ 90d），`end == 2026-06-30`，10-Q。

| XBRL 标签 | Q2 2026 单季值 | 备注 |
|---|---|---|
| `EquitySecuritiesFvNiGainLoss` | **$99.031B** | 权益证券利得总额 |
| `EquitySecuritiesFvNiUnrealizedGainLoss` | $21.399B | 其中未实现部分 |
| `NonoperatingIncomeExpense` | $97.983B | 营业外收支净额，利得几乎全在此 |
| `NetIncomeLoss` | $112.193B | 去年同期 $28.196B，同比约 4 倍 |
| `OperatingIncomeLoss` | $40.770B | 干净的经营部分，不到净利的 4 成 |

即：**当季利润的约 88% 来自投资利得**。报告侧证据（`outputs/decisions/2026-10-15/risk_off/decisions.jsonl`，symbol=GOOG）：

- `net_margin = 0.55653` → `net_margin_strong`（positives）
- `adjusted_net_income_yoy = 1.147024` → `adjusted_net_income_yoy_strong`（positives）
- `operating_margin = 0.339925` → strong（干净的对照信号，未被利用）
- `fcf_margin = 0.119482` → strong（干净）
- Quality：score 0.791 / confidence 0.95 / grade A，无任何相关 risk 项
- `ocf_to_net_income` 与 `accrual_ratio`：**positives / risks / missing 三态全缺席**（静默缺失，见 §3.3）

对照组 MSFT（同为 Anthropic 持仓方，Q4 FY2026 确认约 $3.2B 利得）：`ocf_to_net_income = 1.3506 → strong`，
利得相对 $35B+ 级单季净利可忽略，系统评分正确。说明现有机制在小量级下工作，**遇到 $99B 量级直接穿透**。

---

## 3. 三层防线失效的精确机制（附代码位置）

### 3.1 `adjusted_net_income` 名存实亡

`src/ai_value_scanner/scanner.py:249-254`：

```python
NONRECURRING_GAIN_TAGS = [
    "GainLossOnDispositionOfAssets",
    "GainLossOnSaleOfBusiness",
    "GainLossOnSaleOfPropertyPlantEquipment",
    "GainLossOnSaleOfOtherAssets",
]
```

4 个标签全是**处置类**利得。`EquitySecuritiesFvNiGainLoss` 系（含未实现明细）不在集合中，
经 `accounting.py:111`（`_adjust(net_income, addback, gain)`）算出的 adjusted_net_income ≈ GAAP net income，
一美元都没剔。连带 `net_margin`（分母口径见 quality profitability 柱，30% 权重）与
`adjusted_net_income_yoy`（growth 柱，20% 权重）同步被污染。

### 3.2 `pe_cash_backing_haircut` 够不着

`src/ai_value_scanner/config.py:391`、`scanner.py:4234/4488/4546`：该 guard 只收缩**中位以上（便宜侧）**的
`pe_discount / pe_percentile_low / pe_hist_percentile_low`。其设计假设是"浮盈→显便宜"。
本案杀伤链是"浮盈→显能赚"（profitability + growth 柱），GOOG 的 PE 处于贵侧，haircut **零触发**。

### 3.3 OCF/NI 与应计警报静默缺失

该季度 OCF/NI 应在 0.3–0.4 区间（深度弱信号），应计比率应为大幅正值（弱信号），
两者都是现成的、不依赖新标签的天然警报。但如 §2 所示，两项指标未进入决策证据三态，
也没有 missing 提示。疑似 TTM OCF 重建缺口导致指标缺失且静默（`cache/facts_0001652044.json`
中 `NetCashProvidedByUsedInOperatingActivities` 季度序列止于 2026-03-31 即为旁证）。
**建议把"高净利率 + OCF/NI 缺失"本身列为强制复核条件，而非静默通过。**

---

## 4. 影响面评估

1. **存量报告**：2026-10-15 快照中 GOOG（雷达 #30）及任何含巨额 `EquitySecuritiesFvNi*` 利得的公司，
   Quality 分数/等级/确信度需人工下调一档解读；`adjusted_net_income_yoy` 与 `net_margin` 两项 strong 作废，
   以 `operating_margin`、`fcf_margin`、营收增速为准。
2. **前瞻风险**：Q3 财报（10 月底）中该浮盈可能反转（Anthropic 估值波动双向），TTM 将吞入巨额负数，
   GOOG Quality 分数下期可能断崖式下跌。财报落地前不建议依据当前分数行动。
3. **横向排查建议**：对全宇宙跑一遍"单季 `NonoperatingIncomeExpense / Revenue` 或
   `(NetIncome − OperatingCashFlow) / NetIncome` 超阈值"扫描，列出同类污染名单（MSFT 量级可忽略，可设阈值豁免）。

---

## 5. 修复方案建议（按优先级）

1. **P0 — 扩大 gain-strip 标签集**：`NONRECURRING_GAIN_TAGS`（或新增 `INVESTMENT_GAIN_TAGS`，走同一 cap 通道）
   纳入 `EquitySecuritiesFvNiGainLoss`、`EquitySecuritiesFvNiUnrealizedGainLoss`、
   `GainLossOnEquitySecuritiesNet`、`NonoperatingIncomeExpense` 系标签，使 `adjusted_net_income` 与
   衍生 `net_margin` 真正剔除投资浮盈。注意 cap（`nonrecurring_addback_revenue_cap`）对 $99B 量级的含义需复核。
2. **P1 — 新增 quality risk 项**（类比 PR #86 的 `pre_earnings_window_risk` 模式，只警示不自动降分起步）：
   `nonoperating_gain_inflation`，触发条件如单季 `NonoperatingIncomeExpense / Revenue > 阈值`
   或 `(NI − OCF) / NI` 异常且 margin 异常高；同步进 summary 徽章与 Fundamental Watchouts。
3. **P2 — 缺失指标强制提示**：`net_margin` 显著高于 `operating_margin`（裂口超阈值，如 >15pp）且
   OCF/NI 缺失时，写入 missing/复核提示，禁止静默通过。本案 55.7% vs 34% 的裂口即为触发实例。
4. **P3 — 人肉规则沉淀**（报告解读手册）：净利率远高于经营利润率时，先查营业外收支，再采信 Quality 等级。

---

## 6. 方法论备注
- 本案的发现链可复用：`net_margin` vs `operating_margin` 裂口 → 查 `NonoperatingIncomeExpense` 系标签 →
  对比 `OperatingIncomeLoss`。建议固化为 Quality 评审的标准动作。
- 干净信号与污染信号并存时（本案 operating_margin / fcf_margin / 营收增速干净），
  降级应精确到指标项，而非整单作废——这也是本修复方案采用"剔除 + 挂 risk"而非"降级整单"的原因。

---

## 7. 附录：2026-10-16 全宇宙横向排查（XBRL 明细复核后）

方法：遍历 `cache/facts_*.json`（预热全宇宙），取各 filer 最新 ~90d 季度，
以 `NonoperatingIncomeExpense` 系 / `EquitySecuritiesFvNi*` 系 / `(NI−OCF)/NI` 为初筛，
凡命中者逐一核对 XBRL 明细标签（ consolidated 口径，剔除分部片段误取）。初筛 231 家，复核结论如下。
（一句话：Top-15 无新增中招者；GOOG 仍是唯一的"高确信 + 大金额"污染。）

### 7.1 确认污染（金额实质 + 报告评级受影响）

| 标的 | 最新季度非经营利得 | 占当季净利 | 报告评级/优先级 | 说明 |
|---|---|---|---|---|
| GOOG | $99.0B（权益证券利得，含未实现 $21.4B） | 88% | A 0.79 / pri 30 | 本案主角，见 §2 |
| AMZN | $53.4B（营业外收支净额；**已归因，见下**） | 85% | B 0.77 / pri 43 | 未进注意力；OCF $45.4B vs NI $62.7B（OCF/NI 0.72，边缘） |
| SHOP | $1.25B（`UnrealizedGainLossOnInvestments`，≈净利 83%；**已归因，见 §7.6**） | 83% | A 0.84 / pri 79（WATCH_PULLBACK） | 标签集欠覆盖的直接证据：该标签名不在 strip 集 |
| WDC | $2.73B（`EquitySecuritiesFvNiUnrealizedGainLoss`，≈持续经营净利 85%；**已归因，见 §7.6**） | 85% | A 0.80 / pri 342（HOLD） | 变体标签问题；注意力之外 |
| SNPS | $0.43B（`DisposalGroupNotDiscontinuedOperationGainLossOnDisposal`，≈净利 78%；占营收约 18.5%，非初筛显示的 59%） | 78% | A 0.757 / pri 83（WATCH_PULLBACK） | 处置利得变体标签同样不在 strip 集 |

### 7.2 明确误报（已撤回）

- **AMD**：初筛 F1 系 revenue 误取片段所致（取到 $1.58B，实际合并营收量级约 $8B+），
  明细中无对应非经营利得。教训：单标签粗扫必须配合并口径约束（生产管线的 TTM 重建已有此约束，本排查脚本没有）。

### 7.3 噪声（金额过小，不影响报告）

TEM / SDGR / AXON / ARM / PEG / AQN / IIIV / OPTX / ACNT / IESC / MDB 等：
分母（净利）过小导致比率爆炸，绝对金额均 <$0.2B，且评级多为 B/C 或远离注意力（pri>170）。
此类由 F3 现金断裂触发器在 TTM 化后自然过滤，单季 OCF 噪音大（CVX / PSX / MU 等多为季节性营运资本摆动）。

### 7.4 对 §5 修复方案的增补
strip 标签集至少追加：
`EquitySecuritiesFvNiUnrealizedGainLoss`、`UnrealizedGainLossOnInvestments`、
`GainLossOnSaleOfInvestments`、`DisposalGroupNotDiscontinuedOperationGainLossOnDisposal`、
`MarketableSecuritiesUnrealizedGainLoss`。
F3（现金断裂）建议 TTM 化后作为第二触发器，单季版本误报过多，不宜直接进 risk。

### 7.5 AMZN $53.4B 归因确认（2026-10-16 深挖，10-Q 原文）

来源：AMZN 2026 年 Q2 10-Q（accession 0001018724-26-000026，2026-07-31 申报），
"Total other income (expense), net **$53,415**（百万）"，与 XBRL $53.40B 一致。原文关键句：

> "The upward adjustments relating to equity investments in private companies of
> **$50.5 billion in Q2 2026** and $62.8 billion for the six months ended June 30, 2026
> reflect **observable changes in prices, primarily from our nonvoting preferred stock
> in Anthropic**."

机制链（ASC 321 计量备选法）：2023Q3–2025Q4 投入的 $8.0B 可转债（AFS 核算，浮盈走 OCI）→
2025Q1 / 2026Q1 转为无投票优先股；2026Q2 再投 Series G $5.0B + 行权参与 Series H $5.0B；
Anthropic 自身融资形成可观察价格 → 对优先股一次性上调 $50.5B，计入 Other income。
另有可转债转股 alike 重分类利得 $4.5B（半年度口径）。现金流量表以
`OtherNoncashIncomeExpense` +$53.38B 全额冲回——证实**零现金含量**。

XBRL 对应标签：`EquitySecuritiesWithoutReadilyDeterminableFairValueUpwardPriceAdjustmentAnnualAmount`
+$50.49B（本排查初筛未覆盖该标签，同样证明 strip 集欠覆盖；注意标签名虽含 Annual 实为季度值）。

**前瞻风险（同份 10-Q）**：截至 2026-06-30，可转债公允价值 $97.9B，其中 $92.0B 未实现利得
仍挂在 AOCI（OCI 口径），IPO/流动性事件触发转股时将循环进损益表——即未来季度可能重现
$50B+ 级别的"利润 nucleosynthesis"。另：AWS+Anthropic 扩展 $100B+/10 年商业承诺、
$20B 融资额度（Series H 后剩 $15B）、AWS+OpenAI 扩展 $100B/8 年（AI 商业侧记，与选股主题正相关，
与会计污染问题并存，解读时分离处理）。

报告影响：AMZN 当前 B 0.77 / pri 43，未进注意力；但其 TTM margin 与净利增速同样被污染
（Q1 非经营收支亦达 $16.0B，半年口径 $62.8B），Q3 若无新的可观察调价事件，增速项将自然回落——
这是"污染自洗"的一面，解读时需说明方向，不宜简单外推其 B 级为经营恶化。

### 7.6 SHOP / WDC 归因确认（2026-10-16 深挖，10-Q 原文）

**SHOP**（Q2 10-Q，accession 0001594805-26-000047，2026-08-05 申报）：
利润表 "Net unrealized gain (loss) on equity and other investments **1,249**（百万美元）"，
"Total other income (expense), net **1,287**"，当季净利 **1,502**——未实现利得占净利 **83%**，
经营利润（毛利 $1.71B − 经营费用 $1.22B ≈ $0.5B）仅为净利的约 1/3。
持仓组合：Affirm（Level 1，账面 $1,655M，较年初 +$144M）、Global-E、Klaviyo（含 Level 3 未归属认股权证，
缺流动性折扣 9%）及战略合作私营公司（measurement alternative）。
$1,249M 在组合层面的精确拆分需 Level 3 rollforward，方向性结论不受影响：
其 XBRL 标签 `UnrealizedGainLossOnInvestments` 不在 strip 集——与 AMZN 案并列为标签欠覆盖的直接证据。

**WDC**（FY2026 Q3 10-Q，季度止于 2026-04-03，accession 0001628280-26-029054，2026-05-01 申报）：
"Gain (loss) on retained interest in Sandisk **2,734**（百万美元）"，
"other income (expense), net **2,169**"（另有 debt-for-equity exchange 费用 −$545M 对冲），
持续经营净利 **3,205**——SanDisk 分拆保留权益重估占 **85%**；九个月口径该利得更高达 **$4,448M**。
性质上属分拆一次性重估（spin-off retained-interest remeasurement），
"非经常"属性比 ASC 321 常规调价更强，理应被 gain-strip 捕获。
XBRL 标签 `EquitySecuritiesFvNiUnrealizedGainLoss`（仅明细标签、无总额标签）同样不在 strip 集。

---

## 8. Ticket 规格（Borrow-vs-Build 收敛三件套）

> 通用约束：`unittest`（非 pytest）、单测禁止 live 网络调用、不输出绝对路径；
> 既有 M0–M5 断言与 v1 行为默认冻结，任何例外需 architect 显式批准。

### T1 — P1：标签名无关的非经营利得兜底 risk（止血，一次生效）

- **背景**：§3–§4。denylist 必然滞后，需要一条不依赖标签名的语义防线。
- **目标**：新增 Quality risk 项 `nonoperating_gain_inflation`（对标 PR #86 的
  `pre_earnings_window_risk` 模式：只警示 + 排序惩罚，不动 score/confidence/grade 起步），
  触发条件（二选一，阈值为初值，单测锁定后冻结）：
  1. 单季 `NonoperatingIncomeExpense（系，绝对值）/ Revenue > 25%`；或
  2. TTM 口径 `(NetIncome − OperatingCashFlow) / NetIncome > 50%` 且 `NetIncome > 0`
    （TTM 化，禁止单季 OCF 版本——§7.3 已证单季误报过多）。
- **范围**：`build_company_quality_v2` 仅（v1 不动）；`_build_warning_badges_inline` 加对应徽章
  （如 `⚠️NonOp-Gain(+81.8%)`）；`assign_action_priorities_v2` 复用 pre-earnings 惩罚量级（-0.06）。
- **验收**：
  1. GOOG / AMZN / SHOP / WDC / SNPS 五案全部挂 risk + 徽章；MSFT（$3.2B，占比 <10%）不挂；
  2. 新增单测：合成 decisions 覆盖触发/边界/豁免；全量 `unittest` 绿；
  3. 在 2026-10-15 快照上重放（`--recompute-v2` 或等价 dry-run），Top-15 变化可解释、雷达区徽章齐全。
- **非目标**：不碰 `NONRECURRING_GAIN_TAGS`；不做标签枚举。

### T2 — strip 集：从手工枚举改为 taxonomy 程序化生成 + 交叉验证

- **背景**：§7.1/§7.6。5 个变体标签证明手工枚举不可持续。
- **目标**：
  1. 一次性吃进本次实证的 5 个标签：
     `EquitySecuritiesFvNiGainLoss`、`EquitySecuritiesFvNiUnrealizedGainLoss`、
     `UnrealizedGainLossOnInvestments`、`GainLossOnSaleOfInvestments`、
     `DisposalGroupNotDiscontinuedOperationGainLossOnDisposal`、
     `MarketableSecuritiesUnrealizedGainLoss`、
     `EquitySecuritiesWithoutReadilyDeterminableFairValueUpwardPriceAdjustmentAnnualAmount`
     （注意末者名含 Annual 实为季度值，注释防误读；cap 口径复核 $99B 量级含义）；
  2. 建立生成脚本（taxonomy 关键字检索 `gain/loss/unrealized/nonoperating` →
     人工白名单确认 → 输出冻结集合 + 覆盖率单测），未来新增由测试发现而非用户发现；
  3. 与 edgartools 标准化 income statement 的 Other income 行做 parity 对账（见 T3），
     差异项进入 review 队列。
- **待 architect 决策**：strip 集位于共享会计层（`scanner.py:249-254` →
  `accounting.py:111`），修复会同时改变 v1 的 adjusted 口径。建议按"数据正确性 bug"在共享层修
  （v1 下 GOOG 同样被误评，冻结错误口径没有价值），但需显式批准；若否，则 fork v2 专用集合。
- **验收**：
  1. 五案 `adjusted_net_income` 重算后剔除利得（GOOG adjusted YoY 不再是 +114.7%，给出新值备查）；
  2. `pe_cash_backing_haircut` 行为不变（贵侧仍不触发，有单测锁定）；
  3. 全量单测绿 + 2026-10-15 重放 diff 可解释。
- **非目标**：不引入新数据源；不改 Quality 权重。

### T3 — Spike（半天封顶）：edgartools 标准化报表能否接管映射层

- **背景**：AGENTS.md §5 Build-vs-Borrow。`edgar`（edgartools 5.61.1，已在依赖树，
  `Company.get_financials/income_statement`）已维护"标签→标准报表行"映射。
- **目标**：回答一个二元问题——它的标准化 Other income 行能否作为 T2 的第二信号源
  （替代手工维护 strip 集），而 **Quality/Entry/Action/TTM/股本/估值语义保留在仓库内**。
  红线：edgartools 不得成为第二套 Quality 实现（沿用 `sec_edgartools_parity_spike.md` 方法与红线）。
- **验收（任一即关 spike）**：
  1. PASS：测试集（含 GOOG/AMZN/SHOP/WDC/SNPS + 20 家随机）上，其 Other income 行与我们 XBRL 直读
     的检出一致（允许记录在案的口径差 <5% 样本），则立项接入（只读信号 + parity 单测）；
  2. FAIL：任一实质分歧无法在半天内归因，则维持 T1+T2 现状，结论记入 spike 文档，不再追。
- **非目标**：不评估 Simfin / yfinance / 付费 API（PIT 对账成本已判净负，见正文 §四）；
  不碰 v1；不产生生产行为变更（spike 只读、可丢弃分支）。

### As-Built & Follow-Up Sync (2026-10-16, post-PR #90)

> 本节为 PR #90 合入后的 as-built 记录与跟进裁决，供后续读者对照 §8 T1–T3 的原始规格。

- **T1（P1）已实现（as-built 与原始规格存在记录在案的口径差）**：生产触发不是"单季非经营
  收入 / 营收 > 25%"（该口径保留为 **Case C** 兜底），而是 **TTM 净利率 − 经营利润率裂口**
  语义：`QUALITY_V2_NONOP_MARGIN_GAP_MIN = 0.05`、`QUALITY_V2_NONOP_NET_MARGIN_FLOOR = 0.12`、
  `QUALITY_V2_NONOP_MAX_CASH_BACKED_OCF_NI = 1.50`（Case A）；无经营利润率时回退 FCF 裂口
  （Case B）；单季尖峰触发为 `QUALITY_V2_NONOP_QUARTERLY_RATIO_MIN = 0.25` +
  `QUALITY_V2_NONOP_QUARTERLY_ABS_FLOOR = 200_000_000.0`（Case C，SHOP 类）。常量定义于
  `src/ai_value_scanner/decision/quality.py`；排序惩罚为
  `H3_NONOPERATING_GAIN_PRIORITY_PENALTY = 0.06`（`src/ai_value_scanner/decision/action.py`）。
  徽章与 Watchouts 文案位于 `src/ai_value_scanner/decision/view_model.py`。
- **T2 已实现（收窄版）**：本次仅吃进实证变体标签
  `DisposalGroupNotDiscontinuedOperationGainLossOnDisposal`（`scanner.py` 的
  `NONRECURRING_GAIN_TAGS`）；其余 below-the-line 投资利得标签**故意不进入 strip 集**
  （会错误冲减 `OperatingIncomeLoss`，见 `test_below_the_line_gain_tags_not_stripped_from_ebit`），
  由标签无关的 Layer-1 A/B/C 覆盖。taxonomy 程序化生成与 edgartools parity 对账未做。
- **T3 正式标记为 Deferred (2026-10-16)**：edgartools 映射层 spike 未执行，理由——标签无关的
  Layer-1（Cases A/B/C）+ 只读审计脚本
  （`scripts/audit_nonop_gain_screen.py`）已覆盖当前全部实证污染案（GOOG/AMZN/SHOP/WDC/ZM/
  NTNX/SNPS），接管 Tag→标准行映射属 Borrow 收益不足；仅当未来出现同时逃逸 TTM 裂口与单季
  尖峰的 filing 类别时再重启评估。
- **跟进增强（本 PR）**：P1-1 Case C 单季触发；P2-3 经营口径增速替代可追溯
  （`operating_growth_basis_substituted`，不参与排序惩罚）；P2-2 `--recompute-v2` 同步
  Highlights（经营利润率封顶与增速替代），消除预览自相矛盾；P2-1 `action_list_v2.md` 在
  `Pool & Concentration` 下方披露因质量完整性被挤出 Top-15 的 `PRIORITY_REVIEW` 标的；
  P1-3 只读审计 CLI 入库（见 `scripts/README.md`）。

