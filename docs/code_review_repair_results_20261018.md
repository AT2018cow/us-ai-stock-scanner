# 代码审查修复结果：R01–R08 + A01/A02

日期：2026-10-18。状态：**已实现；R03–R05 已完成 Codex 独立复验并通过。**

- 审查基线：`3e68c0e531c2e96780844daaf0af594fb149da84`（PR #101，与交接文档一致）。
- 修复范围：`docs/code_review_and_repair_handoff_20261018.md` R01–R08；A01 已实施（行为保持重构），A02 补契约测试并明确延期扫描器拆分。
- 本轮全部验证离线完成，未使用凭证、未联网、未运行全量重放、未触碰任何冻结快照或原始研究证据。
- 修复前基线：1093 tests / OK；修复后：**1188 tests / OK**（`.venv/bin/python -m unittest discover -s tests`）。`git diff --check` 通过。
- 首轮交付后按独立复审回执修复了 3 项 FAIL（见文末“复审反馈修复记录”），上表与测试数已反映最终状态。

## 逐项结果

| ID | 状态 | 实现位置 | 测试及结果 | 行为/版本影响 | 剩余限制 |
|---|---|---|---|---|---|
| R01 | 已实现待验收 | `fundamentals/accounting.py`：`total_debt_source`/`net_debt_source`/`net_debt_to_ebitda_source`（reported/partial/missing），净债务需同报现金，两期存货缺失不再推断 not-applicable（显式双零视为报告零增长）；`decision/quality.py`：`_assess_numeric_metric(source_key=...)` 不完整披露只能产生风险、不能产生正面证据或覆盖率；scanner/backtest 行字段同步 | `tests/test_code_review_repair_r01_r02.py`（18 项，v1+v2），更新 `test_accounting_core`、`test_gap12_metrics`；OK | 影响质量证据与覆盖率/置信度；解析缓存与 effective/scoring hash 机制不变（无派生指标缓存）；策略版本号升级（见下） | 缺失债务/存货对全市场覆盖率的整体影响未量化；精确/部分披露的上游语义仍取决于 SEC 提取层 |
| R02 | 已实现待验收 | `fundamentals/accounting.py`：`growth_direction()` + `*_growth(_direction)` 字段（净利润/调整净利润/EBIT/调整EBIT/经营现金流）；`decision/quality.py`：`_assess_growth_metric`（亏损扩大→风险、收窄→0.65 恢复、扭亏→0.65 且非 strong、扭亏为盈反向→风险、零基数→incomparable missing；正基数路径不变）；v2 非经营替换改用归一化方向 | 同 `test_code_review_repair_r01_r02.py`：-100→-200 不再 strong；-100→-50 识别为收窄；-100→+100 扭亏非 strong；+100→-100 风险；0→+100 missing；100→+120 仍 +20%/strong；OK | 仅当输入包含方向字段时启用；纯旧字段 dict 保持旧解释（回测/旧证据可解释）；live/replay 共用 accounting 路径，结果一致 | 扭亏/收窄的分档为规则选择（先经济语义、未按历史收益调参）；负基数 EBIT 替换路径未单独调参 |
| R03 | 已验收 | 新增 `src/ai_value_scanner/market_calendar.py`（NYSE 会话、节假日、提前收市、`latest_completed_session`）；`decision/entry.py`：`runtime_reference_date` 参与年龄计算，4–7 天保留警告语义，>7 天仍旧 INSUFFICIENT；**market_asof 晚于运行时参考日期 fail-closed**（`market_data_ahead_of_reference` → INSUFFICIENT + freshness gate BLOCK），基准晚于参考日期同理（`benchmark_market_data_ahead_of_reference`）；新增 `benchmark_market_data_stale/severe` 基准滞后证据；`scanner.run_scan` 注入 `freshness_now_utc` 并记录 `runtime_reference_session`；replay 不传参考时钟、行为不变且遇 market_asof>decision_date 仍报错 | `tests/test_code_review_repair_r03_freshness.py`（19 项：30 天陈旧→INSUFFICIENT、4–7 天警告、周末/假日、单股滞后、符号/基准未来时间戳 fail-closed、基准滞后、正常新数据、replay 不变、注入时钟）；OK | live 决策证据与状态变化（陈旧缓存不再自称 fresh；未来/盘中混合时间戳不再产生 READY）；历史 replay 语义/结果不变；策略版本号升级；manifest 新增运行时参考会话 provenance | 日历覆盖 2020s 常规 NYSE 规则；提前收市仅影响 13:00–16:00 ET 的运行时刻；**交易时段内含当日未完成 bar 的手动扫描会按“未来时间戳”fail-closed 为 INSUFFICIENT（生产 cron 在收盘后运行不受影响）**；未做真实网络故障注入（用合成输入覆盖） |
| R04 | 已验收 | `scanner.py`：新增 `ScanRunStatus` / `run_scan_with_status`，`run_scan` 保留 `-> Path` 兼容；快照/报告/指针/shadow 各自结构化状态；`_evaluate_existing_snapshot_reuse` 校验完整性+身份（含 dated 策略版本）；multi-source 路径保持重抛；`scripts/run_daily_cron.py`：默认使用状态感知入口，**`main()` 先判 `scan_failed` 再判 `scan_executed`**，核心产物失败→非零退出并报告 stage，shadow 失败显式 partial | `test_daily_cron_scan_and_ttl.py`（core failure / version mismatch / 成功+partial shadow / reuse 完整性、版本不一致 / **main() 对“已执行但核心失败”退出 1**）、`test_code_review_repair_r04_r08_contract_e2e.py`（cron 端到端成功/失败）；OK | cron 失败语义、同日复用门槛；不再出现“CSV 成功但无本次 Action List”被当作成功 | 故障注入为单元级（monkeypatch/fake scan_fn），未做真实进程中断/并发实验；并发 writer 场景仅靠原子替换与日期单调性防护 |
| R05 | 已验收 | `scripts/validate_mvp_snapshot.py`：从 manifest 读取 policy/layout（旧 manifest 显式 v1 默认），未知版本报错不静默回退；按逐股 provenance 阶段版本选择 v1/v2 action mapper；**校验 manifest `quality_policy_version`/`entry_policy_version` 与逐股 provenance 一致且属于已知版本**；非对象 manifest 显式报错；**writer 写入 `report_renderer_revision`**，当前版本做字节级渲染校验，旧快照走结构化校验并给出显式警告，未知 revision 报错；v2 渲染传入完整 decisions；用共享 `collect_detailed_report_symbols` 校验所有被链接详情页；保留篡改/缺文件/重复/守恒检查 | `test_code_review_repair_r05_validator.py`（v2 B 晋升通过、v1 通过、混合组合、未知版本 fail-closed、v2 action 篡改、provenance 不一致、manifest 阶段版本篡改、非对象 manifest、未知 renderer revision、旧快照结构化通过+告警、旧快照仍抓缺失结构、缺详情页、渲染篡改）；`test_mvp_full_scan_acceptance` 等旧测试保持通过；两个本地冻结 v2 快照实测 `ok=True`（含 legacy 警告）；OK | 验收器正确性；生产 v2 快照可被正式验收（修复前必失败，2026-10-16 快照实测 34 个错误） | 历史旧快照不做字节级渲染比对（无 revision 标记，结构性校验 + 显式警告；这是无法重放旧渲染器的诚实上限）；混合阶段（q/e/a 不一致）不支持 |
| R06 | 已实现待验收 | `decision/model.py`：`EntryGateResult`（PASS/BLOCK/WARN/UNKNOWN/NOT_APPLICABLE + blocking + observed/target/reason/policy_version，序列化仅在非空时添加）；`decision/entry.py`：v1 单一评估产出 canonical gates（连贯性、对齐、波动、回撤、联合过热、防守条件、数据完整性），v2 追加 MA 排列与延伸警告；`view_model.py` 只格式化（旧快照 gate 显示“未记录”）；`_build_entry_blockers_inline` 来自 canonical blockers；`integrated._review_trigger` 接收决策，B 晋升文案与共享 mapper 阈值一致；详细报告标题改为动态门数 | `tests/test_code_review_repair_r06_gates.py`（READY⇔无 blocking 不变量矩阵、MA/波动/过热/防守分支可见、延伸仅 WARN、旧快照不伪造、B 晋升 trigger、端到端一致性）；更新 v2 视图模型/报告测试；OK | 报告表格结构与文案、review_trigger、决策 JSONL 增字段（schema 仍为 "1"，旧快照可读）；策略版本号升级 | 门文案为人工措辞；极端组合（多分支同时触发）按 canonical 列表全部展示，未做优先级折叠 |
| R07 | 已实现待验收 | 新增 `decision/attention.py`：`select_state_change_alerts`（实质降级=较上次 Action 排名恶化；排除已列示代码；严重度→Action→priority→symbol 确定性排序；total/truncated 显式）；`reporting/snapshot.py`：写 `state_change_alerts.jsonl` + manifest `state_change_alerts` 摘要，并将告警纳入详情页集合；`reporting/decision.py` v2 Action List 新增 “Attention Changes — Off-List Downgrades” 区；validator 复核 manifest/JSONL/渲染一致 | `tests/test_code_review_repair_r07_alerts.py`（15+1 复现样例、无历史/未变化不告警、确定性排序、cap/truncated、报告+manifest+JSONL+详情页、篡改与缺文件拒绝）；OK | v2 Action List 新增区（layout v2 输出变化）；manifest/快照新增审计文件；主列表 cap 不变 | 仅 v2 布局渲染该区（v1 逐字不变）；“实质降级”简化为 Action 排名恶化，未纳入仅质量降级但 Action 不变的情形 |
| R08 | 已实现待验收 | `scanner.write_latest_decision_pointer`：身份一律读目标 manifest（含 dated 阶段版本），调用者版本不符显式报错；目标必须完整可解析、路径安全；临时文件+`os.replace` 原子写；拒绝把 latest 指针回退到更旧日期；损坏既有指针 fail-closed；`run_scan` 同日复用先校验身份再发布 | `test_daily_cron_scan_and_ttl.py`（v2 快照+v1 调用拒绝、缺目标、残缺、损坏 manifest、回退拒绝且旧指针完好、损坏既有指针、写入失败旧指针完好且无残留 tmp、不安全日期、相对路径、幂等）；`test_code_review_repair_r04_r08_contract_e2e.py`；OK | latest 指针身份/可靠性；pointer JSON 增加 dated 阶段版本字段；调用者期望不符不再静默写错 | 未做进程中断/并发 writer 实验（已覆盖单次写入失败与日期回退防护） |
| A01 | 已实现待验收 | 新增 `decision/attention.py` 承载 Offense Track 资质/排序/版本与 `select_growth_compounder_offense`；`view_model.py` 改为导入并保留历史导出名 | 既有 `test_validate_growth_compounder_offense`、视图模型 Top-10/去重/顺序测试全部保持通过；`test_code_review_repair_r04_r08_contract_e2e.AttentionModuleContractTests` 断言同一性；OK | 行为保持重构；新增策略版本常量（尚未写入 manifest 附加区） | 未把专区选择结果写入 manifest（选择可由快照决定性重放）；如需冻结记录可后续追加 |
| A02 | 部分实施（拆分延期） | 新增 `tests/test_code_review_repair_r04_r08_contract_e2e.py`：隔离数据适配器→canonical decisions→writer→validator→pointer→cron 状态端到端契约；各修复自带缺陷测试 | OK | 无运行时行为变化 | `scanner.py` 的 live freshness 与 snapshot publishing 职责抽取**明确延期**：本轮先冻结行为与契约测试，避免与正确性修复同批大拆分 |

## 版本与缓存影响

- 策略版本升级（行为变化不可再宣称纯重构）：
  - `ENTRY_POLICY_VERSION` → `entry_quality_v1_2026-10-18`；
  - `ENTRY_V2_POLICY_VERSION` → `entry_quality_v2_2026-10-18`；
  - `QUALITY_POLICY_VERSION` → `company_quality_v1_2026-10-18`；
  - `QUALITY_V2_POLICY_VERSION` → `company_quality_v2_2026-10-18`。
- manifest 新增 `quality_policy_version` / `entry_policy_version`（由决策 provenance 派生）；同日快照复用与 latest 指针身份均校验 dated 版本，**不会**把修复前后的同家族（v2）证据静默混用；不匹配时标记 `reused_version_mismatch` 并让 cron 失败。
- 解析缓存（SEC 原始/解析）、effective facts hash、价格缓存语义未变；本轮未引入派生指标缓存，因此不存在旧缓存绕过修复的路径。
- 旧快照读取兼容：`StockDecision` schema 仍为 `"1"`；无 `gate_results` 的旧决策渲染为“未记录/无法完整验证”；旧 manifest 无版本字段时按 v1 处理；旧格式 JSON 序列化保持不变（空 gate 不写字段）。

## 复审反馈修复记录（2026-10-18 回执）

| 复审项 | 判定 | 修复 | 证据 |
|---|---|---|---|
| R03：market_asof 晚于运行时参考日期仍被判 0 天新鲜/READY | 属实 | `entry.py`：符号数据晚于参考 session → `market_data_ahead_of_reference` + `insufficient_reason`（INSUFFICIENT_DATA），freshness gate BLOCK；基准 QQQ 晚于参考 session 同理（`benchmark_market_data_ahead_of_reference`）；不再把未来时间戳夹成 0 天 | 合成诊断：symbol-ahead → INSUFFICIENT（该 risk）；benchmark-ahead → INSUFFICIENT（该 risk）；`test_code_review_repair_r03_freshness.py::test_market_asof_after_runtime_reference_fails_closed`、`::test_benchmark_after_runtime_reference_fails_closed` |
| R04：`main()` 先判 `scan_executed`，“已执行但核心快照失败”仍退出 0 | 属实（首轮遗漏） | `run_daily_cron.main()` 改为先判 `scan_failed` 再判 `scan_executed`；`run_daily_scan_after_prewarm` 对核心失败返回 `scan_executed=True, scan_failed=True` 的语义不变 | `test_daily_cron_scan_and_ttl.py::DailyCronMainTests::test_main_exits_1_when_stage2_core_failed_despite_execution`（`SystemExit.code == 1`） |
| R05：篡改 manifest `quality_policy_version` 仍通过；非对象 manifest 抛 AttributeError；旧快照无法通过渲染一致性校验 | 均属实 | ① validator 校验 manifest 阶段版本 ∈ 已知集合，并与逐股 provenance 相等（缺失/不一致→error）；② manifest 非 JSON object → 显式 error 返回；③ writer 写入 `report_renderer_revision`：当前 revision 做字节级比对，无 revision 的旧快照改为结构化校验（daily/weekly 成员必须出现在报告、daily/weekly 详情页必须存在）并给显式 legacy 警告，未知 revision 直接报错 | `test_code_review_repair_r05_validator.py` 新增 6 项；本地冻结 v2 快照（2026-10-16、2026-10-15）实测 `ok=True` 且带 legacy 警告；当前格式快照的篡改/缺页/未知版本仍全部失败 |

## 建议复核命令

```bash
.venv/bin/python -m unittest discover -s tests
git diff --check
git status --short
```

## 附带的测试隔离修复

`tests/test_io_safety.py` 曾用 `spec_from_file_location("ai_value_scanner.scanner", ...)` 覆盖 `sys.modules` 中的包模块，导致全量测试时后续模块绑定到被替换的 scanner 副本（R04 的身份断言将其暴露）。已改为隔离模块名加载，不影响被测函数本身。

## Review evidence to submit

本轮不需要凭证或外部实验：R01–R08 的验收证据全部是仓库内离线 unittest 与合成 fixture（见上表）。若验收者需要，可在任意干净环境运行上面的 unittest 命令复现全部结果；无需提交 `outputs/`、缓存或任何敏感文件。
