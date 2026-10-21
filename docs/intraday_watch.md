# 盘中观测（Intraday Watch Monitor）—— 能力说明与操作边界

- 状态：可用（Phase 1 价格监控 + Phase 2 临时 Entry 影子）
- 引入提交：`f95c4de`（监控器）、`35135a4`（影子重估）
- 代码：`scripts/intraday_watch.py`；测试：`tests/test_intraday_watch.py`
- 工具条目：README §13.23

## 1. 定位

盘中观测是**只读辅助工具**，用于填补"每日决策快照"与"下一交易日"之间的可见性空白：

- 官方报告在 11:00 北京（23:00 ET）生成，基于最近一个**已收盘**交易日的完整数据；
- 美股盘中（北京 21:30–04:00）没有官方更新；
- 本工具用当前价格刷新重点名单，并给出"如果现在收盘，Entry 会怎么变"的临时影子。

它**不产生官方决策**：不写 `StockDecision`、不写决策快照、不改 Action List。

## 2. 监控范围（`--scope`）

| scope | 含义 |
|---|---|
| `report`（默认） | 最新 `action_list.md` 中列出的全部股票（Priority Review + Offense Track + Secondary Radar + Attention Changes） |
| `attention` | 决策池中 action_state 为 `PRIORITY_REVIEW` / `WATCH_PULLBACK` / `WATCH_BREAKOUT` 的全部标的 |
| `all` | 快照内全部决策（数百只；较慢，约 1 分钟） |
| `--symbols` | 显式名单（覆盖 scope） |

`--include-weekly` 可把 `weekly_review.md` 的名单并入 `report`。

## 3. 数据与计算

- 数据源：Alpaca snapshots（`latestTrade` / `minuteBar` / `dailyBar` / `prevDailyBar`）+ 日线（400 天回看）；默认 IEX feed；
- **缓存强制关闭**（`cache_enabled=False`）：避免生产配置 6 小时 TTL 在盘中返回旧价；
- 价格层：现价、Δ%、vs SMA50/SMA200、52 周回撤/位置、20d/60d 收益；
- 告警标记：`S50↓`（跌破 SMA50）、`S50✖`（当日下穿）、`S200↓`/`S200✖`、`EXT`（偏离 SMA200 >60%）、`HI`（距 52 周高 ≤3%）、`LO`（52 周低位）、`MOVE`（单日 |涨跌| ≥3%）、`PE`（财报窗口）；
- 影子层（Phase 2）：把当前价当作临时收盘价，替换当日未完成日线；复用生产
  `build_entry_quality_v2` 与 `map_action_state_v2`；Quality 沿用最新快照；QQQ 提供
  regime / trend filter / RS60；输出 `E official → E shadow`、Δscore、Action 变化与翻转的门
  （如 `overextension:PASS→BLOCK`）。

## 4. 安全边界（硬约束）

1. 只读：不写 `outputs/decisions/` 任何文件，不更新 `latest_*.json`；
2. `--save` 仅写 `outputs/intraday/<日期>/monitor_*.md`（本地、gitignored）；
3. 影子是临时/未验证结果，**不是决策**，不进入历史验证体系；
4. 官方决策仍是日级、不可变（R08 版本门与快照身份不受影响）；
5. IEX 盘中对薄流动性标的可能失真；影子只作参考。

## 5. 使用

```bash
# 默认：日报全部列出标的名 + 临时 Entry 影子（约 4 秒）
python scripts/intraday_watch.py

# 更宽范围
python scripts/intraday_watch.py --scope attention
python scripts/intraday_watch.py --scope all
python scripts/intraday_watch.py --symbols ADI,CTAS,MSFT

# 盘中循环 + 保存 markdown
python scripts/intraday_watch.py --poll 300 --save

# 只看价格，不要影子
python scripts/intraday_watch.py --no-shadow
```

### 5.1 `--scope report` 覆盖范围

`report` = 最新 `action_list.md` 中列出的全部标的，四块相加（以 2026-10-20 快照为例）：

| 来源 | 数量 |
|---|---|
| Priority Review | 15 |
| Growth Compounder Leaders（Offense） | 9 |
| Secondary Radar（Cap-Omitted + Secondary Watch） | 20 |
| Attention Changes | 8 |
| **合计** | **52** |

不包含决策池其余标的。需要更大范围时用 `--scope attention`（所有 PRIORITY/WATCH 状态，约百只）或 `--scope all`（全池，约 1 分钟）。周报名单与日报不同时，加 `--include-weekly` 并集。

### 5.2 推荐刷新时点与命令

美股常规时段为北京时间 21:30–04:00。建议两个固定时点：

| 时点 | 北京时间 | 命令 | 目的 |
|---|---|---|---|
| 开盘后 30 分钟 | 22:00 | `python scripts/intraday_watch.py --scope report --save` | 情绪定调、识别单日异动（`MOVE`） |
| 收盘前 30 分钟 | 次日 03:30 | `python scripts/intraday_watch.py --scope report --save` | 影子接近收盘价，预判次日名单翻转 |

工具本身不配置定时任务，两个时点需手工执行；也可以用 `--poll 300` 让同一进程每 5 分钟自动刷新（Ctrl-C 结束）。`--save` 写入 `outputs/intraday/<快照日期>/monitor_*.md`（本地、gitignored）。

只关心自选名单时用 `--symbols` 更快；只看价格、不要影子时加 `--no-shadow`：

```bash
python scripts/intraday_watch.py --symbols CRM,MU,OKTA,TEL --no-shadow
```

### 5.3 影子判读：先排除窗口滚动

影子把当前价当作临时收盘价，同时把 20/60 日窗口**向前滚动一根 bar**。若被滚出的那根 bar 恰是大幅波动日，`20d`/`60d` 收益会显著跳变，`ret20_band`、`ret60_trend`、`rs60_qqq` 等门可能在当日几乎无涨跌时翻转。

判读规则：先对照主表 `20d`/`60d` 与最新官方快照的同类值——差异大，说明是窗口边界；只有主表涨幅本身触发的翻转（如当日 `+5%` 把 `sma50_band` push 出 `0.98–1.08`）才是当日行情信号。

## 6. 限制与未来

- 不重算基本面 / Quality（基本面盘中不变）；pre-earnings 窗口沿用快照；
- 不模拟排名 / 优先级变化（仅 Entry 状态与 Action 映射；pre-earnings、非经营利得等优先级惩罚不在影子内）；
- 影子的 20/60 日窗口会随临时 bar 向前滚动，窗口边界的大幅波动可导致分数/门禁翻转与当日行情无关（判读方法见 §5.3）；
- 不自动交易、不连接券商；
- 若未来需要"盘中全量重选股"，必须先有前瞻证据与新的预注册实验，而不是直接扩展本工具。

## 7. 验证

- 15 个离线测试（范围选择、临时 bar 替换、影子状态差异、只读契约等）；
- 全量测试 1245 项通过（2026-10-21）。
