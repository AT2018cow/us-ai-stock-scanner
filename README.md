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
- 三档分组：`triage_rules`（`keep/watch/drop`）
- 主题相关性：`ai_keywords`、`enabler_keywords`、`news_lookback_days`
- 估值：`max_ps`、`max_pe`、`min_ps_discount`、`min_pe_discount`
- 质量：`require_positive_revenue`、`require_positive_net_income`、`min_revenue`、`min_net_income`
- 流动性：`min_dollar_volume`、`min_price`
- 市值区间：`min_market_cap`、`max_market_cap`
- 行业过滤：`include_sic_prefixes`、`exclude_sic_prefixes`、`include_sic_codes`、`exclude_sic_codes`
- 限速与性能：`max_workers`、`max_symbols`、`chunk_size`、`alpaca_max_requests_per_sec`、`sec_max_requests_per_sec`、`pre_news_top_liquid_symbols`

## 4. 运行方式

策略执行顺序（用于降限速风险）：
- 先做价格/流动性预筛，再请求 SEC 基本面
- 基于估值和行业做 pre-news 候选池
- 仅对 pre-news 候选池请求 Alpaca News


先小样本验证（例如 300 只）：

```bash
python run_scan.py --max-symbols 300 --top-n 30
```

运行时终端会持续打印：
- 当前阶段（`[1/5]...[5/5]`）
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

## 5. 运行状态与进度说明

程序运行时会持续打印结构化日志：
- 格式：`[HH:MM:SS][LEVEL][+elapsed_seconds] message`
- 阶段：`[1/5]` 到 `[5/5]`
- 长耗时进度：
  - `SEC fundamentals: x/y (z%)`
  - `Alpaca news: x/y (z%)`
- 失败时会打印：
  - 异常类型
  - 异常信息
  - 完整 traceback

程序结束时会打印简短清单：
- `=== Shortlist (Top 3 Per Channel) ===`
- 每个通道展示 `keep/watch` 的 Top3（不展示 `drop`）

## 6. 输出文件命名与含义

网络诊断输出：
- 默认：与结果 CSV 同名后缀 `_network.json`
- 可通过 `--network-report-output` 指定路径

输出结果文件：
- 默认命名：`outputs/ai_value_scan_YYYYMMDDTHHMMSSZ_<scope>_ranked.csv`
- 分通道结果：`..._ranked_core_ai.csv`、`..._ranked_ai_enabler.csv`
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

## 10. 你可能还想开通的服务（可选）

当前代码已使用：
- Alpaca Trading/Data API
- SEC EDGAR API（免费，无需密钥）

若你需要更高质量基本面，可额外接入第三方财务数据 API（例如更标准化的 TTM、前瞻一致预期、分行业估值基准）。
