# 阶段 7 等待、退出与排序实验

这是独立的纸面研究。它不改日报成员、评分、阈值、订单或 cron。运行结果中的
`production_promotion` 始终为 false。突破 `breakout_20d_v1`、回踩
`pullback_reclaim_v1` 用不同协议 ID 登记和结算，样本不合并。

## 先登记并冻结，后结算

使用阶段 4 的 [前向观察账本](forward_observation_ledger.md)。研究文件存放在
正式快照树外的已存在目录。登记 JSON 包含以下字段，替换身份字段为待测快照的归档值。

```json
{
  "name": "breakout-2027q1-freeze-v3",
  "mode": "forward",
  "pattern": "breakout_20d_v1",
  "start": "2027-01-04",
  "through": "2027-03-31",
  "style": "production",
  "decision_policy": "v2",
  "config_fingerprint": "<canonical snapshot fingerprint>",
  "report_renderer": "mvp_report_renderer_2026-11-25a"
}
```

```bash
python scripts/evaluate_swing_experiment.py --ledger research/evidence.db \
  --snapshot-root outputs/decisions register --spec research/protocol.json
python scripts/evaluate_swing_experiment.py --ledger research/evidence.db \
  --snapshot-root outputs/decisions freeze --protocol PROTOCOL_ID --output research/cohort.json
python scripts/evaluate_swing_experiment.py --ledger research/evidence.db \
  --snapshot-root outputs/decisions evaluate --cohort research/cohort.json \
  --cohort-sha256 COHORT_SHA_FROM_FREEZE --prices research/prices.json --output research/outcome.json
```

- 登记协议冻结版本、配置、模式、起止交易日、计算合同及评估实现的源文件 SHA-256。
  前向登记须早于首日开盘。冻结与结算均验证实现哈希。代码变化后须登记新协议，
  不把旧协议或旧冻结文件混为新版本的前向样本。
  可用 `pressure_windows` 预登记压力区间，每项给 `name,start,through`。结果单列
  这些区间，不把切片重复计入全期。
  回顾性用 `mode=retrospective`，真实发布时点缺失时用归档生成时间与 SIP 发布时间下限
  的较晚者，明确标记为估计，不能进入前向样本。
- 前向只用与协议一致、决策内容哈希受保护、有首次可读正式回执的快照。预热、漏发、
  延迟、其他版本分别保留在覆盖表。冻结时未发生的会话保持待成熟。断档或证券身份
  不可接续的事件不重用旧确认。没有可核实的前一会话，不认定为首次观察。
- `freeze` 无价格输入，冻结来源哈希、观察/确认、当天仍在等待的对照名单、比较规则
  和排序成员。匹配同 Quality、同行业、60 日波动率差不超过 10 个百分点的其他公司，
  按标准 SIC 两位行业、近邻及固定证券 ID 匹配，排除占位 SIC。同日每类对照不重复使用同一公司。种子对照、匹配失败率和
  无确认、失效、到期、观察断档均独立统计。输出不覆盖既有文件，冻结哈希追加到账本。
- `evaluate` 要求账本上已有的冻结哈希，另读独立价格标签并拒绝晚于实际运行时间的
  `asof_utc`。结果同时保留明细与按日期
  等权的对比，不能从事后价格生成或更换成员。

## 价格标签

输入是独立 JSON。顶层包含 `feed="sip"`、`price_basis="raw"`、`source`、
带时区的 `asof_utc` 和 `securities`。证券键为 `TICKER:十位CIK`，QQQ 的键为
`QQQ:0001067839`。每个价格区间是已核对身份和公司行动的 NYSE 会话区间。

```json
{
  "feed": "sip",
  "price_basis": "raw",
  "source": "frozen label source ID",
  "asof_utc": "2025-11-06T22:00:00Z",
  "securities": {
    "AAA:0000000001": {
      "security_id": "AAA:0000000001",
      "identity_source": "archived security identity",
      "corporate_actions_source": "archived splits and cash distributions",
      "verified_from": "2025-11-04",
      "verified_through": "2025-11-05",
      "splits": [],
      "distributions": [],
      "events": {},
      "bars": [
        {"session": "2025-11-05", "o": 100, "h": 106, "l": 96, "c": 104,
         "close_known_at_utc": "2025-11-05T21:20:00Z"}
      ]
    }
  }
}
```

拆股是 `[生效交易日, 旧价格到新价格的乘数]`，例如 1 股拆为 2 股用 0.5。分红是
`[除息会话, 该日新股单位的现金分配]`，按持有资格转换并累计，持现金时无利息。
未发生拆股或分红也须明确给空列表。停牌、全天熔断、并购、退市和身份无法确认可标作
`suspended`、`halted_all_session`、`merger`、`delisted`、
`identity_unverified`。没有行情也没有事件证据为成熟缺价，不跳过缺价选择以后有利的
开盘。完全停牌可继续寻找窗口内第一个有价开盘。并购与退市没有凭证时不假设有结算。

标签的开盘价是常规时段日线开盘的纸面代理，不是成交或容量证明。若列表发布时当天
开盘已过，日线模式用下一个可排定的开盘，**不使用当天已过去的开盘或假造盘中成交**。
结构失效用收盘证据的首次已知时间。前向标签需要 `close_known_at_utc` 来触发退出，
没有时间的触发显式未知。回顾性标签缺少该时间时按 SIP 收盘发布时间下限估算。
确认及延迟路径仅用入场开盘前已经可知的早先收盘决定是否放弃。若计划仍有效，
开盘跳空低于结构位也按该开盘结算，不能看完同一笔开盘价再同时决定及成交。
若研究目标需要由开盘观察决定是否入场，应另立协议并提供其后的可执行报价。

## 研究输出与验收

| 输出 | 含义 |
| --- | --- |
| `paired_paths` | 等待 vs 立即、固定退出 vs 结构失效次开退出、确认组 vs 匹配及随机，1/3/5 日延迟的共同终点和等持有期 |
| `ranking_paths` | Quality → Entry → Priority → Top 15 → 归档实际日报含 S2，另列边界第 16–30 名、随机 K、全额与等部署 QQQ、现金权重与行业贡献 |
| `medium_summary` | 短线确认 × 十周均线状态的四种组合，20/60 日收益、下尾、MAE 和行业；60 日均线仍维持且短线失效的记录单列 |
| `comparisons` | 日期等权净差、交易日历块 95% 区间、非重叠切片、行业/年份/市场阶段、成本压力、最大贡献公司剔除和缺失样本敏感性 |

等部署 QQQ 按 Top-15 实际成交日拆分等权席位，从对应开盘到共同终点计算每批净收益。
未成交席位留现金。某个入场批次缺少同期 QQQ 开盘或后续价格证据时，等部署结果保留缺失。
中线持续性从信号当日已完成的最近一周起算。周末前最后一个交易日收盘发出的信号计入当周。

从入场日计第 1 日。主比较用 10 日，成本为每边 15bp，30bp 为压力。每边费用按
共同的入场价分母扣除。退出后至共同终点持现金，同一日线双障碍触发时给两端结果，
不猜日内顺序。排序候选只在同等级、同行业、同 Entry/风险门状态、同波动桶的连续
优先候选块内，且整块均有已验证的 USD 每股 FCF 和 SIP 价格时按 FCF 收益率重新排序。
已成熟日期若两侧持有相同证券及权重，即使共同价格标签缺失，也记差值为零，绝对
收益仍记未知。缺失压力测试不会填补这类已知零差。组合采用等权股票槽位，15 席不满时剩余持现金。

排序只比较同股本口径的每股 FCF 与原始 SIP 收盘价。期末日与价格日不同，财务影子
提取记录可携带 `market_share_bases` 数组，每项须有 `security_id`、
`share_basis_id`、`share_period_end`、`price_session`、`known_at_utc`、
`source` 和覆盖两日期间的 `splits`。没有拆股用有来源的空列表，不能省略。
证明最迟须在快照生成且可读时已知，并随原快照保留，不可用结算价文件补填。按拆股乘数
把每股 FCF 换到价格日口径。例如期末每股 8 美元、之后 1 股拆为 2 股、当日收盘
100 美元，收益率为 4% 而非 8%。缺乏可对齐证据时保留旧顺序。

退出主比较只纳入两条路径实际使用同一纸面入场成交的样本，取消、未成交和入场
不确定仍单列在覆盖统计。五日假突破率仅使用完整窗口已结束且有可判定结果的样本，
提前跌破单列。非重叠切片依据两条路径真实入场到退出的合并窗口，不按信号日
固定间隔抽样。公司贡献按候选腿正号、基线腿负号归属各自发行人，再按日期等权。

主判据为 10 日点估计至少 +0.30 个百分点、日历块均值区间下界大于零、30bp 时仍为
正、5% 下尾退化不超过 1 个百分点。最低成熟支持包括 40 个有配对结果的交易日、
4 个占用的日历块、10 家公司、单一公司占比不超 25%、至少 90% 配对价可用并且
至少 90% 注册日有可用快照。报告下尾抽样精度及缺失以 ±20 个百分点做压力时的
结果。阈值是预登记的研究判据，不是已验证收益，也不是交易触发条件。

### 独立算例

| 输入 | 手算 |
| --- | --- |
| 100 开盘入、104 收盘出 | +4.00% 毛收益，减双边 0.30%，净值回报 +3.70%；30bp/边时 +3.40% |
| 到共同终点仍未确认 | 现金回报 0%，无交易费用 |
| 100 开盘入，失效后次开 92 | 净值回报 −8.30%；退出日只纳入 92，不纳入其后高低价 |
| 入场 100，1 股拆为 2 股后 52 收盘，除息每新股 1 | 一股旧股对应 104 收盘市值与 2 现金，扣成本净回报 +5.70% |
| 同根日线越过下限 95 与上限 110，开盘在两者之间 | 顺序未知，分别给 95 与 110 的触碰情景 |

运行 `python -m unittest discover -s tests -p test_swing_experiment.py`。这些算例和历史
归档可验证合同、路径、可复现性及候选差异。只有真实自然发布的 SIP 回执、登记之后
形成并成熟的多会话样本才能验证使用价值。长时间全量历史重放按仓库规定放到 Modal
infi 前台运行。单元测试、回执读取或小样本结算不需要 Modal。真实待成熟前向证据
不得用昂贵的历史回放替代。历史通过也只能进入冻结的前向对照，中线采用另立主期限。
