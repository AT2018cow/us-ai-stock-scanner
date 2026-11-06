# 2026-11-06 五项审查问题修复

状态：**五项审查问题均已修复并验收**。19项新增回归、全量1,363项测试通过；6个120日窗口、三组评估及配置绑定的补充归因均已完成。旧冻结报告、数据与不可变正式快照保持原样。详见[最终验收](report.md)。

| 编号 | 审查问题 | 实施 | 验收 |
| --- | --- | --- | --- |
| F01 | 估算日历包络误拒绝合法120日标签 | 收益生成、标签验证/未知结束日与拆股查询统一使用交易所日历结束日 | 六个固定日期、独立120个session金值、原始价复算、全量标签文本对比 |
| F02 | 独立日假期前周五被误当半日市 | 取消Sunday/Monday July 4之前周五的提前收盘推断，保留实际July 3、感恩节次日与Christmas Eve规则 | 2021/2022/2027正常收盘、真实July 3半日市、已有SIP快照出版时刻核对 |
| F03 | SIP每次运行的end时间戳导致缓存失效 | EOD缓存按完整session及feed/start/symbols标识；网络请求end继续使用延迟窗口 | 同日两次只请求一次、过期同日缓存可在故障时复用、mtime不刷新、次日不能复用旧日 |
| F04 | 评估/补充续跑未校验配置身份 | 两条续跑路径校验config_sha256；补充结果记录配置，生成前核对上游评估配置 | 实际续跑函数的变更/缺失配置回归，云端匹配与改动阈值探针 |
| F05 | 外部CSV计算后无法写provenance | 仓库内用相对路径、外部用绝对路径；输入/metadata先登记，完整bundle暂存后发布 | /tmp外部CSV完整CLI；注入写入失败后输出目录可重试 |

F01的[冻结修复计划](repair_plan.json)包含原CSV、metadata及拆股哈希。只修改6个窗口的4个120日结果字段，共3,893条记录；其余所有标签及特征保留原始CSV文字。[独立逐字段校验](label_repair_checks.json)、[窗口覆盖](repaired_windows.csv)、[原始价格复算](independent_raw_checks.json)。

F02依据[NYSE官方日历](https://www.nyse.com/trade/hours-calendars)。2027-07-02是正常session，门禁在17:21 UTC拒绝、20:20 UTC才允许出版。已有正式与smoke SIP快照均在正确收盘后生成，[核对记录](snapshot_gate_audit.json)通过，故不重抓SEC或覆盖旧名单。

本次仅修复正确性、缓存与研究工具，不调整生产财务/量价阈值、权重或0.06排序扣分，也不把样本恢复造成的收益数字变化称为策略增益。

证据：[收益前后对照](baseline_comparison.csv)、[独立汇总复算](independent_evaluation_checks.json)、[归因一致性](attribution_checks.json)、[配置续跑探针](checkpoint_guard_smoke.json)、[执行记录](modal_execution.json)、[最终验证身份](verification.json)、[执行与复现](commands.md)。
