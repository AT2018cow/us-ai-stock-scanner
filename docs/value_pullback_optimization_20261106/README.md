# 价值与回踩有界研究（2026-11-06）

按用户批准的[v4方案](../agent_specs/value_and_pullback_optimization_spec.md)执行。C中的P已另经批准，使用生产联合得分而非整数名次。研究规则、配置和输入身份均冻结，候选不自动推广生产。

- [最终报告](report.md)：主收益、期限/时代/压力期、候选判定及局限。
- [冻结协议](protocol.json)、[执行命令](commands.md)、`manifest.json`：参数、源码/配置/输入及结果身份。
- `baseline_parity.json`、`independent_checks.json`、`validation.json`：旧基线复现、独立收益复算与测试。
- `summary_by_horizon.csv`：20/60/120/252日，list与固定使用及共享池基准。
- `summary_by_era.csv`、`summary_by_year.csv`、`summary_by_market.csv`、`summary_era_eq4.csv`：分段及时代等权辅助视角。
- `paired_deltas_60d.csv`、`time_block_intervals.csv`：共同日期差值、连续时间区块区间与三假设Holm校正。
- `deployment_attribution.csv`、`stage_attribution_60d.csv`、`symbol_concentration.csv`、`casebook.csv`：实际部署、同部署诊断、阶段均值、公司依赖和代表名单变化。
- `coverage.csv`、`unavailable_outcomes.csv`：成熟度、缺失选中结果和明确假设的敏感性场景。
- `snapshot_20261105_top15.csv`、`snapshot_summary.csv`、`snapshot_validation.json`：不可变正式SIP快照的研究影子对照及缓存身份。
- `decision_status.json`、`candidate_decisions.json`、`acceptance_gates.csv`：初筛、最终判定和有条件工作跳过原因。
- `modal_execution.json`、`SHA256SUMS`：运行、清理和证据校验。

200次公司子集、共同删除Top5、阈值邻域及成本压力仅对通过长期月度主指标初筛的因素执行；压力期局部改善不触发该分支。未触发时不生成空CSV，原因记录在运行manifest中。完整成员表、原始CSV、日志和决策pickle留在gitignored outputs/Modal Volume，不纳入本紧凑证据包。

重叠cohort均值不代表账户CAGR，池内比较无法消除幸存者偏差，本研究不是全新OOS。报告必须结合覆盖和分红/成本限制解读。
