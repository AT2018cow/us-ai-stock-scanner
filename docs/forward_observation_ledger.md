# 前向观察与纸面记录

台账保存正式 SIP 发布、人工复核、形态观察和纸面路径。默认数据库为本地的
`outputs/forward/ledger.sqlite3`。它包含人工选择和理由，应存放在私有目录。
台账在决策归档之外写入，所有记录及结算修订都有独立 ID。重复导入相同内容返回原 ID。
相同 ID 的内容冲突会报错。并发写入和逐次导入使用 SQLite 事务。

## 发布导入

```bash
.venv/bin/python scripts/forward_observations.py import-receipts --style production
.venv/bin/python scripts/forward_observations.py list --kind snapshot
.venv/bin/python scripts/forward_observations.py list --kind observation --parent SNAPSHOT_ID
```

可在原 cron 命令上追加 `--forward-ledger outputs/forward/ledger.sqlite3`。
它在正式回执落盘之后采集；台账写入失败时可用 `import-receipts` 恢复。正式的
失败、延后以及重跑回执也保留。重跑回执可补录先前已写入指针的首次可读时间。
待续的运行回执单独计数。名单外的合格决策也有观察记录，并保存原榜单位置、
原始收盘价（有同日完整 SIP 日线时）、门检、S2 原因和文件哈希。
前向证据通过回执中的 manifest SHA256 锁定原始决策文件的 SHA256。缺少该绑定的旧回执可用于历史分析。

可用 `import-archive outputs/decisions/YYYY-MM-DD/production` 导入无回执的旧归档。
该路径保留未知发布时间。允许复盘人工记录，纸面路径需要已核验的首次发布时间。
任意指令之前可指定 `--db` 和 `--snapshot-root` 以使用隔离环境。

## 冻结一次观察协议

每条写入命令用一个 UTF-8 JSON 文件，返回稳定、可引用的 ID。例如
`register protocol.json` 的文件可以是：

```json
{
  "version": "forward-v1",
  "style": "production",
  "decision_policy": "v2",
  "report_renderer": "使用待观察报告的实际 report_renderer_revision",
  "config_fingerprint": "使用待观察配置的实际指纹",
  "description": "同周同行业、等时间预算的复核与固定开盘纸面路径",
  "setup_versions": [],
  "paper_rules": ["next-open-v1"],
  "horizons": [5, 10, 20, 60],
  "fee_bps_per_side": 15
}
```

观察协议需要在相应名单首次发布前冻结。若版本、费用或期限变更，使用新的协议版本。
登记和记录时间由系统产生，业务观察时间使用带时区的 ISO 8601 时间戳。
同一纽约日期内且实际录入时间最迟在发布后首个可入场交易日收盘时的人工判断可纳入前向观察。
更换配置、决策策略或渲染修订时使用独立的观察协议。
旧版、迟录和发布时间未知的记录保留相应证据类型。

## 人工复核和形态

- `review review.json` 接受 `protocol_id`、`observation_id`、`workflow`
  （`baseline` 或 `new`）、`surface`（`daily` 或 `weekly`）、
  `displayed_at`、`read_at`、`decided_at`、`choice`
  （`deep_dive`、`wait` 或 `reject`）、`reason`、`budget_minutes`、
  `review_minutes`，以及可选的 `risk_codes` 数组和 `pair_id`。原流程
  记录另带实际展示文件的 `displayed_report_sha256` 和 `displayed_version`。
  配对要求同周、同行业、同类型榜单、同预算与不同证券。研究人员实际查看的案例应分别安排。
- `setup setup.json` 接受 `protocol_id`、`observation_id`、
  `setup_version`、`state`（`watching`、`confirmed`、`active` 或 `ended`）、
  `observed_at`、`source` 和非空 `evidence` 对象。候选观察和已确认形态
  独立记录。连续交易日的有效观察沿用事件 ID；遇到空档须确认连续性未知并重新确认。形态判定规则和可复算信号输入由阶段 5 提供。

## 纸面路径和结果

1. `paper plan.json` 使用 `protocol_id`、`observation_id`、`path`（`manual`
   或 `fixed`）、`rule_version`、`decision_at`、`status`（`planned`、
   `cash` 或 `unexecutable`）。人工路径引用 `review_id`。可选 `setup_id`
   引用该次已确认或持续中的形态。空席或不可执行需 `reason`。默认
   `execution_basis=next_open`，按决定之后首个 NYSE 正常开盘计。盘中选择
   `time_stamped` 时，需要严格晚于该决定的可执行报价。当前人工录入的报价归入补录组，直到可以证明其为第一笔可执行报价。计划和价格分开记。
2. `fill fill.json` 接受 `paper_id` 和 `status=entered`，以及
   `entry_at`、`entry_price`、`entry_source`、`price_basis`。执行失败以
   `status=unexecutable` 记录 `observed_at` 和 `reason`。
3. `settle outcome.json` 输入 `paper_id`、`horizon`、`asof`。入场日计第
   一个交易日，终点按该期限最后一日收盘。股票路径用同一价格基准的
   `exit_at`、`exit_price`、`exit_source`、`price_basis`，以及
   `equity_continuity`（`verified`、`unknown`、`broken`）。
   提前退出先用 `exit exit.json` 记录 `paper_id`、`decided_at` 和 `reason`，
   在下一可执行开盘前冻结退出决定，结算引用 `exit_id` 和 `exit_reason`。
   无同期退出证据的提前结算归入补录组。退出后持有现金至共同终点。缺失时填
   `missing_reason`。现金路径为零，不可执行保留缺失。修订提交新的
   `revision`、`revision_reason` 并用 `supersedes` 引用当前结果 ID。
   例如 100 入场、104 退出、15 bp/边的毛收益为 4%，净收益为 3.70%。

`summary PROTOCOL_ID` 显示正式发布覆盖、遗漏会话、日报和周报复核及配对统计，以及
按协议期限、证据类型和路径分组的成熟、尚未成熟与成熟缺证据计数。复核样本为空时
统计标为不可判定。真实人工效率及经济结果需要真实发布和样本自然成熟。
