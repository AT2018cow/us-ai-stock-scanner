# US AI Stock Scanner — 下一阶段总计划：v1 失败归因、数据正确性与循证 v2 研究

> **版本**：2026-10-14 / next-phase design contract（**更新状态 [2026-10-15]：本计划 M0–M5 已全部执行完毕**，完整实施台账、PR #73–#81 记录、v2 选股/报告公式与双轨验证结论见 [docs/mvp_v2_completion_and_handoff_20261015.md](mvp_v2_completion_and_handoff_20261015.md)）
>
> **用途**：为下一段对话、新接手的工程师、研究人员、审核者和项目负责人提供完整上下文、工作边界、执行顺序、证据位置及停止条件。本文不是生产变更、不是新参数注册表，也**不授权**任何新一轮收益实验、全量数据重提取、Modal 付费作业或自动合并。
>
> **最高优先级引用**：`AGENTS.md`、`docs/product_direction_low_frequency_manual_selection.md`、`docs/mvp_design_low_frequency_manual_selection.md`；长期发现/Quality 边界见 `docs/general_purpose_discovery_and_quality_v2_design.md`。本文补充**当前实际执行路线**，不替代这些产品与代码契约。旧交接里的 SHA、未合并 PR 状态必须在新对话重新核对。
>
> **制定本计划时已核实 GitHub**：`main=d25278c7baed4dca3ea9e63d7b0f36448b665d37`；`evidence-observations=68143bff19f60f014e237d1f95eda28adf074b9b`。历史优化 [PR #70](https://github.com/AT2018cow/us-ai-stock-scanner/pull/70) **已于 2026-10-14 合并**（merge `d25278c7...`），否定性结果与证据均归档。旧的历史优化**文档 PR #67 仍 Open**；它保留为当时的事前协议，不能被误读为本阶段需要重新执行的任务。以上状态仅是本计划写作时的检查点。

---

## 0. 一页执行摘要与正式研究决策

**已有事实**：

- MVP v1 工程链路已具备：来源可追溯的发现池 → Company Quality v1 与 Entry Quality v1 → canonical `StockDecision` → Daily/Weekly Action List 与同源 Detailed Report；实际投资决策由人完成。
- 过去的策略/因子、单硬门、渠道与权重等历史研究，已积累了不少**没有可靠增益**或解释性有限的结果；不能因一次新的猜想而重开旧参数网格。
- 2026-10-14 完成的 v1.1 历史调参 PR-A 对 9 个修改候选全部做了预注册开发期对比，主指标无人超过 +0.5 个百分点实用门槛；最优 E1 +0.213pp 且重要风险敏感性转负。正式结论为 **`PR_A_FINAL_DECISION=NO_GO_KEEP_V1`**。
- **v1 是继续运行的、已经实现和复现的对照基线，不是已经证明有稳定正超额收益的“最优模型”。**
- **v1.1 原计划的 PR-B 不启动**；条件组合 X1 不运行；不得为找“更好”而查询被该研究封存的 2025 / 2026 Q1 候选收益。

**下一阶段总策略**：

> **先审核数据身份与经济含义；再诊断 v1 是怎样分配错误/无效的人工注意力；只在找到清晰可证伪机制后，提出最多 2–3 个相互独立、可解释的新研究假设；最后用新冻结/前瞻证据证明“更好”。**
>
> 本阶段的首项成果应是**经审计的失败模式/注意力价值诊断与数据可比性报告**，而不是另一次历史调参排行榜。

**三个决策门**：

1. **数据可信**：无法证明 SEC 身份、原始事实版本、时点/股本/价格口径一致时，不得把评分或选股差异归结为经济机制。
2. **机制可信**：没有可复核的真实错判/漏判原因、只重排不换人、或未改善人工研究价值时，不推进候选规则。
3. **验证可信**：已看过的旧开发数据只能产生假设；没有预注册且独立的后续/前瞻证据，不推广新的生产策略。

---

## 1. 项目的中期目标与长期目标

### 1.1 产品北极星：低频人工决策辅助，而非自动量化交易

**核心问题是两步**：

1. **Company Quality**：公司是否值得长期拥有/跟踪？核心是财务质量、盈利与现金流、资本效率、债务/稀释、估值和会计风险。
2. **Entry Quality**：在公司的质量和风险已经有依据的情况下，当前价格/成交/趋势结构是否适合进入人工买入评估？核心是价格相对 SMA、20d/60d 动量、RS、回撤、突破/等待和市场状态。

**唯一正式决策链路**：

```text
US Core + Thematic (AI 只是可选主题) + Manual
        -> 冻结来源/as-of/证券身份 -> 去重与资格排除
        -> Company Quality × Entry Quality
        -> canonical StockDecision
        -> Daily / Weekly Action List (约 5–15 个重点人工研究名字)
        -> 同一个 StockDecision 的 Detailed Report (支持 + 反方证据)
        -> 人工判断/研究笔记/后续观察，不自动下单
```

ETF/watchlist 只提供**发现来源**，不是应复制的 ETF 组合、证券行业定义、Quality 加分或仓位建议。必须区分 `discovery_sources`、`business_model`、`theme`、`tradable_security`、`issuer_cik`；同一 CIK 的两种股票类别不得随意合并为一只可交易证券。

### 1.2 中期（下一批研究与产品迭代）的成功条件

中期工作的目标优先级如下，不预设必须发一个策略 v2：

| 中期成果 | 怎样算完成 | 不接受什么伪证据 |
| --- | --- | --- |
| **可靠、可追溯的数据决策** | 每次扫描可追踪 ticker/CIK/申报、公开时间、Company Facts 内容版本、单位/股份类别、行情来源与输入指纹；未知时明示 UNVERIFIED/UNCOMPARABLE | 仅有 `data_asof` 日期或当前 ticker→CIK 对照就称历史 PIT 已证实 |
| **可用于日常人工研究的 v1 Beta** | Daily 强调变动，Weekly 汇总；5–15 个真正值得看的候选有可理解的证据、反证、缺失和等待触发；Action List 与报告同源 | 一次 full scan 校验通过即称历史有 alpha |
| **v1 失败模式有结构化、可复核的解释** | 能区分“数据错/证据缺/标签错/Quality 语义不适用/Entry 错解/Action 排序错误/候选池偏差/真实不确定” | 事后从涨跌挑特征、把 C 级股票反弹直接解释为 Quality 评分应该倒置 |
| **谨慎的 Generalized Selection v2 研究准备** | 在有限、真实可比、PIT 有据的跨行业样本上检验业务模式解释和 Attention/Entry 机制；必要时只改解释、不动评分 | AI 主题/旧 channel 伪装成行业，或未验证银行/REIT 会计指标却强行跨业评级 |
| **前瞻观察机制** | 当时冻结的 `StockDecision`、名单、手工审阅结论、后续 20/60/120d 标签分开归档；积累足够完整的成熟日期 | 2026-10-14 才选出的股票伪装成 2023 年真实持仓或事后命中 |

### 1.3 长期方向（演进目标，不是下一 PR 的验收）

长期是**跨行业、美国上市公司、来源中立、可复核的低频人工选股工作台**，逐步支持：

- 有界 `us_core` + 独立 `thematic` + `manual` 候选发现，保持全链路来源、映射、流动性与不适用状态。
- **统一财务核心 + 少量经实际申报验证的业务模式解释**：软件/轻资产、工业/半导体周期、资本密集、资源、金融和 REIT 等；银行/券商/REIT 在专业口径未核实前保持 `SPECIALIST_REQUIRED` 或 `UNVERIFIED`，不得输出虚假的跨行业可比评级。
- 周期性的真实人工反馈、候选状态变迁、研究耗时/可解释性/风险提醒质量的衡量，及独立成熟的后续收益诊断。
- **仅在真正可复现的改善得到前瞻证据及负责人审批后**，以版本化 opt-in Beta 引入少量策略升级；旧 v1 始终能回退。
- 账户/NAV、仓位优化、下单、组合优化、全量历史 ETF 成分重建、高频交易、ML 黑箱大调参均**不是本阶段的前置任务**；以后也只能由具体用户需求重新立项。

---

## 2. 已经做过什么：从早期研究到 2026-10-14

下表是**项目历史脉络，不是待重复的开发清单**。个别 PR 的早期研究决策以原始证据为准，不能将“工程 GO”推广成“收益 GO”。

| 时段/代表工作 | 已完成的主要成果与真实限制 |
| --- | --- |
| **最初的 AI 股票扫描/量化研究** | 已有 SEC EDGAR 基本面获取与 Company Facts/TTM、Alpaca/IEX 行情、AI ETF / watchlist、行业/主题、价值/动量/趋势因子、历史 replay、研究缓存与回归测试；这些是可复用资产，而非已验证的自动盈利系统。 |
| **PR #23 之后的基线与归因研究、PR #26** | 构建 risk_off / risk_on 基线、分段研究、IC/decile/风险归因、旧评分权重对照；观察到风险与候选池/状态可能比简单权重更重要。证据：`evidence/baselines/post_pr23_005b86c/`。 |
| **PR #27–#31：原策略门控和一致性验证** | `low_value` position/range 单硬门等消融没有可靠可推广的回报改善；PR #30 same-state 168/168 oracle parity；发现研究 `channel` 元数据混入 scoring 的漂移并修复。已否决的 gate/权重不得当成新发现反复打开。见 `docs/work_handoff_after_pr30_20261010.md`。 |
| **2026-10-10 产品方向重置（PR #31 后）** | 明确从自动交易/组合 NAV 转向 **Company Quality × Entry Quality → Action List → Detailed Report** 的低频人工决策支持；v1 统一决策合同、报告及不可变快照。见 `docs/product_direction_low_frequency_manual_selection.md`。 |
| **v1 工程实现、Full Scan、EdgarTools 诊断及防护（PR #39–#50 等）** | 一个源对象驱动两种报告；对 SEC 10-Q latest filing/facts 覆盖缺口增加受限诊断/保守 fallback；修复市场会话、外币/身份/新鲜度 fail-closed。2026-10-09 `risk_off` 快照审计 510 decisions，Quality A/B/C/UNRATED 分布、19 PRIORITY_REVIEW 超过 Top15 上限、23 B+READY 转 HOLD、`WATCH_BREAKOUT` 为较宽泛 catch-all 等发现皆属**描述性横截面**。见 `docs/mvp_v1_strategy_audit_20261011.md`。 |
| **通用三源发现与 Generalized-v0（PR #56/#57 及 10-12 实验）** | 75 来源成员关系合并为 62 唯一证券；62 decisions，Daily/Weekly 各 15；Quality 24A/31B/5C/2U，Action 6/3/7/39/7（PR #57 冻结版本）；工程/覆盖诊断 GO，**非 formal、非未来收益、非策略 v2 GO**。 |
| **SEC 身份、报告与专业会计探索（PR #59/#60/#62）** | ticker/CIK 防误绑定、财务缓存格式保护、同源解释和报告；11 个固定银行/券商、REIT、一般经营企业案例与 15 指标会计语义矩阵。XOM 相同 as-of 不同事实内容、PLD filing/facts 延迟、银行 OCF 与 REIT 适用性仍是开放问题；首轮 Quality v2 **只达到研究方法阶段**。 |
| **Historical Selection v1：H1–H3（PR #58、修复后的 `_03`）** | 月度历史 Quality/Entry **25,025 行、670 symbols、39 日期（2023-01–2026-03）**；数据池为 `retrospective / union_superset_approx`，不是历史真实 ETF PIT 成分。修复 BKNG/KLAC 拆股收益 horizon、WOLF 重组权益不可连续的收益标签（保持缺失，绝不置零）；分别研究 Grade/Entry/Action：Quality A 120d QQQ excess 约 −2.9%，C 约 +10.5%（易受困境反弹/池偏差影响）；A/B + READY 120d 约 −3.8%，PULLBACK 约 +2.4%。**这不是“C 比 A 更好的公司”或“PULLBACK 可直接买入”**。 |
| **v1.1 Historical Optimizer PR-A：PR #70（本对话，已合并）** | A0 校验 v3；B0 canonical 决策 parity 25,025 行、39 日期、Top5/15 完全匹配；52 个异常事件盘点；有限 EdgarTools SEC/PIT（HEI 4 + 9 固定控制）；24×10 无收益成员预检；一次已授权的 2023–2024 开发期 1,440 行配对收益对照。实验工具、样例、可复现 manifest/CI 与评审 NO-GO 均已落库归档；生产 v1 未改。 |
| **v1.1 后验正式结论** | 预注册主指标：60d Top-15 日期等权净 QQQ excess 相对 B0 增量，**+0.5pp** 实用线。9 个修改候选全未达线：最优 E1 **+0.213pp**；E4 **+0.084pp**；R1/R2/R3/R4/R5 与 E2/E3 均负（见完整决策文档）。E1 事件敏感性 **−0.125pp（18 日期）**，评分来源敏感性 **−0.048pp（15 日期）**；最大正日期 2023-11-30 +6.573pp，单日剔除作诊断后总体约 −0.064pp；E4 只有 2 个日期换 Top-15。正式 **NO-GO/KEEP V1**，条件 X1 未运行，2025/2026Q1 候选收益没有解封，原 PR-B 未建立。 |

### 2.1 这些过去实验共同说明什么

- **可复现不等于有 alpha**：B0 parity、CI、SEC filing 时序审计与 62 股工程验收都证明各自范围的技术/数据合同，不证明投资策略持续跑赢 QQQ。
- **原 v1 不等于历史收益已经很好**：现有某些分组净相对收益是负的，Quality 评级可能更多衡量公司经营稳健而不是下一个 60/120 天涨幅。
- **微小阈值变化经常不换 Top-15 成员**：即便 EvidenceItem/Entry 状态变化，也未必改变关注对象。只改变组内顺序可能有人工研究价值，但无法凭 Top15 等权收益宣称更高选股回报。
- **发生换人也未必是好消息**：E1 换 57 个 Top15 席位，结果集中且敏感性转负；E2 的更强 READY 收紧更差。
- **数据语义错误会污染 Quality 与结论**：HEI 确认 period-weighted 两类别股数与单一 Common 股期末股数互换、又统一乘 HEI 一类价格；对照中 VSH 的 period-weighted 股数与 GOOGL 的多类别价格/数量范围也有疑点。历史 issuer 总市值不能简单用 `HEI Common-only` 股数×HEI 价格当成真实总市值。
- **真实问题要区分两种轨道**：原始 SEC/证券身份与会计口径错误是**正确性缺陷**；选股规则是否产生更有价值的人工关注是**研究假设**。不得根据未来收益反过来“修正”原始财务口径。

---

## 3. 可接手的资产和证据坐标（优先使用已存在的东西）

### 3.1 权威代码 / 数据基线

- GitHub 仓库：`AT2018cow/us-ai-stock-scanner`。
- 写作时 `main`：`d25278c7baed4dca3ea9e63d7b0f36448b665d37`（已合并 #70；下次必须重查），**v1 默认行为仍是基线**。
- 历史修正后的 v3 数据 SHA256：`2a4600ee72de560f4966a4a5aefae233b10ea0e6417a17fbdd1566578e5a328e`，25,025 行，39 日期；**原始大 CSV 未作为公开证据入 Git**，应在本地已冻结 outputs / 合规缓存中找回并先核对 SHA。
- v1.1 开发期真实执行的代码 SHA：`9514166907e7f279fd6efd6f77f672badb9bd6f7`（不是历史证据提交后的新 HEAD）；协议 SHA256：`0a911c0443a2c744a0e8fbe1da02ad4077c880fd08db76eaf96321d3d146f696`；B0 240 行成员预检 SHA：`bc9130edcb62c362d893166d69b7c363087f254ed91bca4127322faac93f6f60`。
- 已归档证据分支写作时 HEAD：`68143bff19f60f014e237d1f95eda28adf074b9b`；路径：`runs/mvp-v11-pr-a-20261014/`，含 A0、B0、52-event risk、13-case SEC/PIT、membership、dev-return 九文件和 final decision、SHA256SUMS。
- PR #70 final review：`docs/mvp_v11_pr_a_final_decision_20261014.md`。旧事前计划仍在 PR [#67](https://github.com/AT2018cow/us-ai-stock-scanner/pull/67)；它不重新授权开发/实验。

### 3.2 代码/设计入口（新参与者请按此顺序看）

1. `AGENTS.md`；`docs/product_direction_low_frequency_manual_selection.md`；`docs/mvp_design_low_frequency_manual_selection.md`。
2. `docs/general_purpose_discovery_and_quality_v2_design.md`；`docs/mvp_v1_strategy_audit_20261011.md`。
3. `docs/work_handoff_after_pr62_20261013.md` 与 `docs/business_model_quality_v0/` 的 11 例归因、会计语义和 reviewer notes。
4. `docs/historical_selection_research_protocol_20261011.md`、`docs/mvp_v11_pr_a_final_decision_20261014.md`、`runs/mvp-v11-pr-a-20261014/`。
5. 主要实现：`src/ai_value_scanner/decision/`、`src/ai_value_scanner/fundamentals/`、`src/ai_value_scanner/research/`；既有诊断 `scripts/audit_mvp_strategy_snapshot.py`、`scripts/evaluate_company_quality.py`、`scripts/evaluate_entry_quality.py`、`scripts/evaluate_action_states.py`、`research/build_entry_diagnostics.py`。
6. 报告与证据合同：`docs/research_evidence_workflow.md`、`evidence/baselines/post_pr23_005b86c/`、`evidence-observations`。
7. 只有需要真实数据源/接口验证时，才查看 Modal `at2018cow` 与合规原始缓存；优先小样本、不直接重跑历史全链路。

**区分三种证据等级**：

| 标签 | 来源及允许的说法 | 禁止的说法 |
| --- | --- | --- |
| `RETROSPECTIVE_EXPLORATORY` | 2023–2024 与已经参与历史研究的 2025/2026Q1、后验 62 样本；用于定位失败机制、提出假设 | “纯新 OOS”或重复选择参数后宣布稳定 alpha |
| `POINT_IN_TIME_RECONSTRUCTED` | 经独立原始来源、有效时间、冻结 membership、证券身份/价格/股本证据复核的时间截面；必须逐案例限定覆盖 | 当前 ticker/CIK 或 `data_asof` 字段存在就宣称完整 PIT |
| `PROSPECTIVE_FROZEN` | 先保存不可变输入/决策/人工审阅、后随自然时间成熟的标签；为长期主要验证轨道 | 在生成当天填入未来 60/120d 收益、把非 formal posthoc 冒充 live formal |

---

## 4. 下一阶段优先级、工作包与依赖关系

**本计划是研究路线图，不是一次性同时开工的功能列表。** 不使用固定日期或“必须找到赢家”作为质量门槛。

```text
M0 事实与产品基线复核（只读，无收益）
  |-----------------------------|
  v                             v
M1 P0 数据身份/版本/会计口径    M2 v1 失败案例 + 人工注意力价值诊断
  |                             |（数据不可比时标 UNKNOWN，等 M1）
  +--------------+--------------+
                 v
M3 输出 2–3 个机制假设 / 明确 NONE，并事前冻结新研究合同
                 |
                 v（只有 M1+M2+M3 gates 都满足）
M4 最小差异实现/同日无收益 parity + 新独立/前瞻验证
                 |
                 v（只有稳健且人工价值实证 GO）
M5 可选 Opt-in Generalized Selection v2 产品 PR
```

### M0 — 开工盘点与使用验收（**立即，先于改策略**）

**目的**：避免重做已完成的探索；确认 v1 的 5–15 条名单对用户真的可解释。

动作：

- 实时查询 `main` / `evidence-observations` / 当前 open PR / CI；核对 #70 merge 与归档、#67 历史 docs PR；保证 `config.risk_off.json` 和 canonical v1 行为未因实验代码变化。
- 读取已存在 2026-10-09 v1 快照、2026-10-12 Generalized-v0 62 样本及报告，只做**非 formal、只读、无新 API**审核；这些是**历史当期可用性证据**，不是 2026-10-14 投资名单。
- 固定约 **15–20 个**审核样例（可用少量 `PRIORITY_REVIEW`、`WATCH_BREAKOUT`、B+READY、A+TREND_DAMAGED、UNRATED；不凭涨幅挑选），人工记录：当前 Action、Grade、Entry、正反证据、实际 as-of、身份、触发下一步研究的条件、Y/N/unknown、研究耗时代理/实际记录、为什么拒绝。
- 清点已有状态迁移/Top15 cap 压制（如 v1 快照 19 PRIORITY_REVIEW / 主列表 cap 15）和 `WATCH_BREAKOUT` 的“兜底状态”歧义，区分**错误决定**与**解释欠完整**。

产物：`baseline_inventory.md`、`human_review_worksheet.csv`、`attention_failure_cases.md`、`review_gate.json`（字段包括证据级别及是否真实人工复核），附原始参考 SHA。**M0 GO**：没有篡改历史快照，能给出最多 3 个真实阻碍人工决策的具体案例族；否则结论为 `INCONCLUSIVE`，不改产品规则。

### M1 — P0 财务身份、内容版本与会计语义正确性（**策略研究的先决条件**）

**已知问题**：

- XOM 同一财务 as-of 在不同研究快照出现 `UNRATED` 与 `B`、公司事实内容规模/来源不一致；旧档案缺每次扫描的 ticker map、Company Facts 原始哈希、获取时刻。**不能断言是 SEC provider 自发翻转**，可能是旧缓存由自家复核作业重写。
- HEI 年报期间两类别加权平均基本股数 vs 单一类别瞬时 outstanding 混用，配合单一 HEI 证券价格导致市值定义不一致；**不能**从 Common-only 市值推断总发行人真实市值。
- 有界 VSH/GOOGL SEC 控制提示 weighted-average/多类别估值基础疑点。PLD latest filing vs Company Facts 可见性、HON/FCX/NEE 等同-asof或跨版本差异须按机制区分；银行/券商/REIT 的商业模式会计适用性待核实。
- 历史公司行为事件 52 个（WOLF 已空标签，其余 51 audit-only）；不以极端价格涨幅自动判断为坏标签。存在旧 replay 公司行为异常 fail-open 路径，只在准备使用该路径时独立硬化。

**首个 outcome-sized correctness PR 建议（先审后编码）**：

1. **运行级绑定**：冻结 ticker 原始/规范化/可交易 security ID、CIK/operating issuer、映射来源/版本/抓取时间和 SHA；保持 share-class 识别，不能以 CIK 直接合并证券。
2. **文件级溯源**：原始 SEC submissions/Company Facts 的响应哈希、HTTP / fetch timestamp、entity name、filing accession、period end、filing date、EDGAR acceptance/public timestamp、币种/单位/维度、cache hit 版本、转换后的有效事实层哈希、Score 输入层哈希。
3. **同 as-of 比较**：ticker+data_asof 相同但来源/实体/事实版本不同 → **跨运行研究比较 UNCOMPARABLE**，先归因再比较，不静默选择有利版本；必要的 production fail-closed 策略须独立测出影响，不能增新评级等级或悄悄调整权重。
4. **证券类别/估值正确性**：`common_shares_outstanding` 和 `weighted_average_basic_shares`、类别轴、即时日期、HEI/HEI.A 分别定价、市值口径分别记录。未经一致的历史时点证据，不数字修补冻结 v3。
5. **可界定的旧案**：XOM 为必测、HEI 为口径必测；VSH、GOOGL、PLD、HON、FCX、NEE 分成对照；原 PR #62 银行/REIT 11 样本是另一组业务语义研究，不必在本 PR 发明全部专业会计指标。
6. **测试矩阵**：同-asof不同原始哈希、ticker跨 CIK 错绑、share class 维度混用、period-weighted vs instant、旧缓存/新 fetch、SEC 不可达、future filing、非 USD/IFRS、重复申报/修订；全部必须保守失败、不会产生虚假的 PASS。
7. **性能/资源**：本地已有 cache + 模拟输入优先；只在具体案例需要时向 SEC 做低速、有限、可缓存检索。EdgarTools 只是准确读取/核对 accession/XBRL 的辅助，**不是真实 PIT、证券类别估值或来源绑定的自动真理机**。

M1 最低交付：`sec_provenance_run_manifest.json` 示例、`identity_version_comparison.csv`、`share_scope_adjudication.md`、失败路径测试与 exact-head CI；**不得重写旧 v3/正式 snapshot**。**GO**：同一经济输入有可复核内容版本/身份证据，若不能确定则明确停止评分比较或保守降级；不是宣称所有 670 证券 PIT 已认证。

**并行小范围研究（不必全部变成此 PR 的代码）**：对 #62 的 11 家、15 指标逐项把 `SCORED_NEGATIVE`、`MISSING`、`INAPPLICABLE`、`UNVERIFIED` 分开，特别是银行/券商的 OCF/收入词汇、REIT 的 FFO/AFFO、XOM 运行版本、PLD filing 延迟。输出经 SEC filing 证据支持的解释文档；不要提前创建一套跨行业 v2 打分规则。

### M2 — v1 历史失败归因与人工注意力诊断（**先归因、后候选**）

M2 可以读旧结果开始，但只有 M1 明确可比的记录才可以被称为“经济/决策机制失败”。其余必须挂 `SOURCE_UNVERIFIED` 或 `LABEL_UNRELIABLE`，**不能为配合假说自动删除差异日期**。

**两条互不混淆的案例轨道**：

1. **事前条件分层样本**（主证据）：按历史信号日期/Quality grade/Entry state/Action/Top15 入选与 16–30 名压制、上升/下降 regime、业务模式和数据 confidence，在**不先看未来收益**时冻结约 24–36 个日期×证券案例（不足则如实记录）。包括 A+READY、B+READY、WATCH_BREAKOUT、A+TREND_DAMAGED、UNRATED、Top15 外候选及真实反例；各层保留来源标签和分母。
2. **后验尾部故障清单**（仅探索）：明确以已经观察过的 2023–2024 返回作为线索，查看 v1 Top15 跑输/跑赢、最大漏选、换股后两边损益、严重反弹/公司行为等案例。**这些股票不再当作新验证数据**，且必须并列展示赢家/输家、零变化、良好拒绝决策。

**需要回答的五类可证伪问题**：

| 诊断轴 | 具体可观察问题 | 必须保存的反证 |
| --- | --- | --- |
| **Quality 财务含义** | A/B/C 是否区分了现金流、利润、财务稳健和估值风险？是 fact 来源/股本口径错、可用性问题，还是合法会计结构不适用？ | 好公司短期跑输、C 公司困境反弹不是评分误判的充分证明；同行/模型反例 |
| **Entry 时机含义** | READY 真满足哪些门？`WATCH_BREAKOUT` 是均衡/弱 RS 的兜底还是接近真实突破？是否把非 READY 漏写成“各门通过”？ | 同状态中不同失败门、市场 regime 变化，未观测到的门标 `UNOBSERVABLE` |
| **Action / Top15 结构** | Action→Quality grade→分数的优先级是否让价值高的人工候选长期在 cap 外？排序是否仅在 Top15 内变动？ | Top15 顺序优化若未改变成员，不宣称 Top15 等权回报改善 |
| **发现/业务模型** | 老 AI ETF 近似池是否导致样本/风格偏见？对银行、REIT、资本密集企业是否出现系统性 `UNRATED` 或错误 B/C？ | 把源池与行业标签分开；未知/不支持类型单列，不强制补分 |
| **真实人工效用** | 用户能否从 Action List 看出应研究谁、反方是什么、明天/下周何种条件触发复核？多大的状态变化没有真实研究意义？ | 审稿人拒绝/不确定、解释矛盾、候选抖动、仍需额外查证的实际成本 |

**案例表最小字段（每一行必须保留来源）**：

```text
study_case_id, case_selection_method, evidence_tier, signal_date, symbol,
source_snapshot_sha, scanner_code_sha, config_sha, candidate_universe_asof,
security_id_or_unverified, issuer_cik_or_unverified, filing_accession_or_unverified,
facts_fingerprint_or_unverified, quality_grade, quality_score, confidence,
quality_evidence_codes, missing_codes, entry_state, entry_evidence_codes,
action_state, priority, selected_top5, selected_top15, excluded_reason,
review_question, observed_failure_hypothesis, alternate_explanations,
data_verdict, human_review_verdict, review_time_or_unknown,
future_label_valid, forward_label_definition, realized_outcome_if_exploratory,
reviewer_notes, source_links
```

**结果拆分规则**：

- `DATA/IDENTITY ERROR`、`ACCOUNTING SEMANTIC GAP`、`EVIDENCE PRESENTATION GAP`、`RANK/CAP STRUCTURAL GAP`、`ENTRY TIMING GAP`、`UNIVERSE/PIT BIAS`、`CORPORATE_ACTION/LABEL UNCERTAINTY`、`IRREDUCIBLE UNCERTAINTY`；可多标签但必须注明主因/反因。
- 保留当时有效证据 vs 后来才知道的解释；未来价格只在**后验分析视图**出现，不能反向进入未来候选定义。
- 对预先固定分层按日期报告 case 数、grade/state/action、覆盖/缺失率、正误样例、风险复核次数；不要把 24–36 例当成总体分布估计，也不要用少数尾部案例宣布策略增益。
- 对历史 Top15 描述性收益依旧采用日期等权、同日期 QQQ、已修正标签，单股/单日最大贡献与 mask attrition；不能把 20/60/120 重叠行视为独立样本。
- 专门审查“**被挑中的赢家**”和“**被拒绝的好股票**”时，同时陈列替代成本和被选替代名字；不允许只列涨得最多的漏选股。

**M2 交付/GO**：`case_registry_frozen.json`、`v1_failure_casebook.csv`、`attention_failure_attribution.md`、`report_evidence_parity_checks.json`、`hypothesis_backlog.md`（每条有反证、数据限制、验证可行性）。如候选池/PIT 不可比，应结论 `DIAGNOSTIC_INCONCLUSIVE` 而不是编造提升。

### M3 — 小假设清单，先做“无收益可见”的规则差异实验

**不要复制旧 R1–R5 / E1–E4 参数、旧 E-first 或旧单硬门**。最多选择 **2–3 条机制不同、来自 M2 真实诊断**的可证伪假设；可以只选择 0 条。下列是**待验证方向，不是新规则或新的已注册参数**：

- **H-Q：质量输入适用性/置信解释**。将 `SCORED_NEGATIVE`、`MISSING`、`INAPPLICABLE` 与真实经济红旗分清、让错误估值/稀释口径能 fail-closed；先比较事实正确性及人工误读率。此方向的“修数据”不自动计作历史收益优化。
- **H-A：人工关注 cap / 排序结构**。研究 Action/Grade 的层级优先级是否隐藏重要候选、被压制 A/B READY 是否有可复核的研究价值。**先同日期名单/排序/解释 preflight**，如果主 Top15 成员未变化，只评估人工研究效用，不能冒称 Top15 预期收益提高。
- **H-E：Entry 的原因分层和状态误解**。`WATCH_BREAKOUT` 用具体“尚未满足的 READY 门”分组，确认真 breakout 与普通监测的区别；第一版本优先提升 evidence 透明度而不是阈值。有确凿机制后才讨论一种最小行动规则。

候选提交前的**冻结合同**：

- 明确因果/经济机制、适用证券/业务模型、可计算的当时信息字段、输入 SHA、最小变更、预期会改变哪些 `StockDecision` 字段/Top15 成员、哪些明确**不得**变化（身份、报告一致性、原 v1 默认和缺失 fail-closed）。
- 以相同 PIT 身份/来源版本、日期、eligible universe 做 v1 vs variant 无收益配对。先看“是否改变正确的人类注意力和解释”，不直接查看每个新增参数的未来回报。
- 预先登记主用户效用指标和辅助经济指标（例如真实审核接受率/反证覆盖/错误解释率/时间、Top5/15 swap、stable attention、尾部和浓度）；**旧 +0.5pp 只是前次事前经济门槛，不能暗中充当新研究已批准阈值**。新实证门槛须在任何新独立收益进入前锁定，报符合/不符合而非最大化历史分数。
- 若要运行新的收益实验，需**单独**研究协议、真正独立或前瞻样本、基线、负对照、可复核的样本量/年份/数据能力、风险敏感性及一次性显式批准。旧 2023–2024 结果只能当探索性原理依据；2025/2026Q1 在旧优化中曾被研究接触且对旧批次仍封存，不可偷偷充当全新 OOS。
- 变动逻辑必须复用 canonical `StockDecision`、同源 Action/Report、不分叉第二套 Quality/Entry 评分引擎；默认 `risk_off` 仍要完全等于 v1。

**M3 GO**：固定 0–3 个可解释且真的改变必要行为的候选研究协议，或明确 `NONE/KEEP V1`；绝不因预检效果平淡而扩成大权重网格。

### M4 — 长期可信的验证轨道（按标签自然成熟推进）

与 M1–M3 **并行可以启动前瞻观测的工程，不必等新规则诞生**：

- 使用当下已经在运行的 v1 默认策略，以真实扫描日为单位存储源 Universe as-of、schema/代码 SHA、SEC 事实指纹、行情/feed、`StockDecision`、Action List/Detailed Report、Top5/15、人工审阅反馈。
- 新研究候选在**事前批准并锁定**后才能以影子模式另存独立 snapshot；先固定版本、同数据相同日名单，再在 20/60/120 个**交易日标签确实成熟后**评价，不造未来收益；旧 snapshot 不覆盖、不回填、不可伪装成之前就已运行。
- 验证维度按两条轨道分别 GO：**人工使用质量**（是否降低查证成本、错误叙述/冲突、可行动的等待条件、候选重复噪声）与**配对经济结果**（相同信号日 Top15 60d净 QQQ excess、Top5、尾部、regime/行业与符号集中、成本假设、event/score 不确定性），两者不能互相替代。
- 当新独立时间证据不足时报告 `NOT_YET_MATURE`，不加速日期；若源数据不全报告 `PIT_UNCOMPARABLE`；样本过少、月份/行业过度集中则 `INCONCLUSIVE`。
- 严禁通过调整证据收集日期、补抓当前 revised Company Facts、重复挑选参数来“提高”前瞻验证通过率。必要时采用按日期/持有期块的保守误差与不确定度分析，而不是按 25k 行独立计算 p 值。

**M4 GO**：实际成熟、来源一致的 paired dates 和人工效用评价显示事先设定的实质、稳健、可解释改善；否则继续 v1，不推动产品策略变更。

### M5 — 可选、独立审批的 Generalized Selection v2 opt-in（**非本轮默认任务**）

若且仅若 M1–M4 各自 GO，另起一个 **outcome-sized** opt-in 实现 PR，包含 policy/version、证据、回归、工程与人工验收、正式快照隔离、关闭开关后的 v1 exact parity。新的 US Core/Manual/AI 并集与业务模式解释不能同时被默默混入收益改进归因；若跨行业池要扩张，先独立评估覆盖/排除/流动性/身份，再评价规则本身。

只有项目负责人显式批准，才允许默认启用；**没有前瞻证据就继续 v1 Beta**，不是项目失败。

---

## 5. 下一阶段的 PR、实验、角色分工与最小交付

### 5.1 推荐开发拆分（避免代码/研究/数据三者归因混杂）

| 工作包 | 建议提交边界 | 产物与审核 | 是否改 v1 默认策略 |
| --- | --- | --- | --- |
| **本计划** | **单独 docs-only PR**，不合并/重写旧 #67 | 本文、准确 GitHub 指针与后续任务合同 | 否 |
| **M0 人工使用诊断** | 优先只读报告/现有数据；如要脚本，单个 outcome-sized research PR | 已冻结样本、完整性表、人工失败案例、报告/决策同源校验 | 否 |
| **M1 P0 financial identity/version** | 1 个 correctness PR（与策略优化分开） | 运行级事实/证券身份指纹、已知案例归因、失败保守测试、CI；必要时独立对照扫描批准 | 默认不改；必须保守失败时独立批准兼容性 |
| **M2 v1 失败归因** | 1 个有边界的 read-only research PR，能复用已有脚本则不要重写 | 冻结案例、诊断表、反例、证据及 UNKNOWN 清单 | 否 |
| **M3–M4 假设与验证** | 先独立研究协议 PR；获批后最多 2–3 个研究候选的单一对照实施/证据 PR | 事前冻结的候选 registry、严格差异/验证报告、GO/INCONCLUSIVE/NO-GO | 否 |
| **M5 可选上线** | 只有独立证据 GO 才新建 opt-in 产品 PR | 报告同源、v1 fallback、真实使用验收、独立快照 | 默认否 |

这**不是**旧历史优化 PR-A / 条件 PR-B 的重启。旧 PR-B 已因 NO-GO 跳过；新阶段的每个工作包必须有全新明确的目标、证据和负责人批准。

### 5.2 负责人和审核流程

- **代码与研究设计**：根据当前对话授权，可由 ChatGPT 编写 GitHub 代码/文档；下一阶段必须重新确认任务合同，不把此 docs 计划当成“可自动改生产”的授权。
- **项目负责人/本地执行方**：保护本地 worktree；检查准确 PR HEAD 和 CI；执行已审批的少量本地只读检查；决定是否触发需要凭证的 SEC/Alpaca 扫描、Modal 费用和任何 PR 合并；不把 API 密钥/SEC 身份放入 Git。
- **独立审核**：检查证据文件、精确 SHA、CI、逐案例反例、PIT 时间、业务语义、候选影响及数据缺失；给出**范围限定**的 GO / INCONCLUSIVE / NO-GO。一个阶段的工程 GO 不自动放行策略收益实验。

### 5.3 计算、数据费用和敏感文件约束

- 优先读取已有 v1 snapshots、`evidence-observations`、本地 `outputs/`、已缓存 SEC/Alpaca；离线核查应无 API 或 Modal 费用。
- 若必须重型任务：提出写明 run-ID、任务目标/冻结输入、预计 CPU/RAM/worker 数、网络与 SEC 速率、Modal `at2018cow` workspace/预算/运行时长的**单独审批**；要求前台执行、不 `--detach`、缓存只读/错写隔离。
- 严禁上传 `.env`、私有 token、个人 SEC identity、原始受许可限制 Alpaca/IEX bars、bulk SEC/EdgarTools caches、全量 25k 行 CSV、公司非公开研究笔记；如许可允许仅上传小型可浏览审计片段。
- 证据按 `docs/research_evidence_workflow.md` 追加到 **`evidence-observations`** 新路径，不覆盖历史；每次含 `README.md`、manifest、small CSV/JSON/MD、`SHA256SUMS`、确切执行代码 SHA/配置/数据来源/CI，使用归档**commit SHA** 锚定。不要把证据分支合入 main。

### 5.4 Gate/停止规则（可以诚实交付“没有赢家”）

| Gate | GO | 停止/降级 |
| --- | --- | --- |
| G0 基线 | v1 `StockDecision`、snapshot、源身份与报告同源；当期样本标志正确 | 找不到源输入/哈希、拿后验样本冒充 formal |
| G1 财务可信 | 指定样本的 ticker/CIK/股类/facts SHA/公开时间可核，未知严格 fail-closed | XOM 同-asof 未可比、HEI 股数经济语义未定义却硬算市值 |
| G2 失败归因 | 事前分层案例有足够反例，可区分数据错、错误解释与真实策略局限 | 只分析大涨大跌个案、忽略完整分母或采用事后修补 |
| G3 新假设 | 0–3 个机制可证伪、真实名单/人工价值差异、经批准新协议 | 换指标追涨、恢复已否决 R/E 参数网格、以统计图替代理由 |
| G4 独立检验 | 新鲜冻结样本有成熟标签、PIT 与多时间/风险/人工效用一致 | 仅旧 2023–24、后验 2025/26、少数暴涨月造成差异 |
| G5 推广 | 双轨可信 GO、默认 v1 parity、人工审批 | 任一证据不充分 → `INCONCLUSIVE/KEEP V1` |

---

## 6. 下一次对话：立即开工清单（无需先发新策略 PR）

### 6.1 第一天的只读检查

1. 从 GitHub 实时核对 `main`、`evidence-observations`、PR #70/#67、open PR 和 exact-head CI；**不要照抄本文件的旧 HEAD**。
2. 阅读 `AGENTS.md`、产品北极星、MVP 契约、本计划、`docs/work_handoff_after_pr62_20261013.md`、#70 最终否定性结论，以及 #62 专业会计研究。
3. 清点**确实已经存在**的可访问证据：v1 2026-10-09 与 Generalized-v0 2026-10-12 snapshots、H1–H3 修正后研究、PR-A 归档目录、小规模 SEC 缓存与研究 CSV；逐个记录 SHA/缺失，不假装所有本地文件可被 GitHub 直接恢复。
4. 先产出 M0 简短的行动名单真实可读性问题 Top-3、已有来源不可比清单与 M1 P0 的可执行合同。**不要立刻跑新的收益回测或新参数搜索。**

仅需检查环境时可以使用这些**已存在的标准命令**（实际分支/路径必须以现场为准）：

```bash
git status --short
git rev-parse HEAD
python -m unittest discover -s tests
```

不要依据本计划想象尚未实现的 CLI 参数；新的 M0/M1 工具命令必须在其未来实施 PR 的 runbook 中声明并由实际 CI 证明。

### 6.2 建议下次对话的第一项具体产出

**《M0/M1 开工核对与失败归因样本合同》**，要求包含：

- 冻结 `main`/证据 SHA，列清楚已能读取和缺少的输入；
- `human_review_worksheet.csv` 的字段约定、事前分层案例数量、首批仅 15–20 例；
- XOM/HEI/VSH/GOOGL/PLD 等的 `source-provenance` 验证矩阵（UNKNOWN 优先于猜测）；
- v1 Top5/15、B+READY、WATCH_BREAKOUT 的两个或三个最高价值可读性问题；
- 无任何新的候选参数、不调用正式历史收益、无网络重算及 0/低资源预算；
- 是否需要下一步 M1 P0 correctness PR 的独立审核决定。

**交接给新的参与者：** 先向项目负责人呈现这份已核查的执行合同，收到单独开发授权后再写代码；关键阶段对齐 GitHub exact-head CI 和独立审查。**本文件不构成任何收益实验授权。**

---

## 7. 资料与长期可维护的交接约定

| 资料 | 角色 |
| --- | --- |
| [项目产品方向](product_direction_low_frequency_manual_selection.md) | 最高优先级：当前与长期成功定义 |
| [MVP 决策架构](mvp_design_low_frequency_manual_selection.md) | canonical `StockDecision`、同源 Action / Report 与 Prospective 不变量 |
| [通用发现和业务模式 Quality v2](general_purpose_discovery_and_quality_v2_design.md) | US Core / AI Theme / Manual 来源约束、专业会计边界 |
| [PR #62 后交接](work_handoff_after_pr62_20261013.md) | 金融事实版本 P0、专业会计、Entry 和 IEX 缓存问题 |
| [v1 观察截面审计](mvp_v1_strategy_audit_20261011.md) | v1 Action/Grade 分组、`WATCH_BREAKOUT`、cap 与 B+READY 案例 |
| [历史选择研究协议](historical_selection_research_protocol_20261011.md) | 数据窗口/retrospective/PIT/收益重叠与 H1–H3 限制 |
| [历史 v1.1 最终结论](mvp_v11_pr_a_final_decision_20261014.md) | NO-GO/KEEP V1 的正式经济门槛、E1 敏感性、不得展开 X1 |
| [PR #70 已合并](https://github.com/AT2018cow/us-ai-stock-scanner/pull/70) | 实际代码、评论、运行协议、测试及负结果 |
| [v1.1 归档证据](https://github.com/AT2018cow/us-ai-stock-scanner/tree/68143bff19f60f014e237d1f95eda28adf074b9b/runs/mvp-v11-pr-a-20261014) | A0/B0、SEC、risk、preflight、dev-return、final decision 与逐文件 SHA |
| [历史调参计划 PR #67](https://github.com/AT2018cow/us-ai-stock-scanner/pull/67) | 事前注册的研究合同，**不是本阶段下一步指令** |
| [浏览型证据工作流](research_evidence_workflow.md) | Append-only archive、哈希、许可与隐私操作规则 |

### 最终原则

- **先从现有数据中理解失败原因，再设计最小的可证伪修正；不靠更多参数试出漂亮曲线。**
- **先有证券/会计/时间点正确性，再谈规则是不是聪明；不能使用未来收益反向“修财务”。**
- **先证明用户能理解并有效使用 5–15 人工研究提示，再要求其证明投资增益。**
- **任何 NO-GO 都应是有效完成的研究结果；v1 可以长期保留，策略升级不是强制 KPI。**
