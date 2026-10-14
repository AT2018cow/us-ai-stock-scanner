# MVP 开发交接 — PR #45 后（2026-10-11）

> 接手时优先读 `AGENTS.md`、`docs/product_direction_low_frequency_manual_selection.md`、`docs/mvp_design_low_frequency_manual_selection.md`，以及本文件。以 GitHub 最新 `main` / PR 真实状态为准。本文件是工作交接，不取代 MVP design。

## 1. 产品北极星与当前范围

目标：**低频、人工最终决策的美股选股辅助系统**，帮助用户回答：

- 哪些公司值得长期研究 / 持有？（Company Quality）
- 当前是否适合开始或等待？（Entry Quality）
- 今天/本周应该优先研究哪些？（Action List）
- 为什么？证据有哪些、缺失哪些、什么变化触发复核？（Detailed Report）

确定性主链路：

`ETF-derived watchlist → live SEC/Alpaca → Company Quality v1 × Entry Quality v1 → canonical StockDecision / Action State → Daily/Weekly Action List + Detailed Report → immutable prospective snapshot`

Production Action List / Detailed Report 只能渲染同一 canonical StockDecision；不能各自重新计算状态。继续保持 legacy low_value / momentum / industry_trend / research_pool 输出兼容。

明确不在 MVP 中扩张：broker、account-NAV、自动下单、portfolio optimization、全面 IFRS/FX、ETF 历史持仓重建、大范围 historical-return 参数优化或 ML opaque scoring。

## 2. 已完成的工作与证据

- PR #35：Decision contract / render skeleton，统一 `StockDecision` 与 JSONL。
- 后续 Company Quality v1 / Entry Quality v1：冻结 policy 和历史 cohort/replay 诊断。
- PR #38：整合 Daily/Weekly Action List、Detailed Report 与 immutable snapshot。
- PR #39：增加 `python scripts/run_mvp_full_scan.py` 一键实验 full scan 和 snapshot validation。
- PR #40：首轮实际 scan evidence，发现 SEC filing freshness、foreign issuer coverage 和周末 decision date 问题。
- PR #41：market-session decision date、latest periodic filing/facts coverage、non-USD fail-closed 修正。
- PR #42：修正后的 evidence；普通 10-Q 仍有 coverage gap，促成 narrow SEC diagnostic。
- PR #43：EdgarTools parity diagnostic（不影响 production）。
- PR #44：EdgarTools parity evidence；显示 filing-level core concepts 可读，但**concept presence ≠ 当前 TTM 能够可靠重建**。
- PR #45：ordinary USD 10-Q exact-filing fallback 的实现候选。**此文档写入 PR #45 分支；合并及真实环境验证状态须新对话重新核对。**

重要：PR #44 是 evidence PR，不能把“核验通过”直接等同“已合并”。接手后务必核实 #44/#45 及最新 main 状态。

## 3. PR #45 的严格边界

PR：`https://github.com/AT2018cow/us-ai-stock-scanner/pull/45`

预期行为：

1. SEC Company Facts 始终是 primary source。
2. 只有 latest periodic form 是普通 `10-Q`、而 recognized core Company Facts 未覆盖 exact accession 时，才尝试 EdgarTools。
3. 只接受 exact-filing **undimensioned consolidated standard `us-gaap` USD** core Revenue / Net Income / OCF facts；不能混入 segment/dimensional、IFRS、custom-only、非 USD。
4. 只构造 Company Facts-compatible 的内存补丁；调用仓库现有 FactRecord、quarter/YTD/TTM reconstruction、accounting、Company Quality v1。**绝不增加第二套 accounting/Quality 引擎。**
5. 仅当三类 core flow 的 latest rolling TTM 均由该 latest accession 驱动，补丁才有效；否则恢复原始内存 facts，保持 `UNRATED` fail-closed。
6. 不修改原始 SEC/Alpaca cache；fallback status/source/version/count 必须进入 canonical provenance 和 validator。
7. 不修改 historical/replay revenue tag contract、不修改冻结的 Quality/Entry 阈值或 Action mapping。
8. 外国发行人（20-F/40-F）、IFRS/非 USD/custom-only 仍拒绝。

**在 PR #45 合并前**，审查最终 exact-head CI、merge base drift、上述 8 个 invariant 及 mock regression；**合并之后仍必须做一次有凭证环境的 experiment full scan**，不能因为模拟单测通过就直接进行正式 prospective run。

## 4. 短期（接下来的 1–2 个 PR / 数次扫描）

最高优先：

1. 审查并合并 PR #45（只有最终 exact-head CI 绿色、review 问题关闭后）。
2. 在 Alpaca/SEC credentialed 环境运行 `python scripts/run_mvp_full_scan.py`，**不要加 `--formal`**。
3. 严格按照 PR #45 的 **Review evidence to submit** 提交独立 evidence PR：
   `evidence/mvp_edgartools_fallback/<decision_date>_<code_sha7>/`
   必需 `README.md`、`run_manifest.json`、`validation.json`、`decisions.jsonl`、`action_list.md`、`weekly_review.md`、`detailed/`、`full_scan.log`、`ai_watchlist.csv`、`ai_watchlist.sha256`、`fallback_cases.md`。
   `fallback_cases.md` 必须包含 EXLS/JCI/PYPL/CDNS/NXPI/NEE/TTAN/TSM/ASML/SAP 和所有实际 fallback / 异常 status。
4. 审核：
   - ordinary USD 10-Q 真正恢复最新 accession 的三个 core TTM；
   - 不支持的案例仍 fail-closed，Company Facts controls 基本稳定；
   - data_asof、currency、fallback provenance 正确；
   - Daily/Weekly attention cap≤15、renderer 与 JSONL 一致、validator PASS；
   - SEC network/latency 没有显著不可控回归。
5. **Stop rule**：如果没有新的会造成错误投资判断的高频 correctness defect，就立即停止 SEC 扩张，开始第一份正式不可变 prospective snapshot：`python scripts/run_mvp_full_scan.py --formal`。

不要为了提高 coverage 百分比而添加 IFRS/FX/custom taxonomy 平台，不要重新调 Quality/Entry 阈值。

## 5. 中期（4–12 周）

重心从“开发功能”转成“实际使用与验证决策价值”：

- 周期性运行单一 canonical MVP 配置，保存 prospective JSONL/manifest；每日观察与每周人工复核少量候选。
- 记录人工决策：接受/搁置/拒绝原因、缺失信息、review trigger 是否可操作、重复候选/状态抖动。
- 分析 Action List 是否稳定聚焦 5–15 名，是否因为 cap 遮挡 `PRIORITY_REVIEW`，是否过度集中于非 AI peripheral names。
- 检查 Company Quality / Entry Quality 的 missing、stale、confidence、market regime，不把 retrospective outcome 反向用于 v1 threshold tuning。
- 经 parity test 后可考虑单独引入中性 `config.mvp.json` 作为唯一产品入口；保留 `risk_on/off` 的 legacy reproducibility，不同时维护两套 canonical 产品。
- 需要调整展示或 audit 体验时，优先做低风险 small PR；保留 snapshot schema compatibility。

## 6. 长期（3–12 个月，需证据触发）

- 利用冻结的 prospective 决策序列，开展 20/60/120d outcome、QQQ-relative benchmark、分年份/市场 regime、集中度与 persistence 评估；避免 overlapping-horizon 统计显著性误读。
- 版本化迭代 Quality/Entry policy，只有足够 prospective/OOS 与实用性证据后才发布 v2；不可追改旧 snapshot。
- 逐步提升人工分析报告中的可解释性与研究闭环（财报来源、风险、复核触发），不是堆指标。
- **条件式**扩张数据覆盖：只有明确改变核心候选覆盖且有清楚会计/PIT 定义时，才评估 IFRS/FX 或新的数据源；否则继续 fail-closed。
- 更远期的 broker、portfolio、NAV 等须另行产品立项，不默认纳入本 MVP。

## 7. 新对话的首个动作

请从这里开始：

1. `main` 当前 SHA 与 PR #44/#45 状态、最终 CI。
2. 审核/合并 PR #45（若仍 open）。
3. 使用 PR #45 中 `Review evidence to submit`，指导实验环境跑一次 **experiment** full scan。
4. 审核 evidence，明确给出 **formal prospective observation GO / NO-GO**，不要反复增加 SEC 范围。
5. 确认 GO 后才执行 `--formal` 并建立长期 observation cadence。

## 8. 工程与安全纪律

- 每次 PR 只解决一个清晰目标，先审代码、尽量复用、不做无必要重构。
- 严格遵守 `AGENTS.md`；提交 PR 时必须确保**最终 head 自己的 CI** 全绿。
- 涉及外部实验，PR 描述必须包含 `Review evidence to submit`：命令、环境/依赖、提交路径/文件、敏感数据禁止项及 review criteria。
- 从不提交 `.env`、SEC/Alpaca identity/keys、raw SEC/XBRL caches、EdgarTools caches 或不必要大文件。
- **永远不要使用 Modal `--detach`**。
