# 新对话启动 Prompt — US AI Stock Scanner（2026-10-13）

> 此 Prompt 优先以 GitHub 文件为交接源，不再依赖上一段聊天记录或聊天附件。上次对话总结已按原文件字节提交；后续 GitHub 状态应实时核对。

## 必读交接（按顺序）

1. **原始 PR #57 权威交接**：[work_handoff_after_pr57_20261011.md](https://github.com/AT2018cow/us-ai-stock-scanner/blob/docs/handoff-after-pr57-20261011/docs/work_handoff_after_pr57_20261011.md)。
2. **截至 2026-10-13 的完整对话交接和实际进度**：[work_handoff_after_pr62_20261013.md](https://github.com/AT2018cow/us-ai-stock-scanner/blob/202dd4428037b1b6bc6b12f9e61132bf2c941e4a/docs/work_handoff_after_pr62_20261013.md)。这是**精确固定提交** `202dd4428037b1b6bc6b12f9e61132bf2c941e4a`，与上一轮交接原文件字节一致。
3. 仓库最新 `main` 上的 `AGENTS.md`、`docs/generalized_end_to_end_research_v0.md`、`docs/business_model_quality_v0/research_protocol.md` 及 PR #62 研究证据。

## 可直接复制到新对话的消息

请继续担任 GitHub 项目 `AT2018cow/us-ai-stock-scanner` 的技术审核与开发决策顾问。我负责独立执行开发与实验，你在关键阶段检查准确代码版本、CI、可复现证据，并给出 GO / INCONCLUSIVE / NO-GO、阻塞问题和下一步指令。未经我明确授权，请不要修改仓库、合并 PR 或启动付费实验。

**首先读取 GitHub 上的两份交接文档：**

- PR #57 原始交接：https://github.com/AT2018cow/us-ai-stock-scanner/blob/docs/handoff-after-pr57-20261011/docs/work_handoff_after_pr57_20261011.md
- 本轮完整交接（固定 commit）：https://github.com/AT2018cow/us-ai-stock-scanner/blob/202dd4428037b1b6bc6b12f9e61132bf2c941e4a/docs/work_handoff_after_pr62_20261013.md

然后核查当前 `main`、`evidence-observations`、所有相关 PR 和 CI 的最新状态。上一轮最后核对的基准是 `main=f1090f1dc6694125460c1f77132ea0cebdad8526`，`evidence-observations=69cc9930938ec3410f4426422a4251ce2771fa72`；PR #58/#59/#60/#62 已合并，PR #61 已关闭未合并，PR #63 尚待合并。这些只是历史基准，不得取代实时检查。

原始 handoff 中 PR #57 的 2026-10-12 冻结 Generalized-v0 实验已经完成：75 个来源成员关系、62 只股票、非 `--formal`，其 Universe、Liquidity、Quality、Entry、Action 工程与诊断阶段审核 GO；**并不代表 v2 生产/收益 GO**。历史 Quality/Entry/Action 研究、公司行为收益标签修复、基础证券身份保护、Action List / Detailed Report 改进和 11 家跨商业模式初步研究也已经完成。

**当前要先推进两条并行工作轨道**：

1. **P0 财务身份和版本一致性工程**：冻结 ticker→CIK 映射、SEC submissions 与 Company Facts 的实际实体、取得时间及内容 SHA，保证跨实体拼接或 same-asof 内容变更不会导致静默且不可比较的 Quality 评级。XOM 为主要反例，HON/FCX/NEE/PLD 为不同机制的对照。
2. **银行、券商和 REIT 的 Quality 专业会计语义研究**：复用已登记的 11 家样本，核验业务模式、10-K/10-Q、filing accession、报告货币和会计事实，区分实质负面分、覆盖缺失和模型不适用；研究专业解释而非盲目改权重。

Entry READY 静默条件的证据完整性、IEX bulk-cache stale-tail 和旧 replay 公司行为 fail-open 均作为后续加固事项。

请先根据真实 GitHub 状态确认是否已经有上述工作的 PR，避免重复创建。随后为 **P0 correctness PR** 和 **专业会计语义研究** 设计具体实施顺序、测试、失败保护、证据目录、资源预算及审核门槛，保持 Quality v1、Entry v1、Action、QQQ、IEX 流动性门槛和 v1 正式历史不变。仅在证据足够时提出一个 coherent、outcome-sized Generalized Selection v2 候选 Policy PR，且不要直接推广生产。

需要重型实验时优先 Modal `at2018cow` workspace、显式 profile 和前台执行，依据资源瓶颈设定并行；已有历史缓存优先复用，不重复已通过的昂贵实验。
