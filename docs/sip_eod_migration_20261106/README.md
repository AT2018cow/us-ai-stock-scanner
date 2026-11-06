# SIP收盘决策、IEX盘中监控与标签日期对齐

状态：**已完成并验收**。日期合同、SIP收盘名单、IEX盘中来源标记均已实施；受影响的长期/压力期收益和归因已重算。完整结果见[验收报告](report.md)，原始冻结证据保持不变。

## 执行合同

- `config.production.json`与防守配置采用`official_market_mode=sip_eod`。正式扫描强制SIP，无需最新快照权限；只在美股收盘20分钟后运行，节假日取最新完整session，明确`end`截止，不混入当天未完成日线。
- 正式价格与成交额均来自目标session的原始close与volume。沿用数值2百万门槛，明确升级为全市场成交额最低要求，不宣称与旧IEX门槛等价，也不为历史收益调参。完整SIP研究已有该数值口径；新的收益标签和报告另存。
- SIP与IEX缓存按目录隔离；无SIP完整session或拆股信息时不退回IEX。QQQ缺少目标session阻断出版，股票缺少目标session按缺失价格排除。旧日快照不改写，已有同日旧feed快照不能被当作新feed复用。
- `intraday_watch.py`固定IEX，终端和Markdown标明IEX临时数据；官方SIP名单不可变，影子状态仍是临时估计。
- 所有收益标签统一使用交易所calendar的下一session入场、第N个session退出。中间缺行不延长持有期；缺入场/退出端点明确不可用。数据尾端消失仍使用原有显式退市情景假设，不把假设当实测结算。

## 受影响的重做范围

复用冻结SEC/会计/技术输入及独立SIP原始行情、拆股记录，只重建20/60/120/252日未来标签；逐列断言所有非标签输入不变。重算SIP月度、2020/2022周频基线/候选、随机对照、区间与逐层归因/集中度/成本证据。原生产IEX报告保留为历史比较，不作为迁移后生产验收。

真实账户3股票smoke覆盖收盘SIP出版与IEX监控，全池SIP收盘扫描产生726份决策、日报/周报各15名，云端与本地校验通过。云端使用infi前台，每个重算阶段先smoke、最多2容器，全池扫描使用另一个容器；不使用detach。无新增策略候选、无广泛参数搜索。

## 操作

`python run_scan.py --config configs/config.production.json`、每日cron均使用配置中的SIP模式，覆盖`.env ALPACA_FEED=iex`；`.env`不需要改成sip，盘中监控独立固定IEX。收盘不足20分钟/盘中正式扫描会报错；使用`intraday_watch.py`监控价格。

不更改早期缺少行情的预热范围、候选池近似、实际交易成本与分红口径。完整正式决策仍用于人工研究，不证明收益贴近QQQ；日期与feed修复不是策略调参。

同日已有IEX不可变快照，因此本次SIP名单另存于[日报](../../outputs/sip_eod_migration/official_decisions/2026-11-05/production/action_list.md)和[周报](../../outputs/sip_eod_migration/official_decisions/2026-11-05/production/weekly_review.md)，旧快照及旧latest指针不改写。下一交易日默认正式入口/cron直接生成SIP快照。当天查看新SIP名单的IEX监控可显式传入本次快照目录，命令见[执行与恢复](commands.md)。

## 证据入口

- [收益汇总](baseline_results.csv)、[四组标签逐列校验](label_validation.json)、[122条股票×日期×期限标签变化](label_changes.csv)。
- [独立原始价格与拆股复算](independent_raw_checks.json)、[IEX错位根因实查](iex_misalignment_root_cause.json)。
- [长期评估](evaluations/sip_monthly/manifest.json)、[2020周频](evaluations/sip_covid_weekly/manifest.json)、[2022周频](evaluations/sip_bear_weekly/manifest.json)。
- [逐层归因变化](stage_changes.csv)、[长期归因与成本](attribution/sip_monthly/stage_comparisons.csv)。
- [全池验收](official_acceptance.json)、[Top-15](official/top15.csv)、[快照校验](official/validation.json)。
- [独立汇总校验](independent_evaluation_checks.json)、[独立归因校验](independent_attribution_checks.json)、[执行与清理](modal_execution.json)、[最终验证身份](verification.json)。
