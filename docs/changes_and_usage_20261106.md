# 2026-11-06 本轮修改与使用影响

这份说明汇总原计算修复、四项优化与专项验证、长期Top-15评估、SIP迁移及后续五项review修复。日常使用从本文开始；精确实验数字、源码/输入哈希和逐项验收保留在各阶段证据目录。

## 1. 对日常使用最重要的变化

**正式扫描命令不变，但正式生产配置改用历史SIP完整日线，交易日必须等纽约市场收盘至少20分钟后运行。盘中继续使用IEX监控工具。** `.env`不必改为SIP；普通日常使用不需要重新运行长期回测或Modal研究任务。

| 场景 | 当前行为 | 使用者需要做什么 |
| --- | --- | --- |
| 正式名单 | `config.production.json`强制使用历史SIP，不调用最新SIP快照；`risk_off`模板同样如此 | 继续使用生产配置，按收盘窗口运行 |
| 运行时点 | 按纽约当地日期判断。交易日盘前、盘中及收盘后不足20分钟拒绝正式扫描；休市日取最近完整session | 不用正式扫描替代盘中监控；半日市按实际收盘时间计算 |
| 盘中观察 | `intraday_watch.py`固定IEX，分别显示临时行情与实际快照基线来源；影子可能受feed差异影响 | 读取IEX标记和临时影子，不把它当作正式名单更新 |
| 环境配置 | 生产/risk_off的SIP模式覆盖通用`ALPACA_FEED`设置；盘中工具独立固定IEX | 可以保留`.env`中的`ALPACA_FEED=iex`，无需来回切换 |
| 成交额 | 数值门槛仍为200万美元，正式扫描现在使用SIP全市场成交量计算 | 不把它解释成原IEX门槛的等价换算或真实成交容量 |
| 数据缺失 | 缺少目标日QQQ或拆股获取失败会阻断正式输出；个股缺目标日按缺失排除，不回退IEX | 正式运行报错时查看错误和数据来源，不能只看旧CSV是否生成 |
| 缓存 | SIP/IEX隔离；正式日线按完整session、feed、start和标的集合复用。临时故障可使用同session过期缓存，并记录降级 | 不必手动删除原缓存；不把缓存降级当作新鲜网络数据 |
| 同日重跑 | 正式快照不可变；同日旧feed/不兼容政策快照不能当作新版本复用 | 独立验证使用新的decision输出根目录，并明确读取该根目录 |
| 试运行 | 生产配置的`--max-symbols`试跑也遵守收盘门禁；默认写入样本快照目录 | 样本跑不能充当全池正式名单或更新正式latest指针 |

以上默认行为针对production和risk_off。没有`official_market_mode`字段的旧研究配置仍保持兼容snapshot模式，不代表所有研究配置都已统一为SIP。

## 2. 常用命令与输出位置

在仓库根目录执行。日常正式扫描与原定时任务入口保持一致：

```sh
.venv/bin/python run_scan.py --config configs/config.production.json
.venv/bin/python scripts/run_daily_cron.py --config configs/config.production.json
```

无需给现有定时命令增加新参数；执行时间必须满足上方门禁。本轮没有改写系统crontab。

盘中使用只读监控：

```sh
.venv/bin/python scripts/intraday_watch.py --scope report
.venv/bin/python scripts/intraday_watch.py --scope report --poll 300 --save
```

默认正式产物仍在`outputs/decisions/<交易日>/production/`，主要查看`action_list.md`、`weekly_review.md`和`detailed/`。`outputs/decisions/latest_production.json`指向最新正式快照。**目录日期是行情交易日，可能与新加坡运行日期不同**，不应手工改成运行机器当天日期。

同日已有不可变快照而需要独立验证时，选择新的根目录。例如：

```sh
.venv/bin/python run_scan.py --config configs/config.production.json \
  --decision-output-root outputs/decisions_sip_review
.venv/bin/python scripts/intraday_watch.py \
  --snapshot-root outputs/decisions_sip_review --scope report
```

独立运行继续重做时需使用未被占用的新根目录；它不会替换默认`outputs/decisions/`中的旧快照或指针。也可用`--snapshot-dir`直接指定某一期快照。

本轮2026-11-05的旧IEX正式快照保留，新SIP验收名单另存于`outputs/sip_eod_migration/official_decisions/2026-11-05/production/`。查看这一份历史验收名单对应的监控：

```sh
.venv/bin/python scripts/intraday_watch.py \
  --snapshot-dir outputs/sip_eod_migration/official_decisions/2026-11-05/production
```

正式SIP模式下，决策快照或latest指针失败会使扫描失败。legacy CSV可能已经写出，**CSV存在不代表正式名单发布成功**。不要删除旧快照来绕过版本/来源检查。

## 3. 评分、名单与报告具体改了什么

| 修改 | 用户可见影响 |
| --- | --- |
| 负EBITDA杠杆修复 | 负债且盈利分母非正不再被负比率误判为优秀偿债能力；会出现明确风险，可能影响评级 |
| NaN/Inf修复 | 非有限财务值按缺失处理，不再形成满分；覆盖不足会如实呈现 |
| 不完整价格窗口修复 | 缺失价格/交易日不再被跳过后算成完整低波动；缺失或无效波动率不能确认ENTRY_READY |
| 人工复核支持 | 日报显示状态变化、在榜信息；提供重复占位、升级后降级、耗时与拒绝原因的可选统计入口 |
| 反方与估值解释 | 详细报告展示GAAP/调整后盈利估值、盈利±20%敏感性、事件日期未验证状态与反方证据 |
| 集中度解释 | 名单展示行业/SIC与来源分布，辅助人工复核共同暴露；ETF仍只作为候选发现背景 |
| 收盘数据源统一 | 正式价格与量价特征基于完整SIP数据，候选数量、名单成员或顺序可以与此前IEX运行不同 |

本轮没有调整原生产财务/量价阈值、Quality/Entry权重或0.06排序扣分。修正计算及放行规则仍可能改变评级和名单；没有通过回测的研究候选未推广。

解析缓存已升级至v10，旧版本不会被当作新计算结果命中，第一次刷新可能较慢；原始SEC缓存保留，不要求手动清空。旧正式快照保持不可变，政策/renderer兼容性按版本检查。

新增统计入口属于可选研究工具，不是日常扫描的新前置步骤。没有真实人工复核日志时，耗时等指标保持空缺。工具及日志格式见[原修复和四项优化说明](review_20261106/implementation_and_validation.md)。

## 4. 回测和研究工具的使用变化

- 股票与QQQ统一按交易所日历：信号后的下一session开盘至第N个session收盘。中途缺行不延长持有期，缺入场/退出端点不顺延补齐。
- 标签生成、结束日验证、未知结束日边界与拆股查询使用日历边界，修复120日合法窗口被旧估算包络拒绝的问题。
- 修改配置后，评估/补充续跑会检查配置、输入及源码身份；不匹配会拒绝复用。缺少配置身份的旧补充结果也不会静默通过。
- 新研究应使用新的输出目录/结果版本，并复用合适的冻结输入；配置改变不自动意味着必须重抓全部SEC或行情。不要改写旧manifest来强行续跑。
- 已有冻结CSV不会自动迁移。本轮修正后的SIP标签位于`outputs/review_followup_20261106/datasets/`；使用其他旧文件前仍需核对其标签合同与已知限制。
- 离线评估支持仓库外CSV路径；建议同目录提供同名`dataset.meta.json`。存在metadata时会校验已有标签的成本与进出场约定；缺少metadata会记录unknown，不补造来源。
- 输出必须是新目录；新版评估先暂存完整CSV/manifest/报告，失败时不发布占用最终路径的半成品。

本轮五项review修复恢复了6个120日窗口，长期120日有效日期110→115，2022周频51→52；长期全名单120日平均净收益由8.183%校正为7.821%。**60日主结果保持不变**。这些是日期等权持有期统计，不是年化或账户净值，也不构成新的收益提升证明。

旧报告中的阶段性测试数量与120日数字保留为历史证据；现行120日结果和最终1,363项测试记录以[五项修复验收](review_followup_20261106/report.md)为准。长期及压力期复现命令见[研究执行说明](review_followup_20261106/commands.md)。长任务继续使用infi、前台运行、先smoke。

候选池近似、财务覆盖、分红与真实成交成本等原有限制仍保留在验收报告中。

## 5. 文档与交付入口

| 需要查看的内容 | 文档 |
| --- | --- |
| 原三个修复、四项优化和四项专项验证 | [实施与验证记录](review_20261106/implementation_and_validation.md) |
| SIP正式名单、IEX盘中、同日快照迁移 | [SIP迁移说明](sip_eod_migration_20261106/README.md) |
| 最新五项review、修正后120日数值、哈希与验收 | [最终审查收尾报告](review_followup_20261106/report.md) |
| 日常配置范围 | [配置地图](../configs/README.md) |
| 盘中监控与临时影子 | [监控手册](intraday_watch.md) |

其他环境需要同步本轮代码与配置后才会生效。本轮没有新增下单或自动交易流程，正式名单仍供人工研究与决策。
