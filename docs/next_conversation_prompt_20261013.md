# 新对话启动 Prompt — US AI Stock Scanner（2026-10-13，已校准）

> 此 Prompt 优先以 GitHub 文件为交接源，不再依赖上一段聊天记录或聊天附件。
> **本文件中的所有 SHA 都只是编写时的检查点。下次对话必须先实时核对
> `main`、`evidence-observations` 和 PR 状态，不得把这里的 SHA 当成现状。**

## 必读交接（按顺序）

1. **原始 PR #57 权威交接**：[work_handoff_after_pr57_20261011.md](https://github.com/AT2018cow/us-ai-stock-scanner/blob/docs/handoff-after-pr57-20261011/docs/work_handoff_after_pr57_20261011.md)。
2. **历史定稿交接**（只读归档，不再改）：[work_handoff_after_pr62_20261013.md](https://github.com/AT2018cow/us-ai-stock-scanner/blob/docs/handoff-conversation-20261013/docs/work_handoff_after_pr62_20261013.md)。
3. 仓库最新 `main` 上的 `AGENTS.md`。

## 可直接复制到新对话的消息

请继续担任 GitHub 项目 `AT2018cow/us-ai-stock-scanner` 的技术审核与开发决策顾问。我负责独立执行开发与实验，你在关键阶段检查准确代码版本、CI、可复现证据，并给出 GO / INCONCLUSIVE / NO-GO、阻塞问题和下一步指令。未经我明确授权，请不要修改仓库、合并 PR 或启动付费实验。

**首先实时核对 GitHub 状态**（`main`、`evidence-observations`、开放 PR、CI）。编写本 Prompt 时的检查点是 `main=11cc71ddc0d9dadb286d66c61e9782b8c3a6821b`（已含 #58/#59/#60/#62/#63/#64），`evidence-observations=fd8328b389a0efe0c300ce8654dd30448ef8f265`，唯一开放 PR 为文档交接 #65 —— **均须重查，不得直接沿用**。

产品北极星（[产品方向](https://github.com/AT2018cow/us-ai-stock-scanner/blob/11cc71ddc0d9dadb286d66c61e9782b8c3a6821b/docs/product_direction_low_frequency_manual_selection.md)）：**Company Quality × Entry Quality → 5–15 个可人工复核的 Daily/Weekly Action List → 同源 Detailed Report**。目标是让人快速知道“该看谁、为什么、风险是什么、下一步等待什么”，不是完备会计平台或自动交易。

**当前唯一最高优先级（NOW）：一次有界的 Action List 使用验收，先读现有产物，不启动新重算。** 用已冻结的 Generalized-v0 证据（62 decisions / Action List / Detailed Report，注意这是**历史可用性样本，不是今天的投资推荐**）逐项复核：Quality/Entry/Action 同源性、理由与反证具体性、as-of/CIK 可见性、失败保守降级、`WATCH_BREAKOUT` 是否被误读、前 5–15 名升级/降级/等待触发条件。输出简短真实用户验收表（symbol、Action、Y/N/unknown、拒绝原因、缺失证据、下一步可答性、top 3 blocker）。**能否赚钱不属于这轮 GO**；不足只就 top blocker 开有界修复 PR。不得重标旧快照为 prospective，不得为验收发起付费/全市场回放。

**NEXT（仅由 NOW 暴露的高价值缺陷触发）**：Entry 只修清晰度（补全非 READY 的 failed/unknown 门，不改状态/分数/阈值）；会计语义先保守分组（银行/REIT 维持 SPECIALIST_REQUIRED/UNVERIFIED，不做通用 v2）；前瞻效果靠真实未来观察自然积累，不做大规模参数搜索。**暂停**：全套专用财报引擎、历史 ETF 重建、仓位/NAV/自动下单、前瞻收益证明、无痛点基建重构。安全/身份正确性 bug 仍是硬阻塞，但已关闭问题不重开。

**协作规则**：各 PR Conversation 评论即任务合同；交接/roadmap 在文档 PR；review 只拦数据/判断错误、安全、不可复现；重型扫描另行批准。每个 PR 回答：它是否让明天的 5–15 名 Action List 更准确、更可理解、更值得看？
