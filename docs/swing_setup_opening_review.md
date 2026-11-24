# 收盘形态与开盘复核

在使用 `official_market_mode=sip_eod` 的配置副本中设置
`"enable_swing_review": true`。首次核验可通过 `--decision-output-root`
写到隔离目录。收盘证据随 `StockDecision.swing_review` 归档，日报、周报和详报
从同一份证据渲染。原决策排序按既有策略产生。

## 收盘形态

| 规则 | 首次确认 | 结束或资料不足 |
| --- | --- | --- |
| `breakout_20d_v1` | 当前收盘严格超过前 20 个完整交易日的最高价，且当前成交量至少为前 20 日中位数的 1.5 倍。平台宽度 `(U−L)/L` 至多 15%。 | 收盘低于锁定的 U 或确认后经过 20 个交易日时结束。结束后需 20 个新的完整交易日构成下一次平台。 |
| `pullback_reclaim_v1` | SMA50 ≥ SMA200，前收高于回落日 SMA50，回落日收盘不高于 SMA50，且当日量低于前 20 日中位数。随后第 1 至第 5 个交易日内，第一次收盘高于该日 SMA50 即确认。 | 触发前若收盘低于回落日低点，优先结束。第 5 日后仍无确认时结束。确认后，收盘低于锁定低点时失效。 |

连续交易日使用 NYSE 日历。输入必须有合法、连续的 OHLCV，成交量基准为零时保持资料不足。
历史价格、成交量和已冻结价位统一到当前信号的拆股口径。形态确认时冻结 S 和备选 R，
后续交易日沿用已冻结参考。R 取形成于平台或回踩前 120 个交易日内、已被两边各两根
完成日线确认、高于确认价且最近的局部高点。连续等高视作一个高点，并使用最后一个
等高日。没有 R 时，仍显示价差风险。最新完整周线单列。

用与扫描相同的函数复算冻结输入：

```bash
.venv/bin/python scripts/swing_review.py close /tmp/swing-close.json
```

输入含 `session`、`bars`（`t,o,h,l,c,v` 的 SIP 原始日线）、可选的
`splits`（`[ex_date, price_multiplier]`）和来自相邻上一交易日的 `prior`
收盘形态证据。按时序使用相同的输入窗口与前日状态可核对扫描与回放。
输出中的 `bars_sha256` 标识本次连续 OHLCV 证据的拆股统一口径。
前向台账导入时会保留收盘形态字段。研究对照仍在冻结的协议下单独登记和结算。

## 财报日历

可选 `"swing_event_calendar_csv": "data/local_event_calendar.csv"`。UTF-8 文件
按发行人记录事件及后续修订：

```csv
event_id,symbol,cik,event_type,event_date,session,known_at_utc,certainty,source
earnings-2026q4,EXM,0000000123,earnings,2027-02-01,postmarket,2026-11-23T21:30:00Z,estimated,issuer IR release URL
```

`session` 可为 `premarket`、`postmarket` 或 `unknown`。
`certainty` 可为 `confirmed`、`estimated`、`conflict` 或 `cancelled`。
使用同一事件 ID 追加每次修订，填原始来源和信息首次可知时点。
快照只收录生成时已知的修订。来源缺失、无法读取或只能看到未来修订时显示未知。
缺来源的新修订会令该事件当前状态变为未知。同日已经过去的盘前窗口单列，近期计划仍显示在摘要。
正式财报申报日与基本面证据年龄单独展示。历史复算可在 `close` 子命令加
`--event-calendar`，并在输入中提供 `symbol`、`cik` 和带时区的 `asof`。

## 开盘卡

```bash
.venv/bin/python scripts/swing_review.py opening \
  --snapshot outputs/decisions/YYYY-MM-DD/production \
  --observations /tmp/swing-opening.json --format markdown
```

输入以股票代码为键。每个对象可包含：

- `quote`，带 `kind`（`trade` 或 `quote`）、`price`、`timestamp`、
  `received_at`、`feed`（`iex` 或 `sip`）及 `source`。同刻双边价另带
  `bid`、`ask`、`bid_at`、`ask_at`。日线字段可用 `kind=daily_bar` 标记。
- `actual_open`，带 `kind=opening_trade` 和 SIP 的 `price`、`timestamp`、`received_at`、
  `feed` 和 `source`。若只有 SIP 日线开盘字段，使用 `kind=daily_bar` 和
  `session`，系统保留观测时间并将开盘成交的准确时间留空。
  已确认的延迟开盘成交采用其实际时间。
- `split_status=verified`、`split_source`、`split_checked_at` 及
  `splits` 数组。没有发生拆股时，以已核验的空数组记录。拆股核验必须在原交易日
  收盘后完成，并在本次开盘观测截止前可见。

开盘卡使用下一 NYSE 交易日的数据与已冻结收盘计划比较。默认报价年龄上限为
180 秒。可用 `--asof` 指定有时区的回放截止点。卡片显示开前指示或开后观测、
相对昨收的跳空、20 个 SIP 交易日的平均成交额、同刻价差和价格空间。
`P≤S` 时标记失效，`P≥R` 时标记已越过目标。
同一拆股比例换算昨收、R、S，当前报价以报价日自己的单位输入。
实际 SIP 开盘价有独立来源。纸面成交继续由前向台账的执行证据记录。

加 `--ledger outputs/forward/ledger.sqlite3` 可将开前和开后观测分别追加到已登记的
冻结快照，供 `forward_observations.py list --kind opening_review` 查阅。
