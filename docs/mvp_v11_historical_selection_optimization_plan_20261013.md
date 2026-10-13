# MVP v1.1 — 历史数据驱动的选股质量优化执行计划

> 制定日期：2026-10-13  
> 基线：MVP v1 Beta 已交付，main = 220a4716c411bd7e9e80f9f7f89502f6ab1ff0ac（PR #66 merged / 623 tests CI pass）；本文件中的 SHA 只是制定时检查点，执行时必须重新核验。  
> 类型：**开发/调参/历史回测执行合同（计划）**，不等于已完成实验，不授权自动切换生产策略、覆写正式快照或立即启动付费计算。  
> 产品北极星：**值得长期研究的公司 × 合理的关注/入场位置 → 5–15 名可解释的人工 Action List → 同源 Detailed Report**；不是自动交易，也不是单纯收益最大化。

## 1. 一页决策

**立刻利用已存在的历史数据优化 MVP，而不是等 20/60/120 天前瞻结果成熟。** 最多 **2 个 outcome-sized 开发 PR**（本计划的 docs PR 不计入），必要时第二个可以不做。不要拆分为一个指标/脚本/说明一个 PR。

| 阶段 | 交付 PR | 工作与成果 | 改动生产 v1？ |
| --- | --- | --- | --- |
| A — 历史优化与选择 | **PR-A：Historical v1.1 optimizer + paired evidence** | 核验既有数据；复现 canonical v1；实现少量候选规则/小范围调参；离线配对回测；得出 GO/INCONCLUSIVE/NO-GO 和唯一推荐候选 | **不改** |
| B — 产品接入与终验 | **PR-B：MVP v1.1 opt-in release + end-to-end acceptance** | 仅在 A 有足够理由时：接入 1 个被选候选、策略版本/开关、同源报告、回归测试、历史配对验证、非 formal 当期体验验收 | 默认仍 v1；经审批才推广 |

**最早停止条件：** A 若没有跨时间段、风险和解释均可接受的改进 → **继续运行当前 v1 Beta，不开 B，不反复搜索**。若 A 显示稳定价值，B 完成后先提供显式 opt-in v1.1 Beta，与 v1 并存；**不得自动推广生产 v2**。

## 2. 已有资产与需要正视的结果

- 归档：evidence-observations 分支的 runs/historical-selection-v1/historical_selection_v1_20261011_03/，含 README、study_manifest、H1/H2/H3、配对排名、失败案例、前向标签校正和 SHA256SUMS。
- 数据规模：**25,025 pre-strategy 行 / 670 symbols / 39 个按月日期（2023-01 至 2026-03）**。Quality/Entry 数据集及修复后 v3 CSV、元数据可能保存在原始 outputs 或 Modal ai-scanner-research Volume；**Git 主要存审核汇总，不假装已存所有原始输入 CSV**。
- 已修正的拆股事件包含 BKNG/KLAC；WOLF 公司权益连续性不可靠的 forward 标签已置空。保留 51 条其它 audit-only 异常，不能假设所有价格标签完美。
- 修复后历史信号：Quality A 120d 日期等权 QQQ 超额约 **−2.9%**，C 约 **+10.5%**（受困境反弹/组成影响，**不是 C 比 A 更值得拥有**）；Quality rank IC 近 0；Quality A/B 的 ENTRY_READY 120d 超额约 **−3.8%**，WATCH_PULLBACK 约 **+2.4%**（WATCH ≠ 可立即成交）。
- 旧 E-first 简单置换、B+READY 全量提升已被研究否决。WATCH_BREAKOUT 是混合的「未 READY」兜底状态，不可视为真正突破形态。
- 2026-10-12 的 62 名三源池 + MVP Beta 端到端验收 **只证明运行/可用性**；这 62 名为 2026-10-11 事先冻结的诊断池，**不能替代 2023–2026 的 PIT 历史股票池**。
- 目前正式运行使用 risk_off **兼容数据/旧策略基线**；risk_on 是可保留的旧研究对照，**不要并排调两套 risk 风格再把新 MVP 拆回两个产品**。新 MVP 的市场 regime 属于 Entry policy。

优先复用：
- scripts/evaluate_company_quality.py、scripts/evaluate_entry_quality.py、scripts/evaluate_action_states.py
- research/historical_selection_v1_20261011_03 的历史研究脚本和决策重建逻辑（审阅后搬入 PR-A 中可测试的正式工具）
- src/ai_value_scanner/decision/{quality,entry,action,integrated}.py；src/ai_value_scanner/reporting/*
- scripts/modal_baseline_executor.py（**缺失历史输入时的提取器**）；scripts/modal_executor.py（**旧策略调参架构可借鉴，但不能未经改造直接用来优化新 canonical Quality × Entry**）。

## 3. PR-A — 一个完整的历史优化工作包（最高优先级）

### A0 数据门禁：先复用，绝不先重抓

1. 查询本地 outputs、原始研究目录与 Modal **at2018cow** workspace 的 ai-scanner-research Volume。取得修复后 v3 的 company_quality/entry_quality **完整 CSV**、对应 meta/splits、研究代码 SHA、config SHA、文件 SHA256；核对 dataset_kind、pre_strategy_cross_section=true、signal_date × symbol 去重、标签成熟/缺失、样本行数、证券身份与 SEC as-of。
2. 从 v3 构造每日期统一的历史决策输入及 forward 20/60/120d 标签。确保同一信号日只用截至当时可得的价格和已申报财务；对历史公司行为、退市/重组和 restatement 风险给出明确 audit flags，疑点标签从结果集排除或降级，不回填 0。
3. **基线 parity 强制通过**：在同一历史 row 上用 canonical v1 Quality、Entry、Action 及 integrated priority 算法重建，逐日期确认状态/score/Top-15 与原注册研究的一致程度。历史数据缺前次决策状态时，将 Top-15 标为 **historical priority/cap proxy**，不冒充线上 Daily/Weekly state-change 排名。若无法 parity，先仅修复计算口径，不解释优化收益。
4. 样本统一标注 **retrospective / union_superset_approx**；2023–2024 可用于假设开发，2025 与 2026 Q1 作为 **已被研究查看过的时间段稳健性检查**，绝不能称全新 OOS。禁止把 2026 年 10 月冻结的 62 名倒灌进 2023 年历史并宣称 PIT。

**A0 GO 条件：** 有真实可验证原始行与标签、可重新评分、v1 同源 parity 和记录完整数据局限。若 v3 CSV 不可取得，先只确认需要补的最小数据范围；**不直接启动整个历史重采集**。

### A1 只允许两个有经济解释的候选方向

**候选 R — 提升 Top-15 人工关注排序（优先）。**
- 先固定 v1 的候选池、Quality grade、Entry state、ActionState、关注上限 15；**只在同 Action/Quality grade 内**改变名次。
- 使用已有 Quality score、Entry score、置信度、重大风险/缺失与理由的固定、可解释分数；候选按下述 R1–R5 固定权重、confidence/risk penalty 测试（不得扩展为大网格）。不可再次把 E-first 当作新发现。
- 比较 Top-5、Top-15、入选/被挤出清单，特别关注此前 PRIORITY_REVIEW 超额数量、风险更大的 A+READY，以及名单稳定性。

**候选 E — 提升 Entry 的实际筛选力（第二优先）。**
- 在 Quality A/B 的固定人群中，利用已存在的 Entry 条件与 breakout_reason 诊断，将「趋势完整 / RS 不足 / 相对强势 / 超涨 / 防守 regime 不满足」明确区分。
- 只考察以下 E1–E4 的两项明确阈值（RS60 READY、20d 过度延伸；不能误认为后一项直接放宽 READY），不进行几十个指标的全局调参。原始 WATCH_PULLBACK 的收益好不等于该时点可以买入；区分「应关注」和「何时成交」。
- 如需改变 Entry state / ActionState，则使用独立候选 policy version，并在历史配对中显示各状态迁移；不能偷改当前 v1 的语义。负面或缺失证据不能变成 PASS。

**Quality 专业语义的约束：** 本轮不做银行/保险/REIT 全套行业评分器，不以过去收益把 C 重新定义成 A。只对能够证明的会计数据/实体/缺失误判做**小范围保守保护**，将不适用的专业财务指标标记 SPECIALIST_REQUIRED / UNVERIFIED；缺乏证据就维持 v1 及披露限制。跨行业评级可比性不凭该历史 AI/主题池验证。


### A1.1 参数名、当前实现、首轮实验数值（正式冻结清单）

这里的 **Quality/Entry 70:30** 是两份现成决策评分在 **Top-15 排序**时的权重，**不是** Company Quality 内部各财务组件的权重，也不是 Entry 内部的趋势/动量权重。当前内部权重保持不变：Quality = 盈利现金流 0.30 / 增长 0.20 / 资产负债 0.20 / 稀释 0.10 / 估值 0.10 / 经营红旗 0.10；Entry = 趋势 0.35 / 动量 0.25 / QQQ 相对强度 0.20 / 位置 0.20。

**R：同一 ActionState、同一 QualityGrade 内的排序**。现有 `src/ai_value_scanner/decision/integrated.py::_priority_sort_key` 依次使用 Action、Grade、Quality score、Entry score、Quality confidence、Entry confidence、symbol 的字典序，**没有**现行的 70:30 参数。实验仅把同组的 Score 优先次序改为：

`RankScore = wQ * Qscore + (1 - wQ) * Escore - c * (1 - Qconfidence) - r * RiskFlag`

| 参数 | 当前 v1 | 首轮候选 | 修改范围 |
| --- | --- | --- | --- |
| `wQ`，Quality/Entry 排名权重 | Quality-first（无权重） | 0.80/0.20、0.70/0.30、0.60/0.40 | **仅同 Action、同 Grade 内排序**，不改变分组优先级 |
| `c`，Quality confidence 缺口惩罚 | confidence 仅后置 tie-break | 0 或 **0.05 × (1 - Qconfidence)**，只在 70:30 试验 | 排名惩罚，不是取消评级 |
| `r`，Quality 风险惩罚 | 无附加项 | 0 或 **0.05 × RiskFlag**，只在 70:30 试验 | 排名惩罚，不变成安全 hard gate |
| 缺失分数/置信度 | canonical fail-closed | 不变 | 不得用历史均值、0.5 或未来数据填补 |

`RiskFlag` 是二值 0/1：**只有截至决策日的 Quality risks[].code** 命中预先固定名单之一才取 1：
`net_debt_to_ebitda_weak`、`interest_coverage_weak`、`free_cash_flow_weak`、`shares_yoy_weak`、`receivables_growth_gap_weak`、`inventory_growth_gap_weak`。一次或多次命中均只扣一次；不查看回报后增删代码。原始 Quality score 可能已包含同类风险，因此独立的 R5 要检查**重复计罚**；缺少可信 risk code 先复算/对齐原始特征，不能默认「无风险」。分数范围均为 0–1，不使用整段样本统计量来标准化；同分用原 v1 排序次级字段（再以 ticker 确定），保留稳定排序。若发生缺失，沿用 v1 的保守比较顺序并单独标记，不让缺失抬升排名。

**E：Entry state 的单因素门槛**。现有 `src/ai_value_scanner/decision/entry.py` 中：
- `base_ready` 要求 `relative_strength_60d_qqq >= -0.03`。E1 测 **≥0.00**，E2 测 **≥0.03**；其他 READY 条件和市场 regime 不变。防守市场已有独立的 `defensive_ready: RS60 >= 0.05 且 return_20d >= 0`，因此 E1/E2 在该情况下可能**没有效果**。
- `overextended` 的其中一项为 `return_20d > 0.15`。E3 测 **>0.12**，E4 测 **>0.18**。注意 v1 另有独立 `base_ready: return_20d <= 0.12`：**把 overextended 从 15% 放宽至 18% 并不会使 16% 涨幅股票变为 ENTRY_READY**。它可能从 `WATCH_PULLBACK` 转成兜底 `WATCH_BREAKOUT`，同时可能被 SMA50、52w range 等其他 overextended 条件覆盖。E3 同理可能使 12%～15% 区间的非 READY 股票提早标记 PULLBACK；测试必须记录全部实际状态迁移。
- 以下固定：READY 20d 回报区间 `[-0.03, 0.12]`、`price_to_sma200 >= 1`、`price_to_sma50 in [0.98,1.08]`、60d 非负、drawdown ≤0.22、防守 RS60 ≥0.05、volatility ≤0.80、TREND_DAMAGED 以及所有数据时效/身份 fail-closed 检查。其他 SMA50/range 的 overextended 判断不变。
- 实验必须对同一历史特征**重新运行版本化的 Entry state → Action mapping → 排序**，而不是手工改 CSV 的 state 字符串；若数值 Entry score 保留 v1 评分函数，明确写出「score 不变，state gate 改变」，同步生成真实新 threshold/evidence/rationale，不能报告中的解释还显示 15% / −3% 旧规则。
- R 试验不调整 Grade、Entry、Action 或 15 cap；E 试验不改排序公式、Quality 或候选池；不可绕开 `AVOID` / `INSUFFICIENT_DATA`。

### A1.2 固定的 11 组实验矩阵（**非笛卡尔积**）

| ID | 具体内容 | 假设 |
| --- | --- | --- |
| **B0** | 完整 canonical v1 基线（字典序；READY RS ≥−3%；20d >15% overextended） | 必须首先完整 parity |
| **R1** | 80% Q + 20% E，c=0、r=0 | 最温和的混排 |
| **R2** | 70% Q + 30% E，c=0、r=0 | 首选权重假设 |
| **R3** | 60% Q + 40% E，c=0、r=0 | 测试增加 Entry 贡献 |
| **R4** | 70:30，c=0.05、r=0 | 仅惩罚 Quality 低置信度 |
| **R5** | 70:30，c=0、r=0.05 | 仅惩罚固定六类风险命中 |
| **E1** | 仅 READY RS60 −3% → **0%** | 减少相对弱势 READY |
| **E2** | 仅 READY RS60 −3% → **+3%** | 中度收紧 READY |
| **E3** | 仅 overextended 20d >15% → **>12%**；READY 的 12% 上限不变 | 更早等待回调 |
| **E4** | 仅 overextended 20d >15% → **>18%**；READY 的 12% 上限不变 | 避免部分过早 PULLBACK 标签 |
| **X1（条件执行）** | **仅基于 2023–2024 开发结果**锁定的 1 个 R + 1 个 E 候选 | 验证组合是否互相抵消或放大；没有两项合格则跳过 |

**数量 = B0(1) + R(5) + E(4) + 可选 X1(1) = 最高 11**，不是 3×2×2×2×2。R4/R5 不另做「两个惩罚都开」的组合，防止无限展开。注册 `candidate_registry.json` 时填写 ID、所有数值/阈值、版本、算法 SHA、数据 SHA、seed、生成时刻、是否条件候选、状态迁移预期与冻结日期。执行后不可修改同一 ID 的语义。若 X1 有效，作为第 11 组计数；否则总数为 10。

**实际效果检查：** R 若只改变 Top-15 **内的顺序而不改变成员**，Top-15 等权收益通常不变；这种情况只能声称「研究顺序有变化」，不能声称「选股回报提高」，除非能真实验证 Top-5 或人工关注效用。E3/E4 若主要把 PULLBACK 改名 BREAKOUT 且没有可理解的新研究动作，不应仅凭回报选择它。


### A2 调参上限、目标和风险约束

- **首轮至多 11 组（含 B0、条件 X1）**，总硬上限 24；超过已列明的 11 组必须先修订候选注册表并单独获得审批，不是可自由搜索的预算；所有候选先列入 candidate_registry.json，固定参数值、含义、计算代码 SHA 和随机种子。最多 **1 次受控搜索 + 1 次锁定候选后的时间分段复核**；失败不扩展网格追逐收益。
- 训练与复核：**2023–2024** 用于开发/比较，**2025**、**2026 Q1** 逐年分开复核；已经查看过两段，因此只是 temporal robustness check。新候选从同一 signal_date × symbol × label-valid mask 与同一 universe 配对 v1。
- **首要成功指标**：Top-15 相对 v1 的日期等权 **20/60/120d QQQ 超额改善**，同时看 Top-5；20/60/120 为多个相关视角，不逐个挑最好的一档。**硬风险约束**：最差日期/尾部亏损不明显恶化，候选数量与缺失/行业集中度不异常，真实可解释性不下降。
- 交易口径固定：信号形成之后的 **next_open 进入、所设 horizon close 退出**，和原历史协议一致的单边 **15 bps** 成本；报告毛/净代理结果及假定执行时点，不能用信号当天 close 作为既得买价。没有可靠 OHLC 时 MAE/MFE 或滑点写 unavailable，不以最终收益冒充回撤。
- 每个候选都报告：39 日期中的有效日期数、n_symbols、缺失与删样原因、日期等权超额、top-5/15 overlap、最差日期、按年份/regime、最高贡献股票/月份、实际风险/反例。相关/重叠持有期不得按 25,025 行独立样本计算显著性。
- **选择规则**：在开发期改善并且后两段不是明显反转，风险与解释不变差，才定 **一个**最简单的候选；如果只有 120d 单一窗口改善、靠少数暴涨/困境股、或对窗口和 universe 近似很敏感 → **INCONCLUSIVE / KEEP V1**。不预设必须产生 v1.1。


### A2.1 对照实验和验收数值（避免事后挑赢家）

1. **执行顺序**：先恢复真实 v3 数据和修复后的标签 → canonical v1 每股状态/分数/Action/排名 parity → 在查看本轮候选回报前锁定 B0/R1–R5/E1–E4 → **只在 2023–2024 开发期**计算各组结果并确定是否执行 X1 → 记录固定候选后一次性汇报 2025、2026Q1。不得发现 2025 最优参数又回头改 R/E；这些年份已经被历史研究接触过，名称只能是 **temporal diagnostic**。
2. **日期切片**：理论 2023–24 = **24** 个按月日期，2025 = **12**，2026Q1 = **3**（总共 39），以实际有效标签为准，不足则列明，不补造收益/日期。每个日期同股票池、同决策 as-of、同 v3 标签成熟/公司行为可用掩码；Top-15 和 Top-5 取同日固定决策类别优先级、比较候选与 v1 各自所选股票，缺标签时在**同日同口径**保守处理并报告样本损失。
3. **主要目标**：**60 个交易日 Top-15 等权 QQQ-excess 的候选减 v1 同日期增量**，日期间等权。20d/120d Top-15、60d Top-5、真实 Top-15 名单成员更替、Action/Entry 迁移、最差 3 日、各年和 regime 同时报告，不能因为另一条 horizon 更好而替换主要目标。
4. **经济实用性参考线**：预先设定 **2023–2024 主指标平均增量至少 +0.5 个百分点** 才进入优选考虑；2025 的配对方向也应不负且非明显失效；2026Q1 只有 3 个日期，作为压力警示、不以其正负直接宣布结论。+0.5pp 是**事前实用性门槛而非统计显著性**。任何一段尾部亏损、数据缺失/样本偏差、可解释性明显变差 → INCONCLUSIVE/KEEP V1；后段不正、差异高度集中或替换不足也不得 GO。
5. **换名单与真实变化的区别**：为每日期和每候选记录 `n_entry_state_changed`、`n_action_changed`、`n_priority_suppressed`、`n_top5_swaps`、`n_top15_swaps`、`top15_overlap` 和每个被挤出的真实 ticker。若没有 Top-15 替换，写 **NO_EFFECT**；「发生变化的日期上的平均增益」可以做支持性诊断，**不能取代全日期平均主指标**。
6. **收益口径**：统一 signal close 之后的 **next_open** 到 20/60/120 交易日对应 close；同日期的 QQQ 对照。单边 **15 bps**、假设完整进出往返约 **30 bps**；先核对 v3 forward label 是否已含此成本，防止二次扣除。给出 gross / net、缺失时是否估计得到 MAE/MFE；长期 horizon 重叠，**不按股票行独立计算 p-value**，更不构造虚假的可同时执行的策略 NAV。Top-15 是注意力名单，不等于当时一定买入。
7. **稳健性**：报告日期等权结果、符号/月份/业务类型集中度、最大贡献单股/单月剔除后的方向、最差日期、尾部、regime 与缺失/退市/重大公司行为情况。单一大赢家或困境反弹主导、只对历史 AI 近似池有效等情形应降级为 INCONCLUSIVE，不能用回测结果重定义 Company Quality。
8. **人类审阅价值**：每个候选固定抽样 10–20 个替换/升级/降级案例，记录原始 Q/E/理由和变化；现实中并没有 2023 年真实 reviewer 采纳/耗时标签，因此历史收益不能证明节省时间或当时正确买入。未来真实使用仍能用于评价体验，但**不是启动历史优化的阻塞条件**。

### A2.2 补充检查的常见遗漏与处理方式

| 易遗漏的问题 | 开发与回测中必须核对的动作 |
| --- | --- |
| **旧训练版本 vs 当前代码** | 旧提取版本 `af70b5e…` 与当前 main/PR #66 可能有数据处理差异。v1 parity 分开报告 Quality、Entry、Action、priority、历史 label；有差异先判断是否历史 live-SEC 数据漂移，不造假复现 |
| **PIT 股票池不完整** | `union_superset_approx` 不是真实 2023 全部 ETF 成分；新增 62 股 US Core 不可伪装成旧 PIT membership；报告来源、幸存者/退市和可外推边界 |
| **财务发布日期和实体** | 明确 period end、filing public time、数据提取日不同；latest facts/修订和 CIK/运营主体/币种不确定的记录应审计、保守降级；一个 algorithmic verified flag 不替代人工经济主体核验 |
| **拆股/重组/股权连续性** | 已修 BKNG/KLAC/WOLF 不代表全量完美。审阅 v3 的 51 条 audit-only 异常，结合事件及份额变化裁决；不得因未来大涨就随意删除真实赢家，也不得把错误标签当 alpha |
| **月度研究 Top-15 vs 日/周名单** | 月度离线只有 `historical priority/cap proxy`，无法复刻线上 prev-state / Daily attention。回测名、图和 KPI 一律标明 proxy，PR-B 再测真日/周体验 |
| **相对强度 / 市场状态** | E1/E2 在防守 regime 可能被 +5% RS 门槛覆盖；RS 特征使用同信号日 QQQ，不允许用未来行情补指标；拆分市场状态复核实际作用率 |
| **旧费用/流动性差异** | 旧单边 15 bps 是假设，不是 guaranteed fill；IEX snapshot gate、bar volume 与 20 日 ADV 不等价，无法从已过 gate 股票反推全部未入池股票的收益 |
| **报告/代码/复现** | 固定原始 CSV SHA、run-spec SHA、版本、候选 seed、参数、每行差异；状态 threshold text 及详细报告与 state 同步；保持 v1 关闭新开关时 parity 和可回退 |



### A3 PR-A 必须带的代码、测试与证据

- 交付：一个复用 canonical policy 的**离线评分/排名/回测比较器**（不重写第二套生产 Quality/Entry）；历史 data loader 与 integrity gates；固定 **B0/R1–R5/E1–E4/X1** candidate registry；确定性搜索器和必要的单元/集成测试。
- 基线验证：历史 v1 parity、失效/空值、严格时间截断、同日相同样本、next_open/cost、分组/浓度、no-lookahead、相同输入重复执行、错误公司行为标签 fail-closed。
- 产物：dataset_inventory.csv、candidate_registry.json、**baseline_parity.json、entry_state_migrations.csv**、paired_by_date.csv、top15_diff_cases.csv、metrics_by_period.csv、risk_and_missingness.md、decision_recommendation.md、run_manifest.json、SHA256SUMS。所有结果包含代码/原始数据/config/候选 SHA。
- **仅提交体积可控、许可允许的审核证据至 append-only evidence-observations 新目录**；不提交原始 Alpaca bars、授权限制缓存、密钥、大型数据集或私人 notes。PR Conversation 评论给出确切数据/证据 SHA、基线与候选表、GO/INCONCLUSIVE/NO-GO，最后一版 HEAD CI PASS。成果为研究决策，不暗中写入生产配置。

## 4. Modal at2018cow 加速计划（适度并行，不花冤枉钱）

**只对超过本机几分钟的计算使用 Modal，优先离线复用已缓存数据。** 全部任务前台执行，显式 `MODAL_PROFILE=at2018cow`，严禁 `--detach`，仅使用已获授权的 at2018cow workspace；运行前记录预期 CPU/RAM、候选数和费用上限，重型或付费作业须项目负责人批准后启动。本文件不启动作业。

| 工作 | 建议规格/并行 | 说明 |
| --- | --- | --- |
| G0 inventory、少量 parquet/CSV 数据校验与本机基线 | 本地快速执行；如超过几分钟可用 Modal **2 vCPU、4–8 GiB ×1** | 先记录耗时和峰值内存 |
| PR-A **离线**独立候选评分 | Modal **1 vCPU、2–4 GiB/worker，首批 4 并发、至多 8 并发**；不超过 24 候选 | 原始数据共享只读 Volume/缓存；矩阵/特征每个固定版本预计算一次，不给每个候选单独打 SEC/Alpaca API；按实测内存调整 |
| 大内存组装/单次历史特征处理（若确实必要） | Modal **2 vCPU、8 GiB ×1–2** | 减少频繁序列化，不与写共享 cache 的任务并行 |
| 修复缺失 v3 原始 CSV 时的**重型历史提取备用** | 复用 scripts/modal_baseline_executor.py：**1–2 vCPU、8–16 GiB，串行仅 1 个容器** | 先核实缓存/输入 SHA/Volume SUCCESS；因读写 SEC/Alpaca cache 与 PIT 口径敏感，不并发重复提取；不得变更原 _03 |
| PR-B 最终固定候选历史 paired replay | 能用冻结特征离线计算则同上；仅确需真实完整 replay 才 **2–4 vCPU、8–16 GiB ×1–2** | 最多 v1 和 1 个锁定候选；禁止每个调参候选做全链路 replay |

**技术落地要求：**
1. 查看已有 scripts/modal_executor.py 的 durable-result / app orchestration 范式，但它实际跑的是旧 tune_parameters 的 legacy 多窗口 backtest，**不能直接把它的胜者当 canonical StockDecision v1.1**。PR-A 可在原架构上增加轻量离线分析入口/脚本，共享相同研究逻辑；不要复制第二套评分公式。
2. 推荐把冻结 v3 数据**上传/复用一次**至 ai-scanner-research 只读数据位置，再让 worker 分批读取；不同候选的输出目录/ID 互不覆盖，主编排器限流并记录已完成结果、失败和重试。续跑必须对 run_spec SHA / input SHA / candidate_id 完全匹配，错配立刻终止。
3. 先 **4 worker 试跑基线 + 2 候选**，观察内存/Wall time/API 请求；如只是 CPU 计算且无内存压力，再扩至 **8**。不要按 AGENTS.md 允许的「最多 80 in-flight」去实际开 80 个容器。出错重试该候选，不重做全部。
4. 所有重型计算附实际 Modal app ID、workspace、规格、容器个数、wall time、估算/实际费用、Volume 路径、SHA、是否 API 网络访问。项目密钥不进入 Git，也不要给纯离线 worker 注入 Alpaca/SEC Secret。

**已经存在的备用提取工具示例（只有 A0 明确判定没有可用原始 v3 时才按原历史协议使用）：**

~~~bash
MODAL_PROFILE=at2018cow .venv/bin/python -m modal volume ls ai-scanner-research
# 精确 dataset 路径与已完成 _SUCCESS 文件以历史 manifest / Volume 实际目录为准。
# 重新提取须先批准费用并使用新的 run-id，不覆盖 _03。
~~~

PR-A 新增的离线候选运行命令必须在该 PR 内提供真实 CLI 用法、profile 检查、可选并发和可重跑示例；**不要在本计划假造尚未实现的脚本接口**。

## 5. PR-B — 如果 A 给出可信候选，才做一次性 MVP 接入

**一个 PR 包括全部代码、测试、解释、对照、验收，不拆成“阈值 PR / 报告 PR / 配置 PR”。**

- 从 PR-A 锁定的**一个**候选实现版本化 opt-in：例如独立 v1.1 ranking policy（首选）或小幅 Entry readiness policy（需要更严格解释和回归）。v1 policy/code hash、原有输出和 risk_off 默认行为保持不变。
- canonical StockDecision → Action List / Weekly / Detailed Report **同一决策对象**；增加版本、关键阈值/失效原因和 changed-vs-v1 理由，缺失/不适用永不写成 PASS。保留旧快照，不重写过去的 v1 日期。
- 单元与集成测试覆盖 state、score、Action mapping、Top-15、身份/filing/行情 as-of、缺失保守降级，以及关闭 v1.1 开关时对 v1 **精确 parity**。
- 完成**一次**锁定 v1.1 对 v1 的历史 paired backtest（39 日期；同股票池/同 PIT 边界/同数据源/同 next_open+15bps/侧）；只评价实际准则一致的 Top-k，不能把 20/60/120 收益视为可同时真实成交的投资组合净值。按 2023–24 / 2025 / 2026Q1、波动和最差日期给出全表及失败案例。
- 经负责人批准后，在目前 Generalized-v0 已冻结 62 股来源上各运行一次**非 --formal** v1 与 v1.1 当期工程体验对照，核验 metadata/CIK、候选数、可见理由与使用时间；这不是“独立历史 alpha 检验”，也不靠今天的收益证明优胜。
- 审核通过可供使用者**显式 opt-in 试用 v1.1 Beta**；是否切换默认扫描规则须另行批准，不能从旧回顾样本直接自启动。若该候选在严格实现时变得不稳定 → **不合并行为改变 / KEEP V1**。


### 5.1 PR-B 新增的上线检查（不要把研究改动偷偷变成默认）

- **最小可用版本化**：一个 v1.1 候选明确 `policy_version`、候选 ID 和参数 SHA、对应输出快照目录；`config.risk_off.json` 的默认运行行为不变，risk_on 不变成第二套正式 MVP。策略开关必须显式开启，关闭后与 v1 决策结构 parity。
- **跨报告一致性**：Action List / 每日 / 每周 / Detailed Report 从同一 `StockDecision` 生成，排序及 Entry 的阈值、风险理由和复核触发条件都跟随候选版本；把 E4 变成 BREAKOUT 但描述成有效突破属于验收失败。
- **历史代理 vs 当期体验分开**：配对历史回测继续标 `monthly historical priority/cap proxy`；同源 62 股非 formal 当期扫描核验真实 Daily/Weekly 15 名限制、详情理由、身份和保存路径，不能把未成熟的未来收益填到当期结果。
- **完整回退**：既有正式快照、`risk_off` 默认与当前 v1 代码/策略合同不覆写；用两个不同目录保存 v1/v1.1，对应 run manifest 有输入和 config fingerprints。测试证明关闭 opt-in 后恢复 v1；负责人单独批准后才讨论默认切换。



## 6. 验收判定（尽量简短，但必须能做决策）

| 维度 | GO 条件 | NO-GO / INCONCLUSIVE |
| --- | --- | --- |
| 数据与口径 | 完整 v3 行、metadata/哈希/时间来源，v1 parity、下一交易日收益与公司行为异常可说明 | 只有 Git 汇总或被污染标签却声称精确回测；未来事实泄露 |
| 选股效果 | 少数**预先固定**候选中至少一个相对 v1 的 Top-5/15 配对结果在开发期和后段风险检查中有一致、可解释的净改善 | 仅某一段/单一 horizon 赢、重尾赢家驱动、日期/行业过度集中 |
| 决策质量 | 真实候选差异可人工理解，风险/证据不弱化、没有抬高财务不可靠名字 | 靠降低安全/身份/缺失保护换“收益” |
| 产品稳定 | v1 unchanged；v1.1 独立版本可 opt-in，Action List 与 Detailed Report 同源，CI PASS | 偷改默认权重、旧 prospective、引入第二套互相冲突名单 |
| 策略推广 | **GO 是 v1.1 实验版候选 / Beta opt-in**，不是跨市场稳健 alpha 或 v2 production | 未获审批禁止默认晋级 |

**成本与停止纪律：** 首轮最多 **11 组（含 v1 与条件 X1），24 是需另行审批才可触及的硬上限**，一次候选搜索、一次时间分段复核、一次固定候选完整回测；如资料或性能不足，不靠扩参数/换标签直到找到漂亮结果。任何新大规模 SEC/Alpaca 提取、新历史 ETF PIT 重建、额外信号扫描或全面 v2 会计引擎，必须说明已有数据何处不够并单独获得批准。

## 7. 本轮不做的工作

- 不为优化分拆 5–10 个 micro-PR；不建新 Web UI、broker NAV、自动交易/持仓/仓位引擎；
- 不做无限制权重搜索、ML/深度学习、行业独立评分器、行业 quotas、历史 ETF 完整重建、全美股新数据重提取；
- 不使用 risk_on 与 risk_off 两套独立 MVP 正式决策产品；现有 risk_on 历史资料仅保留对照价值；
- 不因为历史 C 股超额高就调转 Quality 评级目标——公司可拥有性与短期困境反弹是不同问题；
- 不因为 2026-10-12 的 Beta 工程 GO 就声称真实收益、OOS 或策略 v2 已通过。

## 8. 立即执行顺序 / PR Conversation 任务记录

1. **先开 PR-A**：在 PR Conversation 评论中写明精确 main/evidence SHA、v3 数据恢复路径及哈希、固定候选 registry、资源预算、可复现命令、验收文件；先核对 v1 parity，再用 Modal 离线并行比较。
2. 同一个 PR-A 回传对照和 **选 1 / 选 0** 的决策，优先回答「Top-15 是否比 v1 更有价值」。无证据就停在 v1 Beta，拒绝增加备选候选。
3. **仅选 1 成功时开 PR-B**，完成候选落地、测试、回放、同源解释与非正式真实扫描验收；在 PR-B Conversation 评论记录最终 GO/INCONCLUSIVE/NO-GO。
4. 研究数据仍按 repo 已有协议追加至 **evidence-observations**，本计划不创建 extra evidence-only PR；review 只阻塞真实数据语义/未来信息、状态正确性、来源身份、不可复现、实质性误导等问题。

**最终策略：历史数据驱动改进可以立刻做；最少需要 1 个开发 PR、最多 2 个大型开发 PR。把算力用在少数可解释候选的对照，而不是再次把 MVP 研发变成无止境的研究计划。**
