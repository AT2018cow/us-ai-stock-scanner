# 决策快照目录

快照按照 `YYYY-MM-DD/<策略风格>/` 保存。同日不同策略风格分别存放；历史快照的策略风格以该目录和 manifest 为准。

| 文件 | 用途 |
| --- | --- |
| `action_list.md` | 当日优先复核与状态变化。 |
| `weekly_review.md` | 周度复核名单。 |
| `detailed/<股票代码>.md` | 个股决策和证据的详报。 |
| `decisions.jsonl` | 结构化决策记录，供验证、研究和报告使用。 |
| `run_manifest.json` | 交易日、策略和渲染版本、输入来源及快照身份。 |
| `universe_exclusions.jsonl`、`state_change_alerts.jsonl` | 候选池排除原因和状态变化记录，字段与存在情况取决于快照版本。 |
| `short_research.json`、`short_candidates.csv` | 启用下行研究时的研究结果与候选清单。 |
| `latest_<风格>.json` | 指向相应风格最近发布的快照。 |
| `publication_attempts/<风格>/<模式>/` | 定时任务的逐次发布回执和失败原因。 |

各期文件以对应 manifest 和快照校验结果为准。同日重跑可复用已发布快照。正式生产 SIP 的阅读版见 [reports/](../reports/README.md)，运行和状态查询见[使用手册](../../docs/swing_trading_user_guide.md)。
