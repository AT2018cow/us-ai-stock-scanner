# 代码审查与修复交接：DeepSeek 实施，Codex 独立验收

日期：2026-10-18。状态：**审查及修复建议；业务代码尚未修复，尚未验收通过。**

审查基线：`3e68c0e531c2e96780844daaf0af594fb149da84`（PR #101）。
实施者：DeepSeek；后续独立验收者：Codex；最终合并由用户决定。

本文对应本轮代码审查发现的 8 项问题及 2 项结构改进建议。它是实施和验收的
交接清单，不是新策略研究计划，也不代表历史收益损失已经得到证明。
如果接手时 HEAD 已变化，先核对差异，仍以问题的行为和验收条件判断是否解决，
不要仅按旧行号机械修改。

## 1. 使用方式与范围

DeepSeek 开始前应先阅读仓库 [AGENTS.md](../AGENTS.md) 及其要求的四份当前文档：

1. [产品北极星](product_direction_low_frequency_manual_selection.md)。
2. [MVP 架构与决策契约](mvp_design_low_frequency_manual_selection.md)。
3. [MVP v2 完成交接](mvp_v2_completion_and_handoff_20261015.md)。
4. [运行与配置说明](../README.md)。

本轮实施目标是提高 Company Quality、Entry Quality、Action List、Detailed Report
的正确性和可信度。需要遵守以下边界：

- Action List 和 Detailed Report 消费同一套 canonical `StockDecision`；不得在报告中另写评级或行动映射。
- R01–R08 是修复范围；A01–A02 是结构建议，可以独立交付或明确延期，不应阻塞紧急正确性修复。
- 不做参数搜索、收益导向阈值调优、自动交易、历史 ETF 成分重建或新的全量重放。
- 不修改已冻结的正式快照、原始研究证据；重算结果必须输出到新的实验目录。
- 保留旧 CLI / legacy 输出兼容性。行为修复必须说明计算、策略、缓存及快照版本影响，不能声称是纯重构。
- 审查开始时已存在未跟踪文件 `docs/agent_specs/regime_indicator_validation_spec.md`；它不是本交接文档的产物，不要擅自覆盖或混入提交。
- 不提交 `.env`、凭证、原始缓存、`outputs/`、批量日志或 checkpoint。

## 2. 证据等级与基线

| 标记 | 含义 |
|---|---|
| 已复现 | 已通过离线合成输入执行当前函数，观察到所述行为 |
| 代码确认 | 调用链和分支明确支持结论，但本轮未做完整运行故障注入 |
| 冻结样本确认 | 在已存在的本地决策快照中观察到相应问题；不等同于全市场统计 |
| 待量化 | 对真实名单、覆盖率、排序或历史经济结果的影响尚未测量 |

审查阶段执行了：

```bash
.venv/bin/python -m unittest discover -s tests
```

结果：**1093 tests，22.355s，OK**。这是修复前的测试基线，不是本轮缺陷不存在的证明。
编写本文时 HEAD 与审查时相同；文档编辑未重复运行全套业务测试。

另外只读核查了本地 `outputs/decisions/2026-10-16/risk_off/`：

- 406 个 `StockDecision`，policy/layout 均为 v2。
- 快照记录的代码 SHA：`d4f775b3053af009ee3837fb76e46fcd2d9b4110`，与本次审查 HEAD 不同。
- `decisions.jsonl` SHA256：`c6d161d0edf4d38109e373b82257977148a051091951bdc7aafc7d830ac8d429`。
- `run_manifest.json` SHA256：`9b295f77371113f2e9e5cd3e139698b107586554a969d41ae200e6428826e989`。
- 17 只 Quality B / `PRIORITY_REVIEW` 股票的已存储 `review_trigger` 仍包含 `falls below A`。
- 对该快照的 IFF 决策使用审查 HEAD 的视图模型渲染：状态为 `WATCH_PULLBACK`，7 项检查全部 PASS。

这些文件是本地可选辅助证据，不要求 DeepSeek 拥有或提交它们；合成用例应可独立运行。
IFF 的结论是“旧快照输入 + 当前视图模型”的检查，不是重新运行 SEC/行情扫描。

## 3. 问题总表

| ID | 优先级 | 问题 | 证据 | 当前状态 |
|---|---|---|---|---|
| R01 | P1 | 缺失债务、存货被转换为正面质量证据 | 已复现 | 待修复 |
| R02 | P1 | 负基数同比把亏损改善/恶化解释反 | 已复现 | 待修复 |
| R03 | P1 | live 行情新鲜度缺少独立运行时基准 | 已复现；4–7 天语义需澄清 | 待修复 |
| R04 | P1 | MVP 输出失败仍可能被 cron 判为成功 | 代码确认 | 待故障注入及修复 |
| R05 | P1 | 验收器仍按 v1 验证生产 v2 | 已复现 | 待修复 |
| R06 | P2 | 入场检查表、复核文案与决策不一致 | 已复现；冻结样本确认 | 待修复 |
| R07 | P2 | 重要降级被 Top-15 截断隐藏 | 已复现 | 待修复 |
| R08 | P2 | latest 指针身份可能与实际快照不一致 | 已复现 | 待修复 |
| A01 | 改进 | 成长股专区的筛选和排序放在呈现层 | 代码确认 | 建议后续独立实施 |
| A02 | 改进 | 补跨层契约测试并收敛扫描编排职责 | 代码确认 | 测试随修复补齐；拆分可延期 |

P1 表示优先修复的正确性或运行可靠性问题，P2 表示解释、可见性和产物身份问题。
全部问题的真实总体影响仍待量化，不用合成用例推断某只真实公司的最终评级或收益损失。

## 4. 逐项修复要求

### R01 — 缺失财务数据不能转化为正面质量证据

**位置：** [fundamentals/accounting.py](../src/ai_value_scanner/fundamentals/accounting.py)
的 `derive_accounting_metrics`（基线约 172–178、277–288 行），以及
[decision/quality.py](../src/ai_value_scanner/decision/quality.py) 的相关指标评分。

**复现与影响：**

- `debt_long_term=None`、`debt_current=None`、`cash=100`、`adjusted_ebitda=50`，得到
  `total_debt=None`、`net_debt=-100`、`net_debt_to_ebitda=-2`，随后生成 `net_debt_to_ebitda_strong`。
- 两期存货均为 `None` 且有营收同比时，得到 `inventory_growth_gap=0`、
  `source=inferred_inventory_not_applicable`，随后生成 `inventory_growth_gap_strong`。
- 这证明缺失输入获得了正向贡献，未证明仅凭这些缺失就能让整家公司达到 A。

**建议修复：**

1. 区分 `reported`、`explicit_zero`、`verified_not_applicable`、`missing` 等状态；名称可以调整，语义必须清晰。
2. 债务证据不足时不自动假设为零；部分债务缺失也必须保留不完整标记。
3. 存货不适用需要业务模式或披露证据支持，不能由“两个字段都缺失”推出。
4. Quality 同时消费数值与可用性/来源状态。未知值不得产生正面证据；经过验证的不适用值如何进入 coverage，应显式定义。
5. 同步 live 与 replay 的共享计算路径、解析缓存及数据指纹；已有旧结果缓存不得绕过修复。

**验收：**

- 上述两个缺失样例不再产生对应 strong 证据或伪完整覆盖率。
- 显式零债务与完整披露的净现金样例仍得到正确处理；正常有库存公司的同比计算不变。
- 增加“部分债务缺失”“现金缺失”“真实零存货/确认不适用”的独立测试。
- 测试不能仅检查 source 字符串：必须检查最终 Quality 的贡献、missing evidence 和 confidence。

### R02 — 为负基数同比建立增长语义

**位置：** [fundamentals/accounting.py](../src/ai_value_scanner/fundamentals/accounting.py)
的 `safe_yoy`，以及 [decision/quality.py](../src/ai_value_scanner/decision/quality.py)
的 `_score_earnings_growth`、`_score_ocf_growth`。

**复现：**

| 上期 → 本期 | 当前同比 | 当前增长证据 | 应识别的经济变化 |
|---|---:|---|---|
| -100 → -200 | +100% | strong | 亏损扩大 |
| -100 → -50 | -50% | weak | 亏损收窄 |
| -100 → +100 | -200% | weak | 扭亏 |

同样的问题适用于经营现金流、EBIT 等允许为负的序列。
公式本身在数学上可计算，错误发生在把这个数直接解释成“越高越好”的增长证据。

**建议修复：**

- 保留正基数、同口径数据的现有同比定义。
- 对允许为负的指标引入明确的改善/恶化、扭亏/转亏、不可比状态；可以输出独立方向字段，也可以使用有标记的绝对基数变化率。
- 不要把所有 `safe_yoy` 调用无差别改成绝对分母；收入、股本、库存等指标的有效域不同，应分别核对调用方。
- 扭亏不能自动等价于可持续高速增长；最终分档需写清规则，先按经济语义修复，不用历史收益挑选参数。
- 若选择负基数同比返回缺失，仍须保留金额变化及解释，不能丢掉经营变化的信息。

**验收：**

- 亏损扩大不能得到 strong 增长证据；亏损收窄/扭亏不能仅因该比例符号被描述为利润下滑。
- 测试覆盖正→正、负→负两种方向、负→正、正→负、零基数和缺失。
- live/replay 同一输入得出相同结果；正常 `100 → 120` 仍为 `+20%`。
- fixture 保持金额、利润率及现金流相互一致；独立检查增长贡献，不以整家公司最终评级掩盖错误。

### R03 — 分离历史决策日期与 live 数据可用性时钟

**位置：** [scanner.py](../src/ai_value_scanner/scanner.py) 的 `resolve_market_decision_date`、
`run_scan`；[decision/entry.py](../src/ai_value_scanner/decision/entry.py)
的 `_build_entry_with_thresholds`。

**R03-A：已复现的运行时缺口。**
`decision_date` 取 QQQ 的行情日期，年龄又用 `decision_date - market_asof` 计算。
合成输入中生成时间为 `2026-10-18`，QQQ 和个股数据均停在 `2026-09-18`，结果仍是
`market_data_fresh=0`、`ENTRY_READY`。当前结果可以描述旧 session 的技术结构，
但不能据此声称它是本次 live 扫描的新鲜决策。

**R03-B：对前轮审查的语义澄清。**
5 天旧行情仍为 Ready 的行为已复现，但
[v1 Entry policy](entry_quality_v1_policy.md) §2 明确允许 4–7 天数据并降低置信度。
因此，“5 天仍 Ready”本身不是违反 v1 的计算错误；它与 README 的 v2“<=3 天门限”、
报告的 `FAIL_BLOCKER` / “全部通过”措辞存在不一致。不要以修 bug 为名无版本地改变历史 v1。

**建议修复：**

1. 保留 `decision_date`、各市场数据 `market_asof` 及真实 `generated_at_utc`。
2. live 额外计算独立、可注入的时效参考：最近应完成的美国市场 session；明确盘中、盘后、周末、节假日及提前收市语义。优先复用可靠日历能力。
3. 整体旧缓存必须显示真实运行时滞后，并按明确的 live 过期规则降级/拒绝发布；不能把旧 session 的 0 天相对年龄当作 live 新鲜度。
4. 历史 replay 使用显式 historical as-of，不依赖机器今天的日期；检查个股、QQQ、价格快照的时点一致性。
5. 本轮默认保留已实现的 4–7 天警告语义，修正展示和说明；若将生产 v2 改为 >3 天硬阻塞，须单独写明行为/版本变化并补前后对照。
6. 不得为了消除 future-date 异常放松 PIT：QQQ 陈旧、个股更新或财报更新的混合时点，须明确处理而非忽略校验。

**验收：**

- 所有数据停在 30 天前时，不得输出无运行时降级标识的“新鲜 Ready”并当作本次成功发布。
- 单股滞后而 QQQ 正常、QQQ 滞后而个股正常、缓存 fallback、正常新数据分别有测试。
- 周末/假日不会误把最近正常交易日当作数据故障；reference clock 可注入，测试不依赖执行当天。
- 4–7 天的状态、风险、checklist 与文档一致；>7 天的既有严重过期保护保留。
- 相同历史输入换一天运行，历史判断不因 wall clock 改变。

### R04 — cron 成功必须包含核心决策产物成功

**位置：** [scanner.py](../src/ai_value_scanner/scanner.py) `run_scan` 的 decision-output
异常处理（基线约 5547 行）；[run_daily_cron.py](../scripts/run_daily_cron.py)
的 `run_daily_scan_after_prewarm`。

**代码确认：** 默认 legacy watchlist 路径会捕获快照生成异常、打印 WARN，仍返回 legacy CSV。
cron 仅以是否抛异常判断扫描成功，可能报告成功但没有本次 Action List。
multi-source opt-in 路径另有重抛规则，不能把结论泛化为所有路径都吞异常。
本轮未进行完整扫描故障注入，实施时必须补这一证据。

**建议修复：**

- 引入结构化内部结果，分别记录 legacy 输出、canonical snapshot、报告与 latest 发布状态；或使用兼容的 strict-MVP 执行模式。
- 不必破坏现有 `run_scan(...) -> Path` 调用方，可以由兼容 wrapper 保留旧契约。
- cron 缺少核心产物时返回非零，并输出明确失败阶段；保留已经成功生成的 legacy 文件。
- 区分新建成功、验证后复用、失败。复用快照必须校验完整性和身份，不能只检查目录存在。
- 若 shadow 失败而主快照成功，须显式报告 partial outcome，不能混淆主流程与可选 shadow 的结果。

**验收：**

- 注入 JSONL 写入、Markdown 渲染、manifest、latest 指针失败，检查 cron 状态及退出码。
- 注入故障时不接触真实 SEC、Alpaca、仓库缓存或正式快照。
- 验证返回的 CSV 路径存在并不足以让 cron 报 MVP 成功；错误可定位，重试不会覆盖已冻结产物。
- 正常发布及允许的完整同日快照复用仍成功；残缺目录、身份不符必须显式报错或报告不兼容复用。

### R05 — 验收器必须按快照记录的版本校验

**位置：** [validate_mvp_snapshot.py](../scripts/validate_mvp_snapshot.py)
`validate_snapshot`（基线约 168、466–489 行）；调用入口
[run_mvp_full_scan.py](../scripts/run_mvp_full_scan.py)。

**复现：** 用当前 writer 正常写出 v2 快照后立即验收，出现：

```text
AAA: action PRIORITY_REVIEW != canonical mapping HOLD_MONITOR
action_list.md does not match canonical StockDecision rendering
weekly_review.md does not match canonical StockDecision rendering
detailed/AAA.md does not match canonical StockDecision rendering
```

原因是验证器使用 v1 的 `map_action_state` 与默认 v1 renderer。
样例中的 B+Ready 晋升是 v2 合法行为，不是需要“修掉”的策略错误。

**建议修复：**

1. 从 manifest 解析决策和布局版本；兼容旧 manifest 无版本字段时的明确 v1 默认。
2. 使用对应的共享 Action mapper 和 renderer；v2 渲染需传入完整 decisions 以恢复附加专区。
3. 明确支持的 policy/layout 组合，未知版本必须报错；不要默默回退到 v1。
4. 校验 manifest 与逐股 provenance 的版本一致性；检查所有实际链接的详细报告，包括 Secondary Radar 和 Offense Track。
5. 保留篡改、缺文件、重复股票、universe conservation 等原有防护。

**验收：**

- v1 旧快照、v2 完整快照及受支持的混合 policy/layout 组合正确通过。
- v2 B 晋升例通过；仅将其改为不符合 v2 规则的 action 后必须失败。
- 任意报告篡改、缺少被链接的详情页、未知版本均失败，不能靠关闭一致性比较使测试变绿。
- 增加生产 v2 config 经隔离数据适配器生成快照后由正式 validator 验收的集成测试。

### R06 — canonical 决策、检查表与复核提示必须一致

**位置：** [decision/view_model.py](../src/ai_value_scanner/decision/view_model.py)
的 `_GATE_DEFS`、`_build_entry_checklist`、`_build_entry_blockers_inline`；
[decision/integrated.py](../src/ai_value_scanner/decision/integrated.py) 的 `_review_trigger`；
[decision/entry.py](../src/ai_value_scanner/decision/entry.py) 的分支证据生成。

**已复现的四类问题：**

| 场景 | canonical 结果 | 展示/证据问题 |
|---|---|---|
| `price_to_sma200=1.01`、`price_to_sma50=1.04`，其余健康 | MA 比值约 0.971，`WATCH_BREAKOUT` | checklist 7 项全部 PASS |
| `volatility_60d=0.90`，其余健康 | `WATCH_BREAKOUT` | checklist 7 项全部 PASS |
| 防守市场，RS60=+6%、20d=+5%，其余健康 | `ENTRY_READY` | regime 显示 `FAIL_BLOCKER`，摘要仍称全部通过 |
| B 高分晋升 | `PRIORITY_REVIEW` | review trigger 仍要求 A，否则降级 |

另有 IFF 冻结样本：`WATCH_PULLBACK`、没有 entry risk、当前 checklist 全部 PASS。
代码中 `range_position_52w >= 0.95 && return_20d > 0.08` 可先于 Ready 路由到回调观察，
该组合也应有明确的原因证据。旧快照未完整保存触发输入，不能仅凭该快照反推 IFF
一定命中了这一条件；请用完整合成输入独立覆盖该分支。

**建议修复：**

- 让决策层生成 canonical gate results / blockers：包含 observed、target、result、原因、policy version，区分硬阻塞、警告、未知和不适用。
- 呈现层只格式化结果，不能通过“有负面证据即 FAIL”重新推断门限。
- 覆盖均线排列、波动、回撤、联合过热条件及防守市场的实际附加条件；不强求检查项目永远等于 7。
- 每条导致非 Ready 的有效分支都应解释原因；非阻塞性过热警告不得被错误升级为 blocker。
- `_review_trigger` 接收有效 policy 和当前决策，B 晋升/退出条件应与共享 mapper 一致。
- 老快照无法恢复的 gate 显示“未记录/无法完整验证”，不要伪造原始输入或声明全部通过。

**验收：**

- 上表四例、IFF 类联合过热合成例、非阻塞延伸警告例有定向测试。
- Ready 的表格不能存在实际硬阻塞；非 Ready 必须能定位阻塞/结构原因，未知证据须明确标注。
- 摘要、详情、Action State 和 review trigger 一致；B 晋升不能同时被文案要求因低于 A 而降级。
- 对本地可用的冻结样本作只读回归；报告更准确不意味着旧 JSONL 被重写。

### R07 — 重要降级不能被当前优先级挤出视野

**位置：** [decision/integrated.py](../src/ai_value_scanner/decision/integrated.py)
的 `select_daily_attention`、`select_weekly_attention`。

**复现：** 15 只状态未变的 `PRIORITY_REVIEW`，加 1 只从 `PRIORITY_REVIEW` 降为
`AVOID` 的股票。在 cap=15 时，降级股同时被 daily/weekly 截掉。
排序先使用当前 Action 的优先级，降级股虽然进入候选集合，仍在截断前排在末尾。

**建议修复：**

- 首选独立的状态变化告警区，与当前优先研究名单分别压缩，复用同一 canonical 决策。
- 也可在现有 cap 内预留重要降级名额，但须明确占用规则及排序。
- 不通过增大全局 cap 或提高所有 AVOID 的排名解决；区别新出现的长期弱股和需要复核的实质降级。
- 告警过多时显示总数、明确的截断信息和完整可追索清单，不能静默消失；详情链接必须存在。
- 告警选择规则与输出成员要可审计，不仅存在于 Markdown renderer。

**验收：**

- 15+1 样例中的降级必定在主列表或专用告警区可见。
- 保持普通 attention cap；新增区与主区没有无解释重复。
- 多个降级、无历史、新加入 AVOID、未变化 PRIORITY_REVIEW 分别测试，排序确定且可解释。
- 同时验证 JSONL、manifest、报告与详情链接的一致性。

### R08 — latest 必须准确指向并描述已发布快照

**位置：** [scanner.py](../src/ai_value_scanner/scanner.py)
`write_latest_decision_pointer` 和同日 `allow_existing_decision_snapshot` 分支。

**已复现：** 实际 manifest 为 v2，调用 pointer writer 传入 v1 后，latest 写成 v1。
同日切换配置并复用旧目录时，扫描调用链也会把本次配置版本传给旧快照的 pointer。
另外直接 `write_text` 及无日期单调性检查是代码确认的可靠性风险；本轮未做进程中断或并发实验。

**建议修复：**

1. 从目标快照 manifest 读取日期、style、policy/layout、身份信息，不以调用者配置冒充目标身份。
2. 先确认目标完整、可解析且相对路径安全，再发布 pointer；不存在或残缺目标不得成为 latest。
3. 用临时文件与原子替换避免半截 JSON；如可能有并发 writer，要保证日期单调性检查与发布不会竞态倒退。
4. 较旧 session 的重跑不能覆盖已经指向较新 session 的 latest；显式历史产物仍可以存在。
5. 同日新配置与旧快照不一致时，明确报告“复用的实际身份/未生成本次配置结果”，不得静默伪称新版本已生效。

**验收：**

- v2 快照 + v1 调用参数不能生成错误身份：使用真实 manifest 或显式拒绝。
- 新日期→旧日期、同日期复用、缺 manifest、损坏 JSON、相对路径及写入失败有测试。
- 写入失败后旧 pointer 仍完整可读；不覆盖 immutable snapshot；并发/故障测试使用临时目录。

## 5. 结构改进建议

### A01 — 将 Offense Track 的选择逻辑移出呈现层

现有 [decision/view_model.py](../src/ai_value_scanner/decision/view_model.py)
`is_growth_compounder_offense_eligible` / `growth_compounder_offense_order_key`
包含营收、现金流、RS、均线门限及独立评分公式。这决定用户额外看到哪些公司，属于
注意力分配逻辑；虽然没有改写主 Action State，仍应有可冻结、可复用的策略身份。

建议放入独立共享 attention-policy 模块，输出资格、排序、原因及版本，记录在快照或
manifest 的附加选择结果中；视图模型只负责展示。不必为此改变主 Action State 枚举。

验收：相同输入的专区成员、顺序、Top-10 上限、主区/Secondary Radar 去重完全保持；
无新参数、无隐式重排主名单；新产物能重现当时专区，旧快照按明确兼容规则展示。
这是一项可独立延期的行为保持重构，不是生产策略再调优。

### A02 — 补跨层契约测试，再拆扫描编排

基线 `scanner.py` 为 5823 行，包含客户端、财务适配、扫描编排及输出发布。
建议先补“隔离数据适配器 → canonical decision → writer → validator → cron result”的
端到端契约测试，然后逐步抽取 live freshness 与 snapshot publishing 职责。

无需一次重写扫描器、引入新框架或修改已经验证的底层指标库。
测试应验证业务边界及失败行为，不只比较调用次数或复制实现公式。

验收：没有网络和凭证的集成用例能捕获 R03–R08；抽取前后的正常输出一致，错误可定位；
旧入口保持兼容。缺陷测试随对应修复交付，较大的文件拆分允许明确延期。

## 6. 建议实施批次

| 批次 | 范围 | 交付重点 |
|---|---|---|
| B1 | R01、R02 | 财务有效域、来源状态、live/replay 一致性、缓存/计算版本 |
| B2 | R03、R04、R08 | 运行时新鲜度、核心产物成功判定、可信 latest 发布 |
| B3 | R05、R06 | 版本感知验收器、canonical gate results、正确复核文案 |
| B4 | R07 | 降级告警可见性、manifest/详情一致性 |
| B5（可延期） | A01、A02 的结构抽取 | 独立策略选择模块、扫描编排边界 |

批次用于控制 diff 和验收范围，不要求创建五个 PR。R05 成本较低且能改善后续验收，
可提前完成。R06 的扩展契约要与 R05 协调；不要同时维护第二套门限解释。

所有行为变更必须说明是否影响解析缓存、effective/scoring hash、历史输入、策略版本及
旧快照读取。必要时升级版本，已有 manifest 不匹配时停止复用，不能静默混用新旧证据。

## 7. 离线复现入口

下面是基线诊断程序，不是修复后应继续维持的期望值。它不联网，临时快照只写入
`TemporaryDirectory`，正常结束后自动清理。从仓库根目录执行即可观察 R01、R02、
R03、R05、R06、R07、R08；R04 必须在实施时补真实调用链的故障注入测试。

```bash
.venv/bin/python - <<'PY'
import inspect
import json
import sys
import tempfile
from dataclasses import replace

import pandas as pd

sys.path.insert(0, 'scripts')
from ai_value_scanner.decision import (
    ActionState, build_stock_decisions,
    select_daily_attention, select_weekly_attention,
)
from ai_value_scanner.decision.quality import build_company_quality_v2
from ai_value_scanner.decision.view_model import build_stock_card_view_model
from ai_value_scanner.fundamentals.accounting import derive_accounting_metrics, safe_yoy
from ai_value_scanner.reporting.snapshot import write_decision_snapshot
from ai_value_scanner.scanner import resolve_market_decision_date, write_latest_decision_pointer
from validate_mvp_snapshot import validate_snapshot

BASE = dict(
    symbol='AAA', company_name='Synthetic AAA',
    fundamental_data_asof='2026-08-01', market_asof='2026-10-09',
    revenue=1000.0, net_margin=0.25, free_cash_flow=200.0,
    adjusted_ebit=250.0, ocf_to_net_income=1.2, accrual_ratio=-0.05,
    revenue_yoy=0.20, adjusted_net_income_yoy=0.20,
    operating_cash_flow_yoy=0.20, net_debt_to_ebitda=0.0,
    interest_coverage=10.0, current_ratio=2.0, shares_yoy=0.0,
    fcf_yield=0.06, ps_hist_percentile=0.20, pe_hist_percentile=0.30,
    receivables_growth_gap=0.0, inventory_growth_gap=0.0,
    price_to_sma200=1.05, price_to_sma50=1.03, days_below_sma200=0,
    return_20d=0.05, return_60d=0.10, drawdown_from_52w_high=0.08,
    range_position_52w=0.82, relative_strength_60d_qqq=0.04,
    volatility_60d=0.35, regime='up', benchmark_trend_ok=True,
)

def emit(case, **values):
    print(json.dumps(dict(case=case, **values), ensure_ascii=False))

def decision(changes=None, day='2026-10-09'):
    return build_stock_decisions(
        pd.DataFrame([{**BASE, **(changes or {})}]),
        decision_date=day, generated_at_utc='2026-10-18T12:00:00+00:00',
        policy_version='v2',
    )[0]

args = {key: None for key in inspect.signature(derive_accounting_metrics).parameters}
args.update(revenue=120.0, revenue_prev=100.0,
            cash_and_equivalents=100.0, adjusted_ebitda=50.0)
metrics = derive_accounting_metrics(**args)
quality = build_company_quality_v2(
    metrics, decision_date='2026-10-09', data_asof='2026-08-01',
)
emit('R01', net_debt=metrics['net_debt'],
     leverage=metrics['net_debt_to_ebitda'],
     inventory_gap=metrics['inventory_growth_gap'],
     positives=[item.code for item in quality.positives])

for previous, current in [(-100.0, -200.0), (-100.0, -50.0), (-100.0, 100.0)]:
    growth = safe_yoy(current, previous)
    quality = build_company_quality_v2(
        {'adjusted_net_income_yoy': growth},
        decision_date='2026-10-09', data_asof='2026-08-01',
    )
    emit('R02', previous=previous, current=current, growth=growth,
         evidence=[item.code for item in (*quality.positives, *quality.risks)
                   if item.metric == 'adjusted_net_income_yoy'])

old = {**BASE, 'market_asof': '2026-09-18'}
old_day = resolve_market_decision_date(
    pd.DataFrame([old]), benchmark_market_asof='2026-09-18',
)
stale = decision({'market_asof': '2026-09-18'}, old_day)
emit('R03', decision_date=old_day, generated_at=stale.generated_at_utc,
     entry=stale.entry.state.value,
     age_evidence=[(item.code, item.value) for item in stale.entry.positives
                   if item.metric == 'market_data_age_days'])

for name, changes, day in [
    ('MA', {'price_to_sma200': 1.01, 'price_to_sma50': 1.04}, '2026-10-09'),
    ('volatility', {'volatility_60d': 0.90}, '2026-10-09'),
    ('five_days', {}, '2026-10-14'),
    ('defensive', {'regime': 'down', 'benchmark_trend_ok': False,
                   'relative_strength_60d_qqq': 0.06}, '2026-10-09'),
    ('range_extension', {'range_position_52w': 0.96,
                         'return_20d': 0.09}, '2026-10-09'),
    ('B_promotion', {'shares_yoy': 0.20}, '2026-10-09'),
]:
    item = decision(changes, day)
    card = build_stock_card_view_model(item)
    emit('R06_' + name, quality=item.quality.grade.value,
         entry=item.entry.state.value, action=item.action_state.value,
         gates=[(gate.gate_key, gate.status) for gate in card.entry_checklist],
         inline=card.entry_blockers_inline, trigger=item.review_trigger)

base = decision()
unchanged = tuple(replace(
    base, symbol=f'OK{i:02}', priority=i + 1,
    previous_action_state=ActionState.PRIORITY_REVIEW, state_change_reason=None,
) for i in range(15))
downgraded = decision({'net_debt_to_ebitda': 6.0, 'interest_coverage': 0.5})
dropped = replace(
    downgraded, symbol='DROPPED', priority=16,
    previous_action_state=ActionState.PRIORITY_REVIEW,
    state_change_reason='Quality A to C; Action PRIORITY_REVIEW to AVOID',
)
for selector in (select_daily_attention, select_weekly_attention):
    selected = selector((*unchanged, dropped), cap=15)
    emit('R07_' + selector.__name__, downgraded_action=dropped.action_state.value,
         downgrade_visible=any(item.symbol == 'DROPPED' for item in selected))

with tempfile.TemporaryDirectory() as tmp:
    item = decision({'shares_yoy': 0.20})
    paths = write_decision_snapshot(
        output_root=tmp, strategy_style='risk_off', decisions=(item,),
        daily_attention=(item,), weekly_attention=(item,),
        generated_at_utc=item.generated_at_utc, decision_date=item.decision_date,
        config_fingerprint='synthetic-audit', policy_version='v2', layout_version='v2',
    )
    result = validate_snapshot(paths.root)
    emit('R05', ok=result['ok'], errors=result['errors'])
    pointer = write_latest_decision_pointer(
        tmp, decision_date=item.decision_date, strategy_style='risk_off',
        policy_version='v1', layout_version='v1',
    )
    emit('R08', manifest_policy=json.loads(paths.run_manifest_json.read_text())[
        'decision_policy_version'], pointer_policy=json.loads(pointer.read_text())[
        'decision_policy_version'])
PY
```

修复后的函数契约可能变化，允许调整诊断程序的适配调用；不能改变问题输入或经济方向
来掩盖失败。真正回归测试应断言本文件 §4 的期望行为，不应把上述错误输出写成 golden value。

## 8. DeepSeek 交付与 Codex 验收契约

### 8.1 实施交付

完成实现后，给出可审查的分支/PR 或准确提交 SHA，并提供一份简短修复说明。
建议放在 `docs/code_review_repair_results_20261018.md`，由实现者创建，逐项填写：

| ID | 状态 | 实现位置/提交 | 测试及结果 | 行为/版本影响 | 剩余限制 |
|---|---|---|---|---|---|
| R01–R08（每项一行） | 已实现待验收 / 未完成 | 函数与 SHA | 命令、测试名、结果 | 缓存/策略/快照等 | 未量化部分 |
| A01、A02（每项一行） | 已实现待验收 / 延期 | 同上 | 同上 | 同上 | 延期原因 |

实现者不得把状态写成“Codex 已验收”；本审查基线和原始发现保留，修复结果另记。
至少提交：

- 必要业务修改、定向 unittest、最小跨层集成测试及同步文档。
- 每项修复前失败/修复后正确的简短证据；包括 R04 的故障注入。
- 最终 HEAD 上完整 unittest 结果、`git diff --check` 结果；PR 最终 head 自己的绿色 CI。
- R01/R02 的独立数值推导，R03 的时间语义，R05 的版本矩阵，R06/R07 的小型输出样例。
- 正常控制样例保持不变的证据，以及缓存失效/版本迁移说明；行为变化不能用旧冻结证据冒充重新验证。

推荐常规检查：

```bash
.venv/bin/python -m unittest discover -s tests
git diff --check
git status --short
```

### 8.2 外部实验不是本轮默认前置条件

优先使用合成 fixture、现有冻结输入与隔离缓存。以上正确性验收不需要凭证或新全量 replay。
若确实还需用户运行 credentialed/post-merge 实验，必须先按
[AGENTS.md §8](../AGENTS.md) 在 PR 中提供 **Review evidence to submit**：
精确命令、实验性质、目标证据位置、代码/输入 commit SHA、必须提交的小型原始证据与摘要、
不得提交的敏感/大文件，以及具体验收问题。不能跑完后再补要求。
已有 evidence 分支/存储选择需核实；不要自行新建证据分支或要求第二个 evidence-only PR。

### 8.3 Codex 后续独立验收

用户提供实现提交后，Codex 按以下顺序验收：

1. 确认最终 HEAD、diff 范围、用户已有改动及版本/缓存变化。
2. 对 R01–R08 逐项重读实现，独立推导关键数值，运行边界与负向测试。
3. 用同一输入验证 decision、报告、manifest、validator、cron 状态之间的契约。
4. 检查正常控制样例、旧版兼容、PIT、immutable snapshot，以及 stale/missing/failure 行为。
5. 在最终代码上运行所需 unittest，核对最终 PR head 的 CI；不以测试数量或实现者说明代替结果。
6. 输出逐项 `PASS / FAIL / NOT VERIFIED / DEFERRED`，列出证据及剩余限制。

本轮正确性验收通过要求 R01–R08 全部 PASS；若分批交付，只给该批结论，不宣称整体完成。
A01/A02 的大型结构重构可以有理由地 DEFERRED，但相关缺陷的必要测试不能延期。
“工程正确性通过”与“真实总体影响已量化”分别报告；没有新证据时不得宣称收益改善或 OOS 验证。

## 9. 可直接交给 DeepSeek 的任务说明

> 请先阅读 AGENTS.md 及其四份必读文档，再按照
> `docs/code_review_and_repair_handoff_20261018.md` 实施 R01–R08。
> 逐项保留证据，优先离线复现和定向 unittest，不调参、不覆盖冻结快照、不运行新的昂贵全量实验。
> A01/A02 的较大结构重构可单独交付或明确延期。
> 按 §8 提交准确代码 SHA、逐项修复结果、测试和版本/缓存说明，供 Codex 独立验收。
> 本文的问题状态目前是待修复，不要把审查文档或全绿测试直接解释为已经修好。
