# v1.3.0 中短线选股与复核手册

v1.3.0 在原有 Company Quality × Entry Quality 和日报 Top-15 的基础上，增加正式名单状态检查、信号年龄与复核条件、可选的开盘和中线证据，以及可追溯的人工复核和纸面比较。用日报决定先研究谁，用详报核对证据，用盘中价格判断收盘后形成的计划是否仍有空间。

## 收盘后确认正式名单

在仓库根目录使用现有生产配置。升级后可重新执行一次 `.venv/bin/python -m pip install -e .`，使本地安装元数据与版本一致。已有 cron 时，日常先运行只读状态命令。需要手动正式发布或重试时，再用 cron 入口执行。

```bash
.venv/bin/python scripts/decision_status.py --style production
.venv/bin/python scripts/run_daily_cron.py --config configs/config.production.json
.venv/bin/python scripts/decision_status.py --style production --json
```

| 状态 | 如何阅读 |
| --- | --- |
| `current` | 已找到与期望交易日一致、来源和报告完整性均通过校验的正式 SIP 快照。开盘前和盘中，通常以最近已完成的交易日为准。 |
| `awaiting_sip` | 当前交易日已收盘，新名单仍在收盘后的 20 分钟等待窗口。此时可能仍显示上一期文件。 |
| `overdue` / `failed` | 到可发布时间仍缺少当期有效名单，或该期有失败回执。查看 `reason_code` 和相应正式尝试记录。 |
| `invalid` | 最新指针、时间、SIP 来源或归档内容未通过检查。先定位报告的校验错误。 |

输出包含期望日、已发布日、首次可读时间和可用报告路径。旧快照可能没有首次可读时间。后面三种告警状态 `overdue`、`failed`、`invalid` 的退出码为 1。正式回执位于 `outputs/decisions/publication_attempts/production/formal/`，可核对运行结果和失败阶段。调整开关、修改自选文件或比较报告时，用独立的 `--decision-output-root`，因为正式归档按交易日和档案身份保留。带 `--limit`、`--skip-scan` 或有扫描上限的运行属于非正式流程，正式发布以回执为准。

## 读日报、周报和详报

| 产物 | v1.3.0 的新增内容及读法 |
| --- | --- |
| `action_list.md` / `weekly_review.md` | 卡片增加 **Ready age** 和关键复核门检。 `[NEW]`、`[LIST Nd]` 和 `GRACE 1/2` 仍描述日报榜龄和宽限。启用形态时显示突破、回踩和已知事件摘要，启用中线时增加 **20–60 session context**。提供自选 CSV 时，两份报告都可增加 **Followed Stocks**，包括榜外仍可匹配的股票。 |
| `detailed/<SYMBOL>.md` | **Next Review Conditions** 列出条件、方向、观察值、阈值、余量、状态、时点和理由。余量使用原指标单位，百分比指标的余量以小数记录。按配置增加 **SIP Close Swing Review**、中线同行明细及 **Exact Filing Research**。 |
| `decisions.jsonl` / `run_manifest.json` | 结构化决策保存 `review_conditions`、`ready_age` 和启用时的 `swing_review`、`medium_review`、`financial_review`。manifest 记录决策文件摘要、报告渲染修订和输入证据。自选跟踪可同时保存结果与前日依据。 |

**Ready age** 从收盘确认日计第 1 个交易日。只有前一交易日能核验同一证券的非 Ready 状态时，才可追溯本轮首次 Ready 日。 `at least N trading session(s)` 是已观测天数的下界。 `unavailable for this session` 表示当日证据不足。经同日行情确认退出 Ready 时，才显示当日重置。

例如 v2 的 B 级股票需要 Quality 至少 0.68、Quality 置信度至少 0.80，并已达到 `ENTRY_READY` 且 Entry 分数至少 0.80，才符合优先复核条件。要判断还差哪一步，展开详报的 **Next Review Conditions**，重点查看标为 `blocking` 的条目。完整决策规则见 [README 的策略与报告说明](../README.md)。

启用中线或财务影子时，新快照使用 `mvp_report_renderer_2026-11-25a`。当前基础报告修订是 `mvp_report_renderer_2026-11-24b`。查看历史时以各自的 manifest 为准，旧快照可能没有新字段。

## 启用自选、形态、中线或财务证据

先复制生产配置，按需设置下表字段。形态与中线使用 `official_market_mode=sip_eod`，生产配置已满足。路径按仓库根目录解析。

| 配置 | 默认值 | 启用方式 |
| --- | --- | --- |
| `review_watchlist_csv` | 空 | 提供 UTF-8 CSV，列为 `symbol,cik,added_at_utc,reason`。时间需要时区。按代码与 CIK 匹配，退榜和被排除时也可显示原因。加入自选仅增加跟踪记录。 |
| `enable_swing_review` | `false` | 设为 `true`，保存收盘平台突破、回踩收复、确认日、失效位和阻力位。 |
| `swing_event_calendar_csv` | 空 | 可为形态报告提供带来源和首次可知时间的事件修订。缺来源、存在冲突或时间未确定时，查看报告的相应状态。 |
| `enable_medium_review` | `false` | 设为 `true`，增加已完成周的收盘与十周均线、60 日相对 QQQ 强弱，以及基于 SIC 的 5/20 日同行比较和覆盖率。 |
| `financial_coverage_json` | 空 | 提供财务证据数组，与归档最新定期申报的 CIK、accession、日期、表单和已知币种及期末匹配后显示。列作恢复候选或待审，原 Quality 继续用生产口径。 |

例如将配置副本保存为 `/tmp/scanner-swing.json`，在 SIP 可发布窗口运行：

```bash
.venv/bin/python run_scan.py --config /tmp/scanner-swing.json \
  --decision-output-root outputs/swing_review_trial
.venv/bin/python scripts/decision_status.py \
  --snapshot-root outputs/swing_review_trial --style production
```

新报告开关和自选内容随归档冻结。自选 CSV 缺失或有坏行时，`Followed Stocks` 标为不可用，正式名单可以照常发布。财务审计及三源发现池可先用冻结快照离线检查。输入和具体命令见 [收盘形态与开盘复核](swing_setup_opening_review.md) · [财务覆盖、发现池与中线视图](medium_term_coverage_review.md)。

## 次日看开盘卡和盘中预览

收盘快照已启用形态时，可用下一交易日的观测文件生成开盘卡。观测文件由使用端提供，按股票代码记录报价来源、时间、接收时间和核验后的拆股清单；无拆股也要显式提供空清单。把命令中的 `YYYY-MM-DD` 换为**收盘快照**的交易日。

```bash
.venv/bin/python scripts/swing_review.py opening \
  --snapshot outputs/swing_review_trial/YYYY-MM-DD/production \
  --observations /tmp/swing-opening.json --format markdown
```

卡片用当下可观察价格 `P` 重算跳空、距结构失效位 `S` 的距离 `P−S`、到阻力 `R` 的距离 `R−P` 和两者之比。 `P≤S` 时标记失效，`P≥R` 时标记已越过目标。实际 SIP 开盘成交、日线开盘字段和盘前指示价各有来源标签。缺少阻力或有效拆股证据时，相应项显示缺失。可加 `--format json` 供后续程序读取。[开盘观测字段及示例](swing_setup_opening_review.md#开盘卡)

盘中监控和预览读取 IEX。两者共用行情时间及拆股检查，默认报价年龄上限 180 秒，个股与 QQQ 时差上限 120 秒。检查未通过时，查看显示的降级原因。预览目录有临时日报、周报、详报与 `preview_manifest.json`，临时复核条件带 IEX 标记。

```bash
.venv/bin/python scripts/intraday_watch.py --scope report
.venv/bin/python scripts/render_intraday_preview.py \
  --config configs/config.production.json --output-dir outputs/intraday_review_trial
```

[盘中输出与告警](intraday_watch.md)

## 记录人工决定并复盘

可在日常正式 cron 命令上追加 `--forward-ledger outputs/forward/ledger.sqlite3` 自动导入回执。也可用下面的命令补导入已经落盘的回执、查看本次针对哪些快照和个股开展观察：

```bash
.venv/bin/python scripts/forward_observations.py import-receipts --style production
.venv/bin/python scripts/forward_observations.py list --kind snapshot
.venv/bin/python scripts/forward_observations.py list --kind observation --parent SNAPSHOT_ID
.venv/bin/python scripts/forward_observations.py summary PROTOCOL_ID
```

先登记协议，再同期记录人工选择（`deep_dive`、`wait`、`reject`）及理由、用时和纸面计划。证据到期后再录入结算，提前退出需先按合同登记退出决定。摘要按观察协议、期限、成熟状态和 Ready 年龄展示覆盖及收益。登记、JSON 输入和结算例子见 [前向观察与纸面记录](forward_observation_ledger.md)。

要比较立即入场、等待确认、结构退出或候选排序，使用 `scripts/evaluate_swing_experiment.py` 先登记协议和冻结样本，再提供独立价格输入结算。这轮历史比较用了 11 个同版本正式 SIP 日档，成熟的等待结果来自 2 个日期、32 个持现金的机会。没有发生 FCF 候选排序换人。现有结果支持复查计算与纸面路径，改动正式交易优先级仍需要成熟的前向配对样本。[实验命令与门槛](swing_experiment.md) · [有界历史比较](swing_historical_bounded_20261125/README.md)
