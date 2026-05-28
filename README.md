# AI Undervalued US Stocks Scanner (Alpaca)

本项目会扫描 Alpaca 可交易的美国股票，结合 SEC 基本面与 ETF 观察清单（watchlist），输出两套候选：`core_ai`（AI核心）和 `ai_enabler`（AI基础设施受益）。

## 1. 本地初始化

```bash
git init
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

如果你不想 `pip install -e .`，也可：

```bash
pip install -r requirements.txt
PYTHONPATH=src python run_scan.py --help
```

## 2. 填写 `.env`

你只需要填写以下必填项：

```dotenv
ALPACA_API_ENDPOINT=
ALPACA_API_KEY=
ALPACA_API_SECRET=
SEC_USER_AGENT=ai-value-scanner your_email@example.com
```

可选项：

```dotenv
ALPACA_DATA_ENDPOINT=https://data.alpaca.markets
ALPACA_FEED=iex
```

说明：
- `ALPACA_API_ENDPOINT` 常见为 `https://paper-api.alpaca.markets` 或实盘 endpoint。
- `SEC_USER_AGENT` 建议写真实联系信息，避免被 SEC 限流。

## 3. 参数化筛选配置

默认参数在 `config.filters.json`，可按策略自由修改，核心维度包括：
- 双通道：`channel_profiles.core_ai`、`channel_profiles.ai_enabler`
- 观察清单成员过滤：`watchlist_bucket`/`watchlist_etf_count`（扫描阶段统一使用 watchlist 成员门槛）
- 追涨价格阈值：`momentum_min_return_20d`、`momentum_min_price_to_sma200`、`momentum_max_drawdown_from_52w_high`
- 三档分组：`triage_rules`（`keep/watch/drop`）
- 主题相关性：`watchlist_csv_path`、`watchlist_core_etfs`、`watchlist_enabler_etfs`
- 观察清单强度：`watchlist_etf_count`（可用于排序权重，不作为硬过滤必需）
- 估值参数（便宜程度）：`max_ps`、`max_pe`、`min_ps_discount`、`min_pe_discount`
- 价格位置/低位识别参数：`price_lookback_days`、`min_drawdown_from_52w_high`、`max_range_position_52w`、`max_price_to_sma200`、`min_days_below_sma200`、`max_20d_return`、`max_60d_volatility`
- 质量：`require_positive_revenue`、`require_positive_net_income`、`min_revenue`、`min_net_income`
- 流动性：`min_dollar_volume`、`min_price`
- 市值区间：`min_market_cap`、`max_market_cap`
- 行业过滤：`enable_sic_prefix_filters`、`include_sic_prefixes`、`exclude_sic_prefixes`、`include_sic_codes`、`exclude_sic_codes`
- 限速与性能：`max_workers`、`max_symbols`、`chunk_size`、`alpaca_max_requests_per_sec`、`sec_max_requests_per_sec`

说明：`enable_sic_prefix_filters` 默认 `false`（不叠加 SIC 前缀筛选）；即使关闭，`include_sic_codes`/`exclude_sic_codes` 仍生效。

### 3.5 ETF 观察清单（替代新闻打分）

当前版本已移除“新闻主题打分”作为主流程依赖，改为 ETF 观察清单打分：
- 默认清单文件：`data/ai_watchlist.csv`
- 扫描阶段只读取本地 watchlist，不会自动刷新
- watchlist 维护由独立脚本执行（需要时手工运行）
- 三清单统一执行“watchlist 成员 + 财务/价格/流动性”筛选，不再依赖新闻主题分数。

默认 ETF 集合：
- `core_ai`：`AIQ,BOTZ,ROBT,WTAI,SOXX,SMH,IRBO,ARKQ,IGV,IGM,FDN,PNQI,SOXQ,XSD,KOMP`
- `ai_enabler`：`DTCR,IFRA,XLI,XLU,NLR,URA,SKYY,CLOU,SRVR,GRID,CIBR,IHAK,BUG,PAVE,IGF,IXP`

`data/ai_watchlist.csv` 字段：
- `symbol`：股票代码
- `bucket`：`core_ai` 或 `ai_enabler`
- `etf_count`：命中的 ETF 数量
- `etfs`：命中的 ETF 列表
- `enabled`：是否生效（`1/0`）
- `updated_utc`：更新时间
- 注意：扫描端按上述字段做严格校验，不再兼容旧 schema。

生成与维护方式（定稿）：
1. 手工刷新（按需执行，不随扫描自动触发）

```bash
python scripts/refresh_ai_watchlist.py --config config.production.json --output data/ai_watchlist.csv
```

2. 人工维护（可选）
- 直接编辑 `data/ai_watchlist.csv`
- 常见动作：新增符号、调整 `bucket`、设置 `enabled=0` 排除符号

3. 扫描执行
- `run_scan.py` 只读取本地 `data/ai_watchlist.csv`
- 若文件缺失或为空，扫描会直接报错并提示先刷新

当前可接受风险（后续有时间再优化）：
1. ETF 持仓抓取目前基于网页解析，若页面结构变化可能需要调整解析逻辑。
2. 暂无自动差异报告（新增/移除/桶变更），当前通过结果文件人工复核。
3. 暂无独立 `manual_overrides` 层（强制纳入/排除）；当前通过直接编辑 `ai_watchlist.csv` 实现。
4. 观察清单刷新采用手工触发，不在扫描阶段自动更新；建议在定期刷新后做一次人工抽检。
5. 暂无按日期归档的 watchlist 快照；当前可通过版本控制（git）追踪变更历史。

### 3.6 Watchlist 定稿（2026-05-28）

当前 watchlist 机制已定稿，后续按此作为基线：
- 扫描端只使用本地 `data/ai_watchlist.csv`，不自动刷新。
- 扫描前先加载 watchlist，并将股票 universe 收缩到 watchlist 符号（不再先扫描全市场再过滤）。
- watchlist schema 严格校验：`symbol,bucket,etf_count,etfs,enabled,updated_utc`。
- 已移除 `source` 字段与旧 schema 兼容路径（项目未上线前主动去除遗留逻辑）。
- `watchlist_etf_count` 与 `watchlist_etfs` 使用统一口径：`etf_count = 去重后 etfs 数量`。

### 3.4 生产参数固化（v1）

生产参数基线放在 `config.production.json`，用途是稳定运行，不随实验来回波动。  
当前冻结原则：
- 保留三清单并行（`Low-Value` / `Industry-Trend` / `Momentum`）
- 保持 `enable_sic_prefix_filters=false`（默认不叠加 SIC 前缀）
- 采用已通过全量样本回归验证的平衡阈值（可稳定产出且不过度放宽）
- 将高纯度/高收紧参数留在实验配置中，不直接进入生产默认

建议：
- 生产运行默认使用 `config.production.json`
- `config.filters.json` 继续作为策略实验配置

### 3.1 价格位置/低位识别参数

价格位置参数分两层：
- 全局层（`config.filters.json` 顶层）：给所有通道提供默认值
- 通道层（`channel_profiles.<channel>`）：可覆盖全局默认值

参数说明：
- `price_lookback_days`
  - 含义：回看日K线窗口（自然日），用于计算 52 周高低区间与 SMA 基准
  - 默认：`420`
  - 调大：更平滑，响应更慢
  - 调小：更敏感，波动更大
- `min_drawdown_from_52w_high`
  - 含义：距区间高点最小回撤比例，`1 - price/high_52w`
  - 取值：`0~1`，越大越“离高点远”
  - 示例：`0.20` 表示至少较高点回撤 20%
- `max_range_position_52w`
  - 含义：当前价格在区间 `[low_52w, high_52w]` 的相对位置
  - 公式：`(price-low_52w)/(high_52w-low_52w)`
  - 取值：`0~1`，越小越靠近区间底部
  - 示例：`0.70` 表示仅保留位于区间下 70% 的标的
- `max_price_to_sma200`
  - 含义：当前价格相对 200 日均价的倍数
  - 公式：`price / SMA200`
  - 取值：通常大于 0
  - 示例：`1.10` 表示价格不超过 200 日均价的 110%
- `min_days_below_sma200`
  - 含义：最近连续低于各自 200 日均线的交易日数量下限
  - 取值：`>=0` 的整数
  - 默认：`core_ai=7`，`ai_enabler=5`
  - 示例：`10` 表示要求至少连续 10 个交易日位于 200 日均线下方
- `max_20d_return`
  - 含义：最近 20 个交易日价格涨幅上限，避免追短期急拉
  - 公式：`price / close_20d_ago - 1`
  - 默认：`core_ai=0.12`，`ai_enabler=0.18`
  - 示例：`0.15` 表示 20 日涨幅不超过 15%
- `max_60d_volatility`
  - 含义：最近 60 日年化波动率上限，过滤高波动“低位陷阱”
  - 公式：`std(daily_return_60d) * sqrt(252)`
  - 默认：`core_ai=0.70`，`ai_enabler=0.85`
  - 示例：`0.60` 表示年化波动率不超过 60%

说明：
- `PE/PS` 等属于估值参数（衡量“便宜”），不是价格位置参数（衡量“低位”）。
- 两类建议同时使用：先做低位识别，再做估值约束。
- `ai_and_enabler` 适合做高纯度模式（同时要求 AI 与 enabler 信号达标）。

配置示例（全局默认 + 通道覆盖）：

```json
{
  "price_lookback_days": 420,
  "min_drawdown_from_52w_high": null,
  "max_range_position_52w": null,
  "max_price_to_sma200": null,
  "min_days_below_sma200": 5,
  "max_20d_return": 0.18,
  "max_60d_volatility": 0.85,
  "channel_profiles": {
    "core_ai": {
      "min_drawdown_from_52w_high": 0.2,
      "max_range_position_52w": 0.7,
      "max_price_to_sma200": 1.1,
      "min_days_below_sma200": 7,
      "max_20d_return": 0.12,
      "max_60d_volatility": 0.7
    },
    "ai_enabler": {
      "min_drawdown_from_52w_high": 0.15,
      "max_range_position_52w": 0.8,
      "max_price_to_sma200": 1.15,
      "min_days_below_sma200": 5,
      "max_20d_return": 0.18,
      "max_60d_volatility": 0.85
    }
  }
}
```

### 3.2 如何扩展新的筛选参数

如果你要新增一个参数（例如 `min_gross_margin`），按下面路径扩展：
- 第 1 步：在 `ScanConfig` 增加字段和默认值（`src/ai_value_scanner/scanner.py`）
- 第 2 步：在 `resolve_channel_profile` 增加“全局默认 + 通道覆盖”的解析逻辑
- 第 3 步：如果依赖新数据源/新指标，在数据准备阶段计算新列（如 `run_scan` 或相应 helper）
- 第 4 步：在 `build_filter_steps` 增加筛选条件（`lambda frame: ...`）
- 第 5 步：如需参与排序，在 `score_and_rank` 的标准化与权重中接入
- 第 6 步：在 `config.filters.json` 增加参数键，并给出初始策略值
- 第 7 步：在 README 的“参数说明”和“输出字段说明”同步更新

建议：新增参数后，先跑 `--max-symbols 500/1000` 观察 `*_diagnostics_*` 的“首因失败”分布，再跑 watchlist 全量。

### 3.3 当前版本筛选逻辑（v2）

当前版本核心原则：
- AI 相关性由 watchlist 维护脚本负责（ETF 持仓映射），扫描阶段不再计算 `ai_score/enabler_score`。
- 排序主因子为估值折价、流动性、价格位置和 watchlist 覆盖广度（`watchlist_etf_count`）。
- 输出拆分为三清单（并行）
  - `*_ranked.csv`（Low-Value）：低位+估值优先，偏“择时/估值”。
  - `*_ranked_industry_trend.csv`（Industry-Trend）：主题相关性优先，偏“产业跟踪”。
  - `*_ranked_momentum.csv`（Momentum）：强势追涨优先，偏“强者恒强”。
  - 三者是并行、正交逻辑，不是父子子集关系。

## 4. 运行方式

策略执行顺序：
- 先按需手工刷新 watchlist（非每次必做）
- 先读取本地 watchlist，并将可交易股票 universe 收缩到 watchlist 符号
- 再做价格/流动性预筛，然后请求 SEC 基本面
- 计算估值与价格位置指标
- 合并 ETF 观察清单字段（`watchlist_bucket/watchlist_etf_count/watchlist_etfs`）
- 生成三清单：`low-value`、`industry-trend`、`momentum`


先小样本验证（例如 300 只）：

```bash
python run_scan.py --max-symbols 300 --top-n 30
```

说明：`--max-symbols` 会在 watchlist universe 内按 `dollar_volume`（快照成交额）降序取样，避免按原始顺序截断带来的样本偏差。

运行时终端会持续打印：
- 当前阶段（`[1/6]...[6/6]`）
- 耗时与状态时间戳
- SEC/News 长阶段的进度百分比
- 失败时的错误类型与 traceback

全量扫描：

```bash
python run_scan.py
```

自定义配置文件：

```bash
python run_scan.py --config config.filters.json --top-n 100
```

导出过滤诊断（每一步剔除数量 + 唯一首因统计）：

```bash
python run_scan.py --diagnostics-output outputs/diagnostics.csv
```

导出网络/限流诊断（统计 429、重试、超时、连接错误、限速等待时长）：

```bash
python run_scan.py --network-report-output outputs/network_report.json
```

导出详细分析报告（markdown）：

```bash
python run_scan.py --report-output outputs/run_report.md
```

单独刷新 ETF 观察清单（可选）：

```bash
python scripts/refresh_ai_watchlist.py --config config.production.json --output data/ai_watchlist.csv
```

推荐运行节奏：
- `daily_full_scan`（每天 1~多次，watchlist 全量）

```bash
.venv/bin/python run_scan.py --config config.production.json
```

- `intraday_quick_scan`（日内快速复核，可选）

```bash
.venv/bin/python run_scan.py --config config.production.json --max-symbols 1200 --top-n 30
```

建议时点：
- `daily_full_scan`：每个交易日收盘后（或盘前）
- `intraday_quick_scan`：盘中按需多次
- `watchlist_refresh`：每周 1 次（建议周末或周一盘前）

## 5. 运行状态与进度说明

程序运行时会持续打印结构化日志：
- 格式：`[HH:MM:SS][LEVEL][+elapsed_seconds] message`
- 阶段：`[1/6]` 到 `[6/6]`
- 长耗时进度：
  - `SEC fundamentals: x/y (z%)`
  - `Watchlist refresh: rows=...`
- 失败时会打印：
  - 异常类型
  - 异常信息
  - 完整 traceback

程序结束时会打印简短清单：
- `=== Low-Value Shortlist (Top 3 Per Channel) ===`
- `=== Industry Trend Shortlist (Top 3 Per Channel) ===`
- `=== Momentum Shortlist (Top 3 Per Channel) ===`
- `Low-Value` 展示 `keep/watch` Top3（不展示 `drop`）
- `Industry-Trend` 与 `Momentum` 展示各自打分 Top3

## 6. 输出文件命名与含义

网络诊断输出：
- 默认：与结果 CSV 同名后缀 `_network.json`
- 可通过 `--network-report-output` 指定路径

输出结果文件：
- 默认命名：`outputs/ai_value_scan_YYYYMMDDTHHMMSSZ_<scope>_ranked.csv`
- 分通道结果：`..._ranked_core_ai.csv`、`..._ranked_ai_enabler.csv`
- 产业趋势清单：`..._ranked_industry_trend.csv`
- 产业趋势分通道：`..._ranked_industry_trend_core_ai.csv`、`..._ranked_industry_trend_ai_enabler.csv`
- 追涨清单：`..._ranked_momentum.csv`
- 追涨分通道：`..._ranked_momentum_core_ai.csv`、`..._ranked_momentum_ai_enabler.csv`
- 详细报告：`..._ranked_report.md`
- 过滤诊断：`..._ranked_diagnostics_<channel>.csv`
- 首因诊断：`..._ranked_diagnostics_<channel>_first_fail.csv`
- 其中 `<scope>` 为 `full` 或 `sample<max_symbols>`

示例（全量扫描）：
- `outputs/ai_value_scan_20260526T013236Z_full_ranked.csv`
- `outputs/ai_value_scan_20260526T013236Z_full_ranked_core_ai.csv`
- `outputs/ai_value_scan_20260526T013236Z_full_ranked_ai_enabler.csv`
- `outputs/ai_value_scan_20260526T013236Z_full_ranked_network.json`
- `outputs/ai_value_scan_20260526T013236Z_full_ranked_report.md`

## 7. 输出字段说明

主结果 CSV（`*_ranked.csv`）关键字段：
- `channel`：候选通道（`core_ai` 或 `ai_enabler`）
- `symbol` / `company_name`：股票代码与公司名
- `price` / `dollar_volume`：价格与日美元成交额
- `drawdown_from_52w_high`：距 52 周高点回撤比例（越大越接近低位）
- `range_position_52w`：当前价格在 52 周高低区间中的相对位置（越小越接近低位）
- `price_to_sma200`：当前价格 / 200 日均价（越小越偏低）
- `days_below_sma200`：最近连续低于 200 日均线的天数（越大越“压在均线下方”）
- `return_20d`：最近 20 日涨跌幅（用于限制过快反弹）
- `volatility_60d`：最近 60 日年化波动率（用于控制波动风险）
- `market_cap` / `revenue` / `net_income`：市值与基本面
- `ps` / `pe`：估值倍数
- `peer_median_ps` / `peer_median_pe`：同 SIC 行业中位估值
- `ps_discount` / `pe_discount`：相对行业折价（`1 - 自身/行业中位`）
- `watchlist_etf_count`：观察清单 ETF 命中数量
- `watchlist_bucket` / `watchlist_etfs`：观察清单分类与命中 ETF 信息
- `news_count`：固定为 `0`（已移除新闻打分依赖）
- `composite_score`：通道内综合评分
- `triage_label`：`keep/watch/drop` 三档分组

## 8. 缓存与网络诊断说明

`*_network.json` 按服务输出网络统计（`alpaca` / `sec`）：
- 请求：`requests_started`、`responses`
- 状态码：`http_2xx`、`http_4xx`、`http_429`、`http_5xx`
- 重试：`retries`、`retry_429`、`retry_5xx`
- 异常：`exceptions_total`、`exceptions_timeout`、`exceptions_connection`
- 限速等待：`limiter_wait_calls`、`limiter_wait_seconds`
- SEC 缓存：`cache_hits`、`cache_misses`、`cache_hit_rate`

终端摘要会额外打印：
- `SEC cache: hits=..., misses=..., hit_rate=...%`

`had_rate_limit_or_network_issue` 为 `true` 时，表示本次运行中出现了限流/网络异常信号。

## 9. 评分逻辑（默认）

结果会额外给出 `triage_label`（`keep/watch/drop`），规则在 `triage_rules` 中可调。

- `ps_discount = 1 - (ps / 同SIC行业中位数ps)`
- `pe_discount = 1 - (pe / 同SIC行业中位数pe)`
- 默认综合评分主要使用：`ps_discount`、`pe_discount`、`liquidity`、`watchlist_etf_count`
- 可选价格位置维度：`range_position_52w_low`（即 `1-range_position_52w`）、`days_below_sma200`、`drawdown_from_52w_high`
- 各通道权重由 `channel_profiles.<channel>.score_weights`、`trend_score_weights`、`momentum_score_weights` 配置

## 10. 回测模块（MVP+）

回测入口：

```bash
python run_backtest.py --mode historical_replay --scan-config config.production.json
```

常用参数：
- `--mode historical_replay`（历史重放）或 `--mode existing_runs`（仅重放已有扫描文件）
- `--outputs-dir outputs`
- `--list-types low_value,industry_trend,momentum`
- `--top-n 10`
- `--per-channel-top-n` / `--no-per-channel-top-n`
- `--horizons 20,60,120`
- `--start-date 2024-01-01 --end-date 2026-05-26`
- `--rebalance-frequency weekly|monthly`
- `--replay-max-symbols 800`
- `--replay-asset-status all|active|inactive`
- `--enable-perturbation` / `--no-perturbation`
- `--theme-source rules_proxy|historical_news|latest_scan|zero`
- `--historical-news-lookback-days 180`
- `--historical-news-limit-per-symbol 80`
- `--delist-return-assumption -0.55`
- `--delist-detection-buffer-days 7`
- `--max-runs 60`（仅 `existing_runs` 模式）
- `--benchmark-symbols QQQ,SOXX,XLI,XLU`
- `--trading-cost-bps 15`
- `--dry-run`（仅构建信号，不拉取价格）

说明：
- `--outputs-dir` 同时用于回测产物输出目录；在 `existing_runs` 模式下，也用于读取历史 `ai_value_scan_*` 文件。

输出文件（默认 `outputs/backtest_<UTC>_*`）：
- `*_events.csv`：每次信号事件在各持有期的组合收益
- `*_summary.csv`：按清单类型与持有期聚合的统计指标（含 `n_events_total` 与 `n_events_valid`）
- `*_benchmarks.csv`：对应基准收益（默认含 `QQQ`）
- `*_segments.csv`：分段统计（如 `2023/2024/2025/2026YTD`）
- `*_report.md`：简版回测报告
- `*_report_network.json`：回测阶段网络统计

`historical_replay` 定义：
- 在历史调仓日（周/月）重建当日横截面并生成三清单信号
- 从信号日后的下一个交易日开仓，持有 `20/60/120` 个交易日
- 组合收益默认等权，支持交易成本（双边）
- 可输出 `base/loose/strict` 参数扰动结果用于稳健性比较
- 默认 `theme_source=rules_proxy`：基于公司元数据（名称/SIC描述）关键词静态打分，稳定可复现
- 支持 `theme_source=historical_news`：按每个调仓日回看历史新闻窗口打分（可选实验模式）
- 支持退市收益假设：当标的在回测窗口结束前明显提前消失，可按 `delist_return_assumption` 计入

`existing_runs` 定义：
- 回测对象是已有扫描结果文件（`ai_value_scan_*_ranked*.csv`）
- 每个扫描时点都视为一次“决策点”

重要局限：
- `historical_replay` 仍是近似 PIT，不等价于 CRSP/Compustat 级无偏研究库
- 即使使用 `replay-asset-status=all`，历史可交易池与真实当时成分仍可能存在偏差
- `theme_source=latest_scan` 仍有前视风险；不建议作为主评估口径
- `theme_source=historical_news` 受新闻可得性和文本噪声影响，稳定性弱于 `rules_proxy`
- 退市收益假设是模型参数，不是逐笔真实退市结算

后续优化清单（已确认，暂不在本次实现）：
1. 组合净值回放：
   - 从“事件平均收益”升级为“可执行组合回测”（固定资金、按调仓持仓、空仓处理、持仓延续）。
   - 增加组合级指标：`CAGR`、`MDD`、`Sharpe`、`Calmar`、回撤区间统计。
2. 生存者偏差控制：
   - 现有 `replay-asset-status=active` 可能高估效果。
   - 优先切到 `all` + 更严格退市收益处理；后续可接入历史成分库（如 CRSP/Norgate/Polygon）。
3. 交易可实现性建模：
   - 将交易成本从固定 bps 扩展为分层滑点模型（按市值/流动性分档）。
   - 引入容量约束（如单票成交不超过 ADV 某比例）。
4. 样本覆盖与统计稳健性：
   - 为回测单独配置“覆盖优先”参数，保证每期最小持仓数量。
   - 增加滚动分段统计与 block bootstrap 置信区间，检验稳健性。
5. 反前视审计增强：
   - 对公司名称/SIC 等元数据建立 as-of 快照，减少静态元数据引入的潜在前视偏差。
   - 将该审计过程纳入回测报告输出。

## 11. 你可能还想开通的服务（可选）

当前代码已使用：
- Alpaca Trading/Data API
- SEC EDGAR API（免费，无需密钥）

若你需要更高质量基本面，可额外接入第三方财务数据 API（例如更标准化的 TTM、前瞻一致预期、分行业估值基准）。

## 12. 快速上手与日常执行清单

最简使用流程：

1. 初始化环境

```bash
cd /home/ss/codex_ws/stock
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

2. 配置 `.env`（必填）

```dotenv
ALPACA_API_ENDPOINT=
ALPACA_API_KEY=
ALPACA_API_SECRET=
SEC_USER_AGENT=ai-value-scanner your_email@example.com
```

3. 小样本冒烟（先确认流程）

```bash
python run_scan.py --config config.production.json --max-symbols 300 --top-n 30
```

4. Watchlist 全量扫描（生产）

```bash
python run_scan.py --config config.production.json
```

5. 历史回测（默认稳定口径）

```bash
python run_backtest.py --mode historical_replay --scan-config config.production.json
```

建议的固定节奏：

- 每个交易日可执行 1~多次 watchlist 全量扫描

```bash
python run_scan.py --config config.production.json
```

- 日内快刷（观察 watch/momentum 变化，可选）

```bash
python run_scan.py --config config.production.json --max-symbols 1200 --top-n 30
```

- 每周一次刷新 watchlist（建议周末或周一盘前）

```bash
python scripts/refresh_ai_watchlist.py --config config.production.json --output data/ai_watchlist.csv
```

- 每周一次策略体检回测（建议关闭扰动以缩短时长）

```bash
python run_backtest.py \
  --mode historical_replay \
  --scan-config config.production.json \
  --theme-source rules_proxy \
  --no-perturbation \
  --replay-asset-status active \
  --replay-max-symbols 800
```
