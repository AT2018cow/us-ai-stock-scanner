# Agent Specification: 降低 Top-15 换手率与抑制“追涨杀跌”（稳定化改造 v2）

- **Date**: 2026-11-05
- **Status**: 架构师已审阅并完善（v2）；Phase 1（报告在榜天数展示 + 离线多方案同台回放验证）可直接交由 DeepSeek 实施
- **Scope**: Top-15 判定稳定性、进严出宽缓冲区（Hysteresis）、非对称退场确认制、Regime 确认制、报告可读性
- **Related**: `docs/mvp_design_low_frequency_manual_selection.md`、`docs/entry_quality_v1_policy.md`、`docs/mvp_v2_completion_and_handoff_20261015.md`
- **Target Execution Agent**: DeepSeek（实施与测试）

---

## 1. 问题陈述与根因归因

### 1.1 实盘现象（2026-10-19 至 2026-11-04）

2026-10-19 至 2026-11-04 共 13 个 `production` 实盘快照（位于 `outputs/decisions/<date>/production/`），Top-15 逐日保留数如下（均值仅 **9.5 / 15**，日均换手 **5.5 只 / 36.7%**）：

| 转换 | 保留 | 移出 | 移入 |
|---|---:|---:|---:|
| 10-19 → 10-20 | 13 | 2 | 2 |
| 10-20 → 10-21 | 8 | 7 | 7 |
| 10-21 → 10-22 | 8 | 7 | 7 |
| 10-22 → 10-23 | 7 | 8 | 8 |
| 10-23 → 10-26 | 12 | 3 | 3 |
| 10-26 → 10-27 | 11 | 4 | 4 |
| 10-27 → 10-28 | 11 | 4 | 4 |
| 10-28 → 10-29 | 11 | 4 | 4 |
| 10-29 → 10-30 | 8 | 7 | 7 |
| 10-30 → 11-02 | 9 | 6 | 6 |
| 11-02 → 11-03 | 11 | 4 | 4 |
| 11-03 → 11-04 | 6 | 9 | 9 |

典型“追涨杀跌 / 一日游”样本：

- **MTCH**：11-02 刚贴边进入 Top-15（`sma50=0.98x`），11-03 单日 `-6.6%`，11-04 移出，在榜仅 2 个交易日；
- **ECL**：11-02 因短线冲高略超 `sma50_band` 上沿移出，11-03 回调一点又移入，11-04 再次移出（3 天往返 2 次）；
- **MSFT / AAPL / CPAY / MPC**：在 `ENTRY_READY` 与 `WATCH_BREAKOUT`（对应 `PRIORITY_REVIEW` 与 `HOLD_MONITOR`）之间随 20 日收益在 `0%` 或 `-3%` 附近微小波动（含 20 个交易日前基数滑出效应）而反复切换。

### 1.2 四大触发根因（原提案 3 项 + 架构审查新增第 4 项）

换手并非来自基本面质量分级（`Company Quality`）变化（例如 11-03 → 11-04 的 9 个移出品种中，质量分级均未下调），而是集中在以下 **4 个单点零缓冲机制**：

1. **`ret20_band` 单点硬边界（`-3%` 至 `+12%`）**：
   - 进场阈值与退场阈值完全重合。20 日收益在 `-3%`（或防御档 `0%`）附近仅波动 `0.2%`（甚至当天股价未跌、仅因 20 个交易日前的一根阳线滑出窗口），就会触发状态翻转（造成“微跌即砍、微涨又追”）。
2. **`sma50_band` 窄带硬边界（`0.98x–1.08x`）**：
   - 贴近 50 日均线的品种（如 `0.979x` vs `0.981x`，或 `1.079x` vs `1.081x`）因单日 `0.3%` 的正常价格噪声在 `ENTRY_READY`、`WATCH_BREAKOUT`、`WATCH_PULLBACK` 之间高频往返。
3. **`market_regime` 零缓冲单日开合（QQQ 60 日收益 `< 0` vs `>= 0`）**：
   - 防御档（`regime=down`）要求所有标的额外满足 `RS60 >= +5%` 且 `return_20d >= 0%`。当 QQQ 60 日收益在 `0%` 附近震荡时，单日符号翻转会导致整批名单（5–8 只股票）在同一天集体进出。
4. **【架构审查新增】Top-15 截断线排位抖动与 `select_daily_attention` 的一日游填充漏洞**：
   - **排位截断抖动**：在 `assign_action_priorities_v2` 中，第 13–18 名的 `joint_score` 往往仅相差 `0.005–0.015`，缺乏“在榜驻留加分（Incumbent Bonus）”，导致截断线附近的股票每日互换名次；
   - **`select_daily_attention` 填充漏洞**：当前 `integrated.py` 的 `select_daily_attention` 筛选条件为 `action_state == PRIORITY_REVIEW or state_change_reason is not None`。当 `PRIORITY_REVIEW` 不足 15 只时，会把当天恰好发生状态变化的非优先股（如刚降级为 `HOLD_MONITOR` / `AVOID` 的股票）塞进 Top-15 主榜；而第二天该股状态不再变化（`state_change_reason is None`），又立即从主榜消失，制造人为的“一日游”（注：`R07` 已专门增设 `Attention Changes — Off-List Downgrades` 告警区，主榜不应再混入非 `PRIORITY_REVIEW` 的单日变动股）。

---

## 2. 架构审查结论与关键改进原则

原提案的目标、非目标与问题归因完全正确，但在具体机制设计上做以下 **4 点关键改进**：

1. **警惕对称确认制（`N=2` 进场、`M=2` 退场）的“追高滞后”与“破位漏网”**：
   - 若进场一律强制等待 `N=2` 天确认：由于 `ENTRY_READY` 本身是回踩低吸窗口（`sma50 0.98–1.08x`），Day 1 回踩到位时不进、等到 Day 2 反弹 `+3%` 才进，会**加剧“追涨”**；
   - 若退场一律无条件等待 `M=2` 天确认：当持仓股发生真破位（`TREND_DAMAGED`、`sma200 < 0.95`、`days_below_sma200 >= 15`）或基本面降级（`Quality C/UNRATED`）时，多留榜 1 天会产生实质风控隐患；
   - **改进**：必须对比 **`N=1` 进场 + 软越界 `M=2` 退场（硬破位 `M=1` 立即退场）** 与 **`N=2, M=2`**，用实盘数据检验滞后代价。
2. **将“方案 B（进严出宽阈值缓冲区 Hysteresis + 在榜排位缓冲）”列为核心治本机制**：
   - 控制论中消除单阈值高频抖动（Chattering）的标准解法是 **施密特触发器（进严出宽）**：对**上一交易日已在 Top-15 内且未发生趋势破位**的在榜股，放宽软边界的退场阈值（如 `sma50` 在榜保持带 `0.96–1.10x`、`ret20` 在榜保持带 `-5%..+14%`、防御档在榜保持带 `RS60 >= +2% & ret20 >= -2%`、B 级晋升在榜 `entry.score >= 0.74`、Top-15 综合分在榜驻留加分 `+0.02`）。既能做到 **进场 0 延迟（不追高）**，又能做到 **微幅回调不乱砍（不杀跌）**，且一旦触及硬破位立即当天移出。
3. **严守 `StockDecision` 单一事实源契约（`AGENTS.md` §2）**：
   - 任何正式进入生产的稳定化规则，不得导致“Action List 卡片显示在 `Priority Review`，但 `StockDecision.action_state` 却是 `HOLD_MONITOR`”（否则 `validate_mvp_snapshot.py` 会判定渲染不一致而失败）。
4. **明确解决原 §7 的全部 4 个待决问题**：
   - **状态来源**：直接读取上一交易日快照的 `decisions.jsonl` 与 `run_manifest.json`（`daily_symbols`），**不新增独立外部状态文件**；首次运行或无历史快照时自动退化为单日判定；
   - **`in_list_streak` 口径**：按**连续生产快照（交易日）**计数，跨周末/节假日天然连续，不因休市断签；
   - **缓冲区宽度**：仅使用一组根据经济语义预设的固定常数（严禁网格搜索调参）；
   - **验证数据分工**：**13 个日频实盘快照（2026-10-19 至 2026-11-04）**用于精确测量日度换手率、保留数、一日游与 5 日往返次数；**51 期月度冻结数据集（39 base + 12 bear-2022）**用于检验策略变更对 60d 前向超额收益与熊市/回撤期重伤率的影响。

---

## 3. 候选方案定义（进入同台离线验证）

在修改生产 `entry.py` / `action.py` 之前，先在离线评估器中实现以下候选机制并同台实测：

### 3.1 `B0_baseline`（当前生产基线）
- 现行 `v2` 规则（单日硬门限、无在榜缓冲、无确认制）。

### 3.2 `S1_confirm_2_2_safe`（原方案 A 安全版：双日进出确认 + 硬破位单日熔断）
- **进入 Top-15**：连续 `N=2` 个交易日原始判定满足 `PRIORITY_REVIEW`；
- **移出 Top-15**：
  - 若当日触发 **硬风险熔断**（`entry.state in {TREND_DAMAGED, INSUFFICIENT_DATA}`，或 `quality.grade in {C, UNRATED}`，或严重超买 `price_to_sma50 > 1.12` / `return_20d > 0.15`），**`M=1` 当日立即移出**；
  - 若仅为软边界越界（落入 `WATCH_BREAKOUT` 或轻度 `WATCH_PULLBACK`），需连续 `M=2` 个交易日不满足才移出。

### 3.3 `S2_confirm_1_2_safe`（非对称确认制：进场不延迟 `N=1` + 软越界 `M=2` 缓退 + 硬破位单日熔断）
- **进入 Top-15**：`N=1`（当日满足标准 `PRIORITY_REVIEW` 即可入选，避免回踩买点滞后追高）；
- **移出 Top-15**：与 `S1` 相同（硬风险 `M=1` 当日立即移出；软越界需连续 `M=2` 个交易日不满足才移出，期间赋予在榜股优先保留权）。

### 3.4 `S3_hysteresis_buffer`（原方案 B 完整版：进严出宽阈值缓冲区 + 在榜排位缓冲）
仅对**上一交易日位于 Top-15 主榜内（Incumbent）且未触发任何硬破位**的标的启用驻留缓冲带（新进候选仍严格执行现行进场门限）：
1. **`sma50_band`**：新进 `[0.98, 1.08]`；在榜驻留 **`[0.96, 1.10]`**；
2. **`ret20_band`**：新进 `[-3%, +12%]`；在榜驻留 **`[-5%, +14%]`**；
3. **`rs60_qqq`**：常规档新进 `>= -3%`、在榜驻留 **`>= -5%`**；防御档（`defensive_regime`）新进要求 `RS60 >= +5%` 且 `return_20d >= 0%`，在榜驻留要求 **`RS60 >= +2%` 且 `return_20d >= -2%`**；
4. **Quality B 晋升 `PRIORITY_REVIEW` 门限**：新进要求 `entry.score >= 0.80`；在榜驻留要求 **`entry.score >= 0.74`**（允许吸收一项 `-0.06` 轻度延伸扣分而不被立刻踢出）；
5. **Top-15 排位截断缓冲（Incumbent Bonus）**：在榜股计算 `PRIORITY_REVIEW` 排序键时获得 **`+0.02` 综合分驻留加分**，防止第 14–16 名因 `0.005` 分差每日互换；
6. **主榜纯净性修复**：主榜仅从 `PRIORITY_REVIEW` 中按优先级选取（当不足 15 只时如实展示实际数量，不再用 `state_change_reason is not None` 的非 `PRIORITY_REVIEW` 股票凑数）。

### 3.5 `S4_hybrid_hysteresis_regime`（方案 B + 方案 C 组合：进严出宽 + Regime 3 日确认/死区缓冲）
- 在 `S3_hysteresis_buffer` 基础上，叠加 **方案 C（Regime 确认制）**：
  - `defensive_regime` 切换需连续 3 个交易日 QQQ 60 日收益 `< 0`（切 `down`）或连续 3 个交易日 `>= 0`（切 `up`），中间未满 3 日维持上一交易日 `regime` 状态。

---

## 4. 分阶段实施计划（Phase 1 立即执行，Phase 2 凭证据晋升）

| 阶段 | 内容 | 是否改变生产选股结果 | 交付物 |
|---|---|---|---|
| **Phase 1（本轮立即实施）** | ① **方案 D（报告可读性增强）**：在 `StockCardViewModel` 与 `action_list_v2.md` 中展示 `Streak: Nd`（连续在榜交易日数）及近边界提示；<br>② **离线多方案回放评估器**：在 13 个日频实盘快照 + 51 期冻结历史集上实测 `B0 / S1 / S2 / S3 / S4` | **否**（仅增强报告展示 + 产出离线对比证据） | `view_model.py`、`reporting/decision.py`、`scripts/evaluate_top15_turnover_stability.py`、`docs/top15_stability_validation_20261105/`、单元测试 |
| **Phase 2（审阅 Phase 1 报告后实施）** | 将 Phase 1 中通过全部验收门禁（G1–G4）的最佳方案正式接入 `entry.py` / `action.py` / `integrated.py` 并升级策略版本号 | **是** | 独立 PR |

---

## 5. Phase 1 详细技术规范（供 DeepSeek 执行）

### 5.1 报告可读性增强（方案 D — `view_model.py` / `reporting/decision.py` / `snapshot.py`）

1. **`StockCardViewModel` 新增可选展示字段**：
   - 在 `src/ai_value_scanner/decision/view_model.py` 的 `StockCardViewModel` 中新增：
     - `in_list_streak_days: int | None = None`（连续在 Top-15 主榜的交易日天数；`1` 表示今日新进 `NEW`，`>=2` 表示已连续在榜 `Nd`；无历史上下文时为 `None`）。
2. **连续在榜天数计算辅助函数 `compute_in_list_streaks`**：
   - 在 `src/ai_value_scanner/reporting/snapshot.py`（或 `decision/attention.py`）中提供纯函数：
     - 给定当前 `decision_date`、当前 `daily_symbols` 以及 `output_root`（扫描 `<output_root>/<prior_date>/<style>/run_manifest.json` 或传入历史每期 `daily_symbols` 序列），按交易日倒序回溯计算每只当前在榜股票的连续在榜天数 `streak >= 1`；
     - 在 `write_decision_snapshot` 与 `scripts/render_snapshot_preview.py` 中，将该 `streaks_by_symbol: Mapping[str, int] | None = None` 传入 `render_action_list_v2` / `build_snapshot_view_model`；
     - 若未传入 `streaks_by_symbol`（如无历史上下文的单测），则当 `decision.previous_action_state == ActionState.PRIORITY_REVIEW` 且当前为 `PRIORITY_REVIEW` 时默认标记状态为延续，否则不渲染 streak 标签，保持向后兼容。
3. **卡片头部渲染格式（`reporting/decision.py`）**：
   - 当 `card.in_list_streak_days` 存在时，在 `<summary>` 标题行的 `#rank SYMBOL` 后紧跟紧凑标签：
     - `in_list_streak_days == 1` 且有历史快照时：显示 `[NEW]`（今日新晋）；
     - `in_list_streak_days >= 2` 时：显示 `[LIST {N}d]`（如 `[LIST 5d]`，直观区分长驻稳健股与今日新进股）；
   - 同步将 `src/ai_value_scanner/reporting/snapshot.py` 中的 `REPORT_RENDERER_REVISION` 升级为 `"mvp_report_renderer_2026-11-05"`。

### 5.2 离线换手率与稳定性评估器（`scripts/evaluate_top15_turnover_stability.py`）

编写完全离线、确定性的评估脚本 `scripts/evaluate_top15_turnover_stability.py`，支持以下两路评测并输出到 `docs/top15_stability_validation_20261105/`：

1. **Part A — 13 个日频实盘快照回放（2026-10-19 至 2026-11-04）**：
   - 自动按日期升序读取 `outputs/decisions/2026-10-19/production` 至 `outputs/decisions/2026-11-04/production` 共 13 个快照的 `decisions.jsonl`（从每条 `StockDecision` 的 `quality`、`entry.gate_results`、`entry.positives/risks` 提取各门限观测值：`price_to_sma200`、`price_to_sma50`、`return_20d`、`return_60d`、`relative_strength_60d_qqq`、`drawdown_from_52w_high`、`volatility_60d`、`days_below_sma200`、`sma50_to_sma200`、`regime`）；
   - 对 `B0_baseline`、`S1_confirm_2_2_safe`、`S2_confirm_1_2_safe`、`S3_hysteresis_buffer`、`S4_hybrid_hysteresis_regime` 五个方案逐日重建 Top-15 名单，计算并输出：
     - `mean_retained_count`（日均保留股票数，满分 15）与 `min_retained_count`（最差单日保留数）；
     - `mean_daily_turnover_rate`（日均换手率 `= 平均移出数 / 平均在榜数`）；
     - `one_day_whipsaw_count`（仅在榜 1 个交易日即被移出的总人次）；
     - `roundtrip_5d_count`（5 个交易日内“移出又重新移入”或“移入又移出再移入”的往返人次，重点核查 `ECL`、`MSFT`、`AAPL`、`MTCH`、`SSNC` 等典型样本的轨迹变化）；
     - `damaged_leaked_count`（在榜股票中处于 `TREND_DAMAGED` / `INSUFFICIENT_DATA` / `Quality C` 的次数，必须严格为 `0`）。
2. **Part B — 51 期冻结历史截面回放（39 期基准集 + 12 期 2022 熊市集）**：
   - 读取 `outputs/historical_selection_v1_20261011_03/repaired/company_quality_dataset_risk_off.v3.csv` 与 `outputs/historical_selection_bear2022_20261017_01/repaired/company_quality_dataset_risk_off.repaired.csv`（主口径 `ETF_SLICE`）；
   - 对比 `B0_baseline` 与 `S3_hysteresis_buffer`（月频截面可测阈值缓冲区与主榜纯净性）在 `ALL_51`、`BASE_39`、`BEAR_2022`、`FWD_DRAWDOWN_60D` 上的：
     - 跨月 Top-15 留存率、60d 日期等权平均超额收益（vs QQQ）、胜率、重伤率（`severe_loss_rate <= -20%`）。
3. **产物清单（写入 `docs/top15_stability_validation_20261105/`）**：
   - `report.md`（含 G1–G4 门禁裁决表、13 期逐日保留数对比表、典型股票 `MTCH/ECL/MSFT/AAPL` 轨迹对比表、51 期历史收益与回撤对照表）；
   - `daily_turnover_comparison.csv`（12 个日转换 × 5 个方案的保留/移入/移出明细）；
   - `scheme_summary_metrics.csv`（5 个方案的汇总指标）；
   - `historical_51dates_comparison.csv`（51 期历史回放指标）；
   - `SHA256SUMS`（所有生成文件的校验和，确保删目录重跑字节级一致，且不含任何本地绝对路径）。

### 5.3 预注册验收门禁（Gates G1–G4）

- **G1（日度稳定性）**：13 个实盘快照的日均保留数从 `9.5` 提升至 **`>= 12.0`**（或日均换手率下降 **`>= 35%`**），且 5 日内往返折返次数（Whipsaws）下降 **`>= 50%`**；
- **G2（风控零漏网）**：所有 13 个日频快照及 51 个月度截面中，`TREND_DAMAGED`、`INSUFFICIENT_DATA`、`Quality C/UNRATED` 混入 Top-15 的次数 **严格等于 `0`**；
- **G3（不追高 / 入场及时性）**：对比 `S3_hysteresis_buffer` / `S2_confirm_1_2_safe` 与 `S1_confirm_2_2_safe`，验证 `N=1` 进场不延迟方案能否在不牺牲稳定性的前提下避免 Day-1 回踩买点踏空；
- **G4（长期收益与回撤不劣化）**：51 期历史回放中，`ALL_51` 的 60d 日期等权超额收益劣化不超过 `1.0pp`，`BEAR_2022` 与 `FWD_DRAWDOWN_60D` 的重伤率不恶化。

---

## 6. Phase 2 生产集成规范（已拍板采用 `S2_confirm_1_2_safe`）

根据 Phase 1 实测结果（`docs/top15_stability_validation_20261105/report.md`）：
- `S2_confirm_1_2_safe`（进场 `N=1` 不延迟 + 软越界 `M=2` 确认退场 + 硬破位 `M=1` 当日立即熔断）将 13 个实盘快照的日均保留数从 **`9.58` 提升至 `12.50 / 15`**、日均换手率从 **`36.1%` 降至 `16.7%`**、一日游从 **`27 次` 降至 `2 次`（-93%）**、5 日往返从 **`22 次` 降至 `7 次`（-68%）**，且硬破位漏网为 **`0`**、底层 `Company Quality × Entry Quality` 阈值 **0 放宽**。

### 6.1 核心纯函数设计（`src/ai_value_scanner/decision/attention.py`）

1. 新增常量：
   - `DAILY_ATTENTION_STABILITY_POLICY_VERSION = "confirm_1_2_safe_v1"`
   - `HARD_OVERBOUGHT_SMA50_FOR_RETENTION = 1.12`
   - `HARD_OVERBOUGHT_RET20_FOR_RETENTION = 0.15`
2. 实现硬破位熔断判定函数 `is_hard_damage_for_retention(decision: StockDecision) -> bool`：
   - 当满足以下任一条件时返回 `True`（触发 `M=1` 当日立即移出，绝不给予驻留缓冲）：
     - `decision.entry.state in {EntryState.TREND_DAMAGED, EntryState.INSUFFICIENT_DATA}`
     - `decision.quality.grade in {QualityGrade.C, QualityGrade.UNRATED}`
     - `decision_metric_value(decision, "price_to_sma50")` 非空且 `> 1.12`
     - `decision_metric_value(decision, "return_20d")` 非空且 `> 0.15`
3. 实现软越界 1 日驻留缓冲判定函数 `is_soft_exit_grace_eligible(decision: StockDecision, previous_daily_symbols: Iterable[str]) -> bool`：
   - 仅当同时满足以下 4 个条件时返回 `True`：
     1. `decision.symbol in {str(s).strip().upper() for s in previous_daily_symbols}`（上一交易日在 Top-15 主榜内）；
     2. `decision.action_state is not ActionState.PRIORITY_REVIEW`（今日未达到标准 `PRIORITY_REVIEW`）；
     3. `decision.previous_action_state is ActionState.PRIORITY_REVIEW`（上一交易日其 canonical `action_state` 为 `PRIORITY_REVIEW`，说明今天是第 1 天软越界 `soft_streak == 1 < 2`；若次日仍未恢复 `PRIORITY_REVIEW`，次日的 `previous_action_state` 将是非 `PRIORITY_REVIEW`，从而在第 2 天自动移出，无需跨多日状态文件即可严格实现 `M=2`！）；
     4. `not is_hard_damage_for_retention(decision)`（未触发硬破位熔断）。

### 6.2 `select_daily_attention` 升级（`src/ai_value_scanner/decision/integrated.py`）

1. 扩展 `select_daily_attention` 签名（保持完全向后兼容）：
   ```python
   def select_daily_attention(
       decisions: Iterable[StockDecision],
       *,
       cap: int = DEFAULT_ATTENTION_CAP,
       previous_daily_symbols: Iterable[str] | None = None,
   ) -> tuple[StockDecision, ...]:
   ```
2. 选择逻辑：
   - **当 `previous_daily_symbols is None` 时**：保持现有旧行为不变（确保所有未传该参数的历史单测 100% 兼容）；
   - **当传入 `previous_daily_symbols` 时**：
     - 若 `previous_daily_symbols` 为空集合/空元组（例如首次运行无历史快照），退化为无历史模式（调用 `select_weekly_attention(ordered, cap=cap)`）；
     - 若 `previous_daily_symbols` 非空（启用 `S2_confirm_1_2_safe`）：
       1. 归一化 `incumbents = {str(s).strip().upper() for s in previous_daily_symbols if str(s).strip()}`；
       2. **在榜保留集合 `keep`**：遍历 `ordered`（按 `(d.priority, d.symbol)` 排序），若 `d.symbol in incumbents` 且（`d.action_state is ActionState.PRIORITY_REVIEW` 或 `is_soft_exit_grace_eligible(d, incumbents)`），加入 `keep`（最多取前 `cap` 个）；
       3. **新进候选集合 `candidates`**：遍历 `ordered`，若 `d.symbol not in incumbents` 且 `d.action_state is ActionState.PRIORITY_REVIEW`（`N=1` 进场不延迟），加入 `candidates`；
       4. 取 `slots = max(0, resolved_cap - len(keep))`，合并 `selected = keep + candidates[:slots]`；
       5. 按 `(0 if d.action_state is ActionState.PRIORITY_REVIEW else 1, d.priority, d.symbol)` 排序返回 `tuple(selected)`（确保正常 `PRIORITY_REVIEW` 排在前面，1 日缓冲驻留股紧随其后，且不再用一日游的 `AVOID` 降级股凑数）。

### 6.3 历史主榜读取与生产调用链（`reporting/snapshot.py` / `scanner.py` / `scripts/render_snapshot_preview.py`）

1. 在 `src/ai_value_scanner/reporting/snapshot.py` 中新增纯函数：
   ```python
   def load_previous_daily_symbols(
       output_root: str | Path,
       decision_date: str | date,
       *,
       strategy_style: str | None,
   ) -> tuple[str, ...] | None:
   ```
   - 查找 `<output_root>/<prior_date>/<style>/run_manifest.json` 中 `< decision_date` 的最近一期有效 manifest：
     - 若找到，返回 `tuple(str(s).strip().upper() for s in (manifest.get("daily_symbols") or []) if str(s).strip())`；
     - 若不存在任何历史同 style 快照，返回 `None`。
2. 在 `src/ai_value_scanner/scanner.py`（主快照与 shadow 快照两处 `select_daily_attention` 调用点）及 `scripts/render_snapshot_preview.py` 中：
   - 先通过 `load_previous_daily_symbols(decision_output_root, decision_date, strategy_style=...)` 获取上一期主榜符号；
   - 传入 `select_daily_attention(decisions, cap=decision_attention_cap, previous_daily_symbols=previous_daily_symbols)`。
3. 在 `run_manifest.json` 中记录稳定性策略标识（可选附加字段，保持旧验证兼容）：
   - `write_decision_snapshot` 写出 `run_manifest.json` 时记录 `"stability_policy_version": DAILY_ATTENTION_STABILITY_POLICY_VERSION`。

### 6.4 报告卡片对“软退场观察期（Grace Hold）”的透明披露（`view_model.py` / `reporting/decision.py`）

1. 当主榜卡片满足 `card.in_list_streak_days is not None and card.in_list_streak_days >= 2 and card.action_state != "PRIORITY_REVIEW"` 时：
   - 在 `reporting/decision.py` 的 `_v2_stock_card_block` 中，将在榜标签从 `[LIST {N}d]` 渲染为 **`[LIST {N}d · GRACE 1/2]`**；
   - 让使用者一眼看清：该股已在榜连续 `N` 天，今日因软边界轻微越界进入第 1 天驻留观察期（若次日仍未恢复 `ENTRY_READY` 将自动移出 Top-15）；
   - 同步将 `REPORT_RENDERER_REVISION` 升级为 `"mvp_report_renderer_2026-11-05b"`。
