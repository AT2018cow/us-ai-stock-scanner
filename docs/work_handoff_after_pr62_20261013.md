# US AI Stock Scanner — 对话交接与开发审核基线（2026-10-13）

> 项目：`AT2018cow/us-ai-stock-scanner`  
> 整理日期：2026-10-13  
> 性质：**更新后的事实与执行进度摘要**；不是对原始产品原则的替代，也不是授权直接修改生产策略。  
> 原始权威交接：[work_handoff_after_pr57_20261011.md](https://github.com/AT2018cow/us-ai-stock-scanner/blob/docs/handoff-after-pr57-20261011/docs/work_handoff_after_pr57_20261011.md)  
> 本次更新文档：[work_handoff_after_pr62_20261013.md](https://github.com/AT2018cow/us-ai-stock-scanner/blob/docs/handoff-after-pr57-20261011/docs/work_handoff_after_pr62_20261013.md)  
> 阅读顺序：原始交接 → 本摘要 → GitHub 最新分支和证据 → 相关设计/实现文档。

## 1. 一页结论：项目现在到哪里了？

**已完成原交接（PR #57）中第 5–8 节要求的首轮 Generalized-v0 端到端实验、证据归档和多维诊断审核。** 项目当前处于原交接第 9 节（**根据证据准备 Generalized Selection v2 候选政策**）之前的关键研究/正确性阶段。尚不具备直接推广生产 v2 的充分证据。

进度概览：

| 原交接相关阶段 | 最新进度 | 范围说明 |
|---|---|---|
| US Core / Thematic / Manual 三源候选合并（PR #56） | 已合并 | 75 memberships / 62 unique 的实验支撑已验证 |
| 全链路研究实现及协议（PR #57） | 已合并 | 冻结代码 `2d8919444828643f7b888f90907e0b0e6632bfc4` |
| 2026-10-12 非 `--formal` Generalized-v0 实验 | **已完成并审核 GO** | 仅首轮工程/诊断，不是收益/生产策略证明 |
| Universe、Liquidity、Quality、Entry、Action 五维审核 | **工程或诊断 GO** | 财务专业语义、流动性实盘能力等仍有明确限制 |
| 2023–2026 历史研究（Quality/Entry/Action） | 已完成首轮，纠正收益标签 | 回顾性近似股票池；不得冒充真实 OOS |
| 证券身份保护与报告可用性 | 已合并（#59、#60） | 同一个 `StockDecision` 输出 Action List 和 Detailed Report |
| 跨商业模式 Quality 研究设计及 11 个案例（#62） | **已合并** | 会计语义初稿，不是 Quality v2 生产规则 |
| 财务数据身份/版本一致性 P0 | **未实现，下一阶段最高优先级** | XOM 等案例的同-asof 财务内容差异尚未闭环 |
| 专业会计口径、Entry 完整解释与 v2 政策 PR | 尚待研究/开发 | 继续保持 Quality/Entry/Action v1 政策冻结 |
| v2 独立前向验证与生产推广 | 尚未开始 | 需要冻结候选政策、全新样本及 v1 比较 |

## 2. 本轮核实的 GitHub 状态

截至检查时：

- `main`：**`cf0f0585c861ec933a9050c73dcc060f28ceb9fd`**，即 PR #63 合并提交；[main CI 成功](https://github.com/AT2018cow/us-ai-stock-scanner/actions/runs/38336508980)。上一基线 PR #62 合并提交为 `f1090f1dc6694125460c1f77132ea0cebdad8526`。
- `evidence-observations`：**`69cc9930938ec3410f4426422a4251ce2771fa72`**，为冻结 Generalized-v0 实验证据提交。
- PR [#58](https://github.com/AT2018cow/us-ai-stock-scanner/pull/58) 已合并：历史研究协议、Modal pre-strategy 数据集入口、收益标签纠错/公司行为测试。
- PR [#59](https://github.com/AT2018cow/us-ai-stock-scanner/pull/59) 已合并：ticker/CIK/SEC 实体身份校验、旧缓存版本保护和溯源。
- PR [#60](https://github.com/AT2018cow/us-ai-stock-scanner/pull/60) 已合并：Action List / Detailed Report 的证据、风险、时效性与人工复核说明。
- PR [#62](https://github.com/AT2018cow/us-ai-stock-scanner/pull/62) **已于 2026-10-13 合并**：首轮业务模式 Quality 研究、归因、Entry 解释诊断。最终 PR head `1d96944f279495d804503f762da5d52b7319fd58`，合并提交为当前 main。
- PR [#63](https://github.com/AT2018cow/us-ai-stock-scanner/pull/63) **已合并**：只改 `AGENTS.md` §11，明确重计算优先 Modal `at2018cow` workspace；对应 main 合并提交 `cf0f0585c861ec933a9050c73dcc060f28ceb9fd`，CI 通过。
- PR [#61](https://github.com/AT2018cow/us-ai-stock-scanner/pull/61) 已关闭、未合并（曾为 DO NOT MERGE 集成测试 PR）。
- **新对话必须再次查询当前 GitHub 状态；以上 SHA 是交接基准，而不是永久固定的最新版本。**

## 3. 不可更改的产品方向

```text
US Core Universe ----------+
Thematic Universe ---------+--> 来源可追溯、可版本化的候选股并集
Manual Research Universe --+                     |
                                                 v
                                 Company Quality × Entry Quality
                                                 |
                                                 v
                                    canonical StockDecision
                                                 |
                                       Action List (约 5–15 只)
                                                 |
                                          Detailed Report
```

- AI 只是一类可选研究主题，**不是全部美股候选池**。旧 `core_ai`、`ai_enabler`、`ai_peripheral`、`ai_smallcap` 仅是历史发现来源，不能充当业务模型/行业分类或 Quality 评分输入。
- 候选发现、业务模式分类和研究主题应相互独立。
- Quality 判“公司业务/财务质量”，Entry 判“进入时机/价格结构”，不能仅通过一段未来收益直接宣称 Quality 优劣。
- 单一 canonical `StockDecision` 驱动 Action List、详细报告；无自动交易、仓位管理、经纪商下单。
- 尽量用 **outcome-sized PR**：一个明确目标包括实现、测试、文档及验证证据；仅在正确性阻断或归因需要时拆出小 PR。
- 日常实验提交普通可浏览文件到 append-only `evidence-observations`；不用 ZIP、通常不建 evidence-only PR；附 `SHA256SUMS` 和完整证据 commit SHA。
- 不修改或重新解释已有 v1 正式前向历史，冻结实验不可重写；如将来推广 v2，创建独立版本系列。

## 4. 首轮 Generalized-v0 实验：已完成

**证据位置**：

https://github.com/AT2018cow/us-ai-stock-scanner/tree/69cc9930938ec3410f4426422a4251ce2771fa72/runs/generalized-v0/2026-10-12_2d89194_generalized_v0_20261012_01

使用注册的、冻结的 **PR #57 精确代码 `2d891944...`**（不是当前 main）、原配置/政策和 2026-10-11 注册的 62 股候选池；决策会话是 **2026-10-12**；**非 `--formal`**。

主要事实：

- 三源合计 **75 来源成员关系 → 62 不同证券**；来源拒绝 0，Universe 排除 0，`StockDecision` 62 条，未发生静默股票替换。
- 验证器 PASS，Daily/Weekly Action List 各 **15 条**，与 snapshot 一致。
- PIT IEX bars 研究导出 **76/76 个证券序列、9,728 行**；原始行情受许可限制未提交，保留 manifests、哈希、覆盖与重抓方法。
- Liquidity 研究：**62/62** 满足 20 session 同源覆盖，已登记的代理指标零分歧；不能据此证明 SIP 交易量/真实执行容量，也不能更改 $2m 单日 snapshot 前置 gate。
- Entry 研究：**62/62** 拥有至少 61 个与 QQQ/SPY 对齐的 session；这是 trailing 对照，不是前瞻收益。
- Quality 分布：**24A / 31B / 5C / 2 UNRATED**（PR #57 冻结版本，不能和 #59 新身份保护的等级混为一谈）。
- Action 分布：**6 PRIORITY_REVIEW / 3 WATCH_PULLBACK / 7 WATCH_BREAKOUT / 39 HOLD_MONITOR / 7 AVOID**。
- 最新 filing/Company Facts 覆盖对 **HON** 触发一次可见警告；银行/券商/REIT 的会计适用性不确定性在样本中显现。
- 审核结果：**Engineering GO、Universe/provenance GO、Liquidity coverage/diagnostic GO、Quality diagnostic GO、Entry diagnostic GO、Action/Attention engineering GO**。但跨模式 Quality 的可信可比性、实盘可执行流动性、策略未来有效性均**未证明**。

限制：原先一批 IEX 缓存的旧尾（47 名末日 09-25）是已记录的 bulk-cache 陈旧问题；后来小批次查证 10-12 行情完整，没有将错误缓存用于冻结证据。须列为独立 P1 工程加固，不需要重跑已封存实验。

## 5. 同一对话中完成的其他主要工作

### 5.1 历史研发 H1–H3 与收益标签纠错

- 在 Modal Workspace `at2018cow` 用 1–2 vCPU、8–16 GiB 的顺序重型容器提取 2023-01 至 2026-03 月度历史数据；Quality 与 Entry 各 **25,025 行、670 证券、39 信号日期**。
- 历史 ETF/AI watchlist 不是严格 PIT 候选池：`union_superset_approx`；只适合机制诊断，不能当做通用美股正式 OOS 研究。
- 初轮发现 Quality A/B 未来 QQQ 超额弱于 C、`WATCH_BREAKOUT` 含多种不同结构、15 名关注清单压缩以及 B+ENTRY_READY 路由问题；不因为这些结果直接调权重。
- 发现金融行情公司行为标签错误：BKNG/KLAC 未来持有期的拆股查询截止日期不全；WOLF 破产重组前后证券权益无法按 ticker 原始价格直接计算收益。修复拆股事件 horizon、将无法可靠重建的 WOLF 标签置空，并重新生成研究证据。
- 最终证据：[历史修复后 `_03`](https://github.com/AT2018cow/us-ai-stock-scanner/tree/a3bec3d9ae4164f450c94c546d57d36a5d63e063/runs/historical-selection-v1/historical_selection_v1_20261011_03)；[分母/容错附录](https://github.com/AT2018cow/us-ai-stock-scanner/tree/eb68688f9d1bbeb814a2b4ecb96cbf861782dfbb/runs/historical-selection-v1/historical_selection_v1_20261011_03_addendum1_20261011)。评级总数 25,025；有 5 个 WOLF 120d 标签失效，120d 有效数 25,020。
- 结论：历史研究代码与标签修复工程 GO；旧样本不能直接证明 Quality 有 alpha；只比较同日期同候选池的 v1 vs 候选，不准大范围调参；旧 `E-first` 排序并未提供有说服力的增益。
- **遗留工程事项**：独立 `src/ai_value_scanner/backtest.py` replay 路径曾存在公司行为接口失败后继续的 fail-open；在使用该路径出正式收益报告之前应加固，未因研究提取器 fail-closed 而自动解决。

### 5.2 62 股 × 3 历史日期后验功能检查

证据：[posthoc-62-diagnostic-v1](https://github.com/AT2018cow/us-ai-stock-scanner/tree/6e9658c63d0e242fd3e95d22a95b799ade3caf6/runs/posthoc-62-diagnostic-v1/posthoc_62_20261011_01)。

- 2026-09-30、10-05、10-09：每日期 **62 唯一证券 / 62 决策**，0 股票 Universe exclusions；186 决策无未来 as-of。
- 业务 Quality 分级 26A/28B/6C/2U 在这三个日期不变；Action 与 Entry 可以变化。
- **均标记 `retrospective_posthoc_cohort`**；因 62 股 roster 在 10-11 才冻结，不能冒充这些历史日期的 PIT 成分。
- Report Phase 2 实现已并入 PR #60：同一个 `StockDecision` 的 Action List / Detailed Report 同步展示 Quality、Entry、Action、风险、证据、as-of、人工复核条件，不在 renderer 内独立算策略。

### 5.3 证券身份保护 PR #59

- 引入 ticker→CIK→SEC filing 经营主体的核对；明示已知绑定错误/显式不能验证时 Quality 走保守路径 `UNRATED`。
- parsed-fund 缓存升级 v7→v8，防旧缓存绕过身份检查；CIK、申报实体名进入决策 provenance，报告可提示。
- 不要误以为已根除 XOM 问题：**XOM 同一财务 as-of 的来源内容与实体经济口径跨运行不一致**，需要新的逐运行快照/指纹；仅一个 as-of 日期不足以证明是同一组原始事实。

### 5.4 跨商业模式 Quality 研究 PR #62：已完成首轮并合并

代码和文档（当前 main）：

- `docs/business_model_quality_v0/research_protocol.md`
- `docs/business_model_quality_v0/quality_failure_cases.md`
- `docs/business_model_quality_v0/candidate_interpretation_policy.md`
- `docs/business_model_quality_v0/reviewer_notes.md`
- `data/research/business_model_quality_v0/company_identity_and_pit_inventory.csv`
- `data/research/business_model_quality_v0/accounting_semantics_matrix.csv`（**15 指标** × 三种业务模型的初步语义矩阵）
- `data/research/business_model_quality_v0/quality_driver_attribution.csv`（11 家真实 scored vs missing vs inapplicable）
- `data/research/business_model_quality_v0/entry_readiness_diagnostics.csv`（11 家 × 3 日期 = 33 行）
- `data/research/business_model_quality_v0/silent_gate_inputs.csv`
- `research/build_entry_diagnostics.py`，`tests/test_entry_diagnostics_rebuild.py`

样本：银行/券商 JPM、BAC、GS、MS；REIT AMT、EQIX、O、PLD；普通运营 ABBV、AAPL、XOM。

关键研究结论/限制：

1. **银行 C 的真实评分归因**：JPM、BAC、MS 的 v1 风险主要来自 OCF 比率或增速；`net_debt_to_ebitda`、`interest_coverage`、`current_ratio` 多数是 **MISSING**，没有直接给负面分。应分开“实际负面评分、数据覆盖缺失、模型会计不适用”；BAC 盈利组件分数可为 1.0，不是全面走弱。
2. **GS** 财务实体可核对，但券商式 revenue XBRL 词汇未被 v1 映射覆盖，UNRATED 不能简单解释为公司经营差。
3. **REIT** 的 GAAP 净利、经营现金流、FCF、杠杆/流动性和 FFO/AFFO 专业语义尚未对齐；现有 B 不代表跨模型可比。
4. **XOM P0**：2026-10-09 posthoc UNRATED（14 missing）与 10-12 冻结实验 B（含 opco 规模 FCF $19.263B），即使 `data_asof` 同为 2026-08-03，也不能直接认为来自同一稳定原始经济实体/内容。原始运行的 ticker map、SEC 内容指纹/抓取时间未归档。曾观测到不同大小的缓存，但**原因可能是自发重抓覆写，不得断言是 provider 翻转**。
5. **PLD**：2026-07-29 Q2 10-Q 已可在 submissions 查到，但 Q2 accession 在当时 Company Facts 快照中缺失，Quality as-of 滞留 Q1；SEC endpoint 延迟和缓存 TTL 影响尚未分离。
6. **HON/FCX/NEE 同-asof 或跨版本评级变化**：分别需区分 integrity 保护、阈值边际、真实财报更新；不可把所有变化归因于同一个机制。
7. **Entry 静默门**：RS 60d 在 [-10%,-3%)、ret60 在 [-8%,0%) 等范围可能未产生独立负面 EvidenceItem。EQIX/AAPL 有真实示例。新版脚本从原有风险或提交的 `silent_gate_inputs.csv` 重建，否则写 `UNOBSERVABLE`；非 READY **绝不可写全部条件满足**。
8. 本轮审核曾独立复核 33 行新诊断表，与冻结 decisions/manifests 逐字段一致 **0 差异**；旧版相比仅 EQIX 10-05 的证据措辞变化。该行 -0.90% 来自提交的冻结二级输入，原始 IEX 可变缓存没有在 Git 留下完整原始行情，保留此限制。
9. 每家公司业务模式的 SEC filing 引用、报告币种和专业解释验证未完全闭环；**PR #62 是研究初稿及方法 GO，不代表生产 Quality v2 GO**。

## 6. 当前剩余问题：按优先级和边界处理

### P0：Financial-data identity & version consistency（最优先）

拟独立 **outcome-sized correctness PR**（当前尚无该 PR 的已确认实现）：

- 每次扫描**冻结 ticker→CIK 映射**（证券身份、来源、获取时间、完整 SHA256）；映射版本进入 run manifest。
- per-symbol：保存 SEC submissions 查询 CIK/实体名、ticker 列表、10-K/10-Q accession/filing 日期、Company Facts 查询 CIK、来源类型、抓取时间、原始响应内容指纹、会计单元和关键 tag 统计。
- SEC filings 与 Company Facts 原始事实做实体与版本核对；跨实体事实不能在同一个 Quality 中静默拼接。
- 同 symbol/同 data-asof 却内容 SHA 不同时，在**研究跨运行比较**中标记 `UNCOMPARABLE`，不得选择有利结果；生产新保护应另行证明回退行为，不擅自新增 Quality 评级类型。
- 命中缓存也必须核对身份/版本；重新计算不可使用来源无法复现的旧快照。
- XOM 为 P0 主案例，HON、FCX、NEE、PLD 作为不同机制的对照；测试：映射错误/未证实、旧缓存、缓存变化、接口失败、有效 filing 延迟、same-asof 内容变化。
- 以现有缓存 + 合成测试优先，不在 P0 内重跑完整历史研究。对代码/结果/数据 provenance 清楚分开审查。

### P1：专业会计语义研究（可以和 P0 并行）

- 固定 11 家已登记研究样本；逐公司拿到可核对的 10-K/10-Q、SEC accession、filed/published 日期、货币单位、业务模式的有依据标识、XBRL tag 和计算方式。
- 银行与券商：利息净收入、信用损失、CET1、净核销、券商佣金/投资银行收入、金融业务 OCF 解释。
- REIT：FFO/AFFO 调节、维护资本开支、Same-store NOI、Debt/EBITDAre、fixed-charge coverage；核实是否存在 Nareit/公司特定非 GAAP 定义差异。
- 普通经营企业 ABBV/AAPL 为通用核心参照；XOM 身份未完成之前不判定其评级质量。
- 对 15 指标逐项归类 `applicable / needs-specialist-interpretation / inapplicable / unverified`，保留原始证据和反例，不改变权重/阈值。
- 交付研究文档、11 家 PIT 事实/口径表、案例比较矩阵、差异说明与 reviewer notes；审核后再定是否做统一核心 + 少量专业解释的 Quality v2 候选。

### P1：Entry evidence completeness（在合适时候）

- 只让已有 READY 条件的未满足原因更完整、更诚实；可在不改 Entry 状态逻辑的前提下改 EvidenceItem/renderer；未知的保持 `UNOBSERVABLE`，不得捏造指标。
- 保持 QQQ regime、现行 READY 条件、Action 映射与 attention cap 15 作为 v1 comparator；有充分独立研究后才另议政策调整。

### P1：IEX bulk-cache stale-tail 硬化

- 已知部分批次缓存末日停在 2026-09-25，而 provider 2026-10-12 数据已经可用。
- 在 `AlpacaClient.get_daily_bars` 增加缓存尾部/请求目标 session 有效性检查；不满足则按协议补拉或明确 STALE；针对 47 名旧尾构造单测。不要混进财务 P0 以免归因混杂。

### 其他遗留

- 旧 replay 路径公司行为失败继续运行（fail-open）：未来该路径要生成正式收益报告之前加固。
- PR #63 `AGENTS.md` Modal-first 文档变更已合并且 main CI 绿；历史本地 stash 的处理仍需本人自行确认，不能自动丢弃。

## 7. 何时做 Generalized Selection v2 政策 PR？

**不是立刻上线。** 原交接第 9–11 节要求：

1. 先完成 P0 财务事实身份/版本追踪并独立评估影响，再完成专业会计语义的最低可信证据；Entry 解释完整性可以独立完善。
2. 然后在证据支持的组件上设计 **一个可归因的、coherent Generalized Selection v2 候选 Policy PR**，必要时把 P0 correctness 工程独立拆分。
3. 必须保持 Quality / Entry / Liquidity / Attention 的 v1 comparator；逐组件与组合版对照，不拿 62 人工选股池调大量权重。
4. 选股池、日期、指标、评估合同在独立验证样本出现之前冻结；明确历史 posthoc、已有诊断数据、前向数据的等级差异。
5. 至少一个真正独立的 prospective 或经审计可用的时间隔离样本，才讨论 v2 默认策略推广。
6. 旧 v1 formal/prospective 历史不可修改；新 generalized-v0/v2 序列独立版本化；未明确批准，不运行 generalized `--formal`。

## 8. 与用户的协作/工具约束

- 用户独立运行研发，ChatGPT 担任 **关键阶段独立技术审核和设计指导**；除用户明确请求，不应主动编辑 GitHub、创建或合并 PR。
- 审核必须实际查看 GitHub 的 **精确 HEAD SHA、CI、代码 diff、可浏览证据目录**，尽量独立复算关键小样本；结论分维度写出 GO/INCONCLUSIVE/NO-GO、具体阻塞项和重新审核条件。
- 不需要用户分享 Alpaca/SEC 账号密钥、SEC 身份；不要提交 `.env`、raw private caches、未授权分发 IEX bar、不可公开的 manual research notes。
- 长任务优先 Modal **`at2018cow` Workspace**，按实际 CPU/内存和缓存竞态设定合理并行；前台、显式 profile、不 `--detach`；已存在数据优先复用，小型分析本机运行即可。PR #63 已将该规范合并至 AGENTS.md。
- `evidence-observations` 为 append-only，每个研究 run 单独目录+完整 commit SHA+`SHA256SUMS`；证据不重复用 ZIP 提交。

## 9. 新对话建议的执行顺序

1. 读取原交接、本摘要、当前 main 的 `AGENTS.md`、Generalized-v0 协议、#62 研究成果。**先核对仓库最新状态**，不要假定上述 SHA 仍最新。
2. 确认 PR #63 的合并状态及该合并提交的 main CI；如 GitHub 后续又有变更，以最新状态为准。
3. 明确从 **财务身份与版本一致性 P0** 启动下一份 correctness 工程 PR 的研究合同与验收矩阵；检查有无新 PR 或已有实现避免重复。
4. 并行继续银行/券商/REIT 专业会计语义研究，遵守 11 家固定样本、SEC filing 实据与美元单位验证。
5. P0 证据与专业解释达标后，提出 outcome-sized 的 v2 候选 Policy PR（Quality/Entry/Liquidity/Attention 中只改有证据组件）；优先验证解释、事实可靠性、Action List / Detailed Report 一致性，不急于调历史收益。
6. 新政策进入至少一份独立前向/时间分离验证前，不宣称生产 GO，也不改变既有正式 v1/prospective 记录。

## 10. 可以直接复制到新对话的启动消息

> 请继续担任 GitHub 项目 `AT2018cow/us-ai-stock-scanner` 的技术审核顾问。我会自己开发和执行，你负责关键节点的独立证据审核、方向建议、GO/NO-GO 判断；未经我要求不要直接改代码或合并 PR。
>
> 首先阅读原始交接 `docs/handoff-after-pr57-20261011` 分支中的 `docs/work_handoff_after_pr57_20261011.md`，以及同一交接分支中的 `docs/work_handoff_after_pr62_20261013.md`（本文件）；然后重新核对 GitHub 的 `main`、`evidence-observations`、PR #62/#63 与 CI，不要把旧 SHA 当成当前 HEAD。
>
> 最新已知状态：main `cf0f0585c861ec933a9050c73dcc060f28ceb9fd`（PR #62、#63 均已合并、main CI 通过）；证据分支 `69cc9930938ec3410f4426422a4251ce2771fa72`；2026-10-12 冻结 PR #57 代码 `2d891944...` 的 62 股/75 来源 Generalized-v0 非 formal 实验与五维工程/诊断审核完成；PR #58/#59/#60/#62/#63 已合并，PR #61 关闭未合并（如有变化以 GitHub 实时状态为准）。
>
> 原交接已推进到“首轮 generalized-v0 evidence GO、准备 Generalized Selection v2 证据支持的候选政策”阶段。但 **P0 财务数据 ticker→CIK→SEC submissions/Company Facts 身份、内容版本和抓取指纹一致性**尚未闭环，XOM 同-asof 决策不一致；银行/券商/REIT 的专业会计语义及 11 家 SEC 来源实据仍需补齐。Entry READY 的静默条件解释、IEX bulk-cache 旧尾和 replay split fail-open 也是后续事项。
>
> 请先核实现状，再帮我把下一步 **P0 财务数据来源一致性工程**和**专业会计语义研究**制定为清晰、可测试、证据可追溯的任务，给出实施顺序、验收标准、资源预算与交付证据，不改现行 Quality/Entry/Action 权重或映射，不重复过去已经完成的实验，也不提前推动 v2 生产部署。