# AI Undervalued US Stocks Scanner (Alpaca)

本项目会扫描 Alpaca 可交易的美国股票，结合 SEC 基本面与 Alpaca 新闻，输出两套候选：`core_ai`（AI核心）和 `ai_enabler`（AI基础设施受益）。

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
```

可选项：

```dotenv
ALPACA_DATA_ENDPOINT=https://data.alpaca.markets
ALPACA_FEED=iex
SEC_USER_AGENT=ai-value-scanner your_email@example.com
```

说明：
- `ALPACA_API_ENDPOINT` 常见为 `https://paper-api.alpaca.markets` 或实盘 endpoint。
- `SEC_USER_AGENT` 建议写真实联系信息，避免被 SEC 限流。

## 3. 参数化筛选配置

默认参数在 `config.filters.json`，可按策略自由修改，核心维度包括：
- 双通道：`channel_profiles.core_ai`、`channel_profiles.ai_enabler`
- 信号逻辑：`signal_logic` 支持 `ai_only`、`ai_or_enabler`、`ai_and_enabler`
- 趋势清单信号逻辑：`trend_signal_logic`（默认继承 `signal_logic`）
- 趋势信号阈值：`trend_min_ai_score`、`trend_min_enabler_score`（默认继承对应通道阈值）
- 追涨清单信号逻辑：`momentum_signal_logic`（默认继承 `trend_signal_logic`）
- 追涨信号阈值：`momentum_min_ai_score`、`momentum_min_enabler_score`
- 追涨价格阈值：`momentum_min_return_20d`、`momentum_min_price_to_sma200`、`momentum_max_drawdown_from_52w_high`
- 三档分组：`triage_rules`（`keep/watch/drop`）
- 主题相关性：`ai_keywords`、`enabler_keywords`、`news_lookback_days`
- 估值参数（便宜程度）：`max_ps`、`max_pe`、`min_ps_discount`、`min_pe_discount`
- 价格位置/低位识别参数：`price_lookback_days`、`min_drawdown_from_52w_high`、`max_range_position_52w`、`max_price_to_sma200`、`min_days_below_sma200`、`max_20d_return`、`max_60d_volatility`
- 质量：`require_positive_revenue`、`require_positive_net_income`、`min_revenue`、`min_net_income`
- 流动性：`min_dollar_volume`、`min_price`
- 市值区间：`min_market_cap`、`max_market_cap`
- 行业过滤：`enable_sic_prefix_filters`、`include_sic_prefixes`、`exclude_sic_prefixes`、`include_sic_codes`、`exclude_sic_codes`
- 限速与性能：`max_workers`、`max_symbols`、`chunk_size`、`alpaca_max_requests_per_sec`、`sec_max_requests_per_sec`、`pre_news_top_liquid_symbols`

说明：`enable_sic_prefix_filters` 默认 `false`（不叠加 SIC 前缀筛选）；即使关闭，`include_sic_codes`/`exclude_sic_codes` 仍生效。

### 3.4 生产参数固化（v1）

生产参数基线放在 `config.production.json`，用途是稳定运行，不随实验来回波动。  
当前冻结原则：
- 保留三清单并行（`Low-Value` / `Industry-Trend` / `Momentum`）
- 保持 `enable_sic_prefix_filters=false`（默认不叠加 SIC 前缀）
- 采用已通过全市场回归验证的平衡阈值（可稳定产出且不过度放宽）
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

建议：新增参数后，先跑 `--max-symbols 500/1000` 观察 `*_diagnostics_*` 的“首因失败”分布，再跑全市场。

### 3.3 当前版本筛选逻辑（v2）

本版本对 AI 相关性与输出结构做了三项关键优化：

- 优化 1：关键词匹配从“子串命中”升级为“词边界/短语命中”
  - 目的：降低 `llm` 命中 `hellmann's` 之类的假阳性。
  - 影响：减少消费/食品等行业因文本噪声被误归类为 AI。

- 优化 2：支持 `ai_and_enabler` 高纯度模式
  - 使用位置：`signal_logic` 或 `trend_signal_logic`
  - 含义：必须同时满足 `ai_score >= min_ai_score` 且 `enabler_score >= min_enabler_score`
  - 实测结论：直接作为全局默认通常过严，容易导致候选过少；更适合用于“高置信度复核”。

- 优化 3：输出拆分为三清单（并行）
  - `*_ranked.csv`（Low-Value）：低位+估值优先，偏“择时/估值”。
  - `*_ranked_industry_trend.csv`（Industry-Trend）：主题相关性优先，偏“产业跟踪”。
  - `*_ranked_momentum.csv`（Momentum）：强势追涨优先，偏“强者恒强”。
  - 三者是并行、正交逻辑，不是父子子集关系。

当前默认建议（`ai_enabler`）：
- `signal_logic = ai_or_enabler`（用于 Low-Value，不让候选过快归零）
- `min_ai_score = 0.01`，`min_enabler_score = 0.08`
- `trend_signal_logic = ai_or_enabler`（用于 Industry-Trend）
- `trend_min_ai_score = 0.03`，`trend_min_enabler_score = 0.08`
- `momentum_signal_logic = ai_or_enabler`（用于 Momentum）
- `momentum_min_return_20d = 0.05`，`momentum_min_price_to_sma200 = 1.05`

如果你要进一步提纯：
- 第一优先：提高 `trend_min_ai_score` / `trend_min_enabler_score`
- 第二优先：将 `trend_signal_logic` 提升到 `ai_and_enabler`
- 不建议第一步就加严低位参数，否则会把强趋势基础设施股整体排掉

## 4. 运行方式

策略执行顺序（用于降限速风险）：
- 先做价格/流动性预筛，再请求 SEC 基本面
- 基于低位价值逻辑构建 low-value pre-news 候选池
- 基于趋势逻辑构建 industry-trend pre-news 候选池
- 基于追涨逻辑构建 momentum pre-news 候选池
- 对三个池子的并集请求 Alpaca News（避免趋势/追涨清单漏数）


先小样本验证（例如 300 只）：

```bash
python run_scan.py --max-symbols 300 --top-n 30
```

说明：`--max-symbols` 会在全市场候选里按 `dollar_volume`（快照成交额）降序取样，避免按原始顺序截断带来的样本偏差。

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

推荐运行节奏：
- `weekly_full`（每周 1 次，全市场）

```bash
.venv/bin/python run_scan.py --config config.production.json
```

- `daily_watch_refresh`（每个交易日 1 次，快速复核）

```bash
.venv/bin/python run_scan.py --config config.production.json --max-symbols 1200 --top-n 30
```

建议时点：
- `weekly_full`：周末或周一美股盘前
- `daily_watch_refresh`：每个交易日收盘后

## 5. 运行状态与进度说明

程序运行时会持续打印结构化日志：
- 格式：`[HH:MM:SS][LEVEL][+elapsed_seconds] message`
- 阶段：`[1/6]` 到 `[6/6]`
- 长耗时进度：
  - `SEC fundamentals: x/y (z%)`
  - `Alpaca news: x/y (z%)`
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
- `ai_score` / `enabler_score`：主题相关性得分
- `news_count`：参与打分的新闻数量
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
- `ai_score`：AI关键词命中得分
- `enabler_score`：数据中心/电力/基建/核能等受益关键词命中得分
- `core_ai` 和 `ai_enabler` 使用各自权重（`channel_profiles.<channel>.score_weights`）

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
