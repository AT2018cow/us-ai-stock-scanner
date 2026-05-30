# AI Undervalued US Stocks Scanner (Alpaca + SEC)

基于 Alpaca 行情/交易元数据与 SEC EDGAR 基本面数据，对美股 `AI 观察清单`执行多通道筛选，输出三张候选清单：
- `Low-Value`：估值与质量优先
- `Industry-Trend`：产业趋势与主题联动优先
- `Momentum`：价格动量优先

项目默认只扫描本地 watchlist 中的股票，不执行全市场无约束遍历。

## 1. 核心能力

- Watchlist-only 扫描（候选池可控，执行速度稳定）
- 三池并行通道：`core_ai`、`ai_enabler`、`ai_peripheral`
- 三张并行清单：`low_value`、`industry_trend`、`momentum`
- 硬过滤 + 打分排序 + `triage` 分层（`keep/watch/drop`）
- 网络/限流诊断、过滤诊断、Markdown 运行报告
- Alpaca 与 SEC 本地缓存（降低重复请求）
- 可选历史回测（`run_backtest.py`）

## 2. 数据源

- Alpaca API：可交易资产、快照、日线
- SEC EDGAR：公司财报事实（companyfacts/submissions）
- ETF 持仓页面（watchlist 刷新脚本使用）

扫描主流程不依赖新闻打分。

## 3. 快速开始

### 3.1 初始化环境

```bash
cd <repo_root>
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

可选安装方式：

```bash
pip install -r requirements.txt
PYTHONPATH=src python run_scan.py --help
```

### 3.2 配置 `.env`

必填：

```dotenv
ALPACA_API_ENDPOINT=
ALPACA_API_KEY=
ALPACA_API_SECRET=
SEC_USER_AGENT=ai-value-scanner your_email@example.com
```

可选：

```dotenv
ALPACA_DATA_ENDPOINT=https://data.alpaca.markets
ALPACA_FEED=iex
```

### 3.3 刷新 watchlist（按需手工执行）

```bash
python scripts/refresh_ai_watchlist.py --config config.production.json --output data/ai_watchlist.csv
```

### 3.4 运行扫描

示例（限制扫描数量）：

```bash
python run_scan.py --config config.production.json --max-symbols 300
```

全量 watchlist：

```bash
python run_scan.py --config config.production.json
```

## 4. Watchlist 机制

### 4.1 运行时行为

- `run_scan.py` 只读取本地 `watchlist_csv_path`（默认 `data/ai_watchlist.csv`）
- 扫描前不会自动刷新 watchlist
- watchlist 缺失或为空时会直接报错并终止

### 4.2 CSV 字段规范

扫描端要求以下必填列：
- `symbol`
- `bucket`（`core_ai`/`ai_enabler`/`ai_peripheral`）
- `etf_count`
- `etfs`
- `enabled`

`updated_utc` 建议保留，但不是扫描必需列。

### 4.3 默认 ETF 三池（来自 `config.production.json`）

- `watchlist_core_etfs`：`AIQ,BOTZ,ROBT,WTAI,SOXX,SMH,IRBO,ARKQ,IGV,IGM,FDN,PNQI,SOXQ,XSD,KOMP`
- `watchlist_enabler_etfs`：`DTCR,IFRA,XLI,XLU,NLR,URA,SKYY,CLOU,SRVR,GRID,CIBR,IHAK,BUG,PAVE,IGF,IXP`
- `watchlist_peripheral_etfs`：`XLB,VIS,ITA,IYT,ITB,PICK,COPX,VPU,XLRE,VNQ,FXR,IGE`

## 5. 扫描逻辑

### 5.1 6 阶段流程

`run_scan.py` 运行时会输出 `[1/6]` 到 `[6/6]`：
1. 加载 watchlist + 可交易标的
2. 拉取行情并计算价格维度指标
3. 拉取 SEC 基本面（含缓存）
4. 计算估值/历史估值分位/质量指标
5. 合并 watchlist 属性，执行三通道筛选与打分
6. 写出 CSV/JSON/Markdown，并打印控制台简表

### 5.2 三张清单（并行）

- `Low-Value`：价值与质量因子主导，输出 `triage_label=keep/watch/drop`
- `Industry-Trend`：趋势相关约束与趋势权重打分，`triage_label=trend`
- `Momentum`：动量约束与动量权重打分，`triage_label=momentum`

三张清单是并行结果，不是子集关系。

### 5.3 AI 关联度评分

`ai_link_score`（0~1）由四部分组成：
- `ai_etf_consensus_score`（权重 0.40）
- `ai_disclosure_score`（权重 0.35）
- `ai_market_link_score`（权重 0.15）
- `ai_backlog_signal`（权重 0.10）

### 5.4 低估与质量口径（关键点）

- 估值：`ps`、`pe`、`ev_to_ebit`、`fcf_yield`
- 行业相对估值：`ps_percentile_in_sic`、`pe_percentile_in_sic`
- 个股历史估值分位：`ps_hist_percentile`、`pe_hist_percentile`
  - 基于“历史价格 + 历史 TTM 分母 + 历史股本”重建估值序列计算
  - 来源字段：`*_hist_percentile_source`、`*_hist_observation_count`
- 质量与稳健性：
  - 盈利/现金流（可切换 `use_adjusted_quality_metrics`、`use_ttm_metrics`）
  - 资产负债与现金化（如 `interest_coverage`、`net_debt_to_ebitda`、`ocf_to_net_income`）
  - 营运与稀释（如 `receivables_growth_gap`、`inventory_growth_gap`、`shares_yoy`）

## 6. 配置说明

默认扫描配置：`config.production.json`（`run_scan.py` 默认读取该文件）。

### 6.1 参数层级

- 全局参数：`ScanConfig` 顶层字段
- 通道参数：`channel_profiles.<channel>`（覆盖全局默认）

### 6.2 生产配置关键默认值

- `metric_hard_filter_coverage_mode = "balanced"`
- `force_hard_filter_low_coverage_metrics = false`
- `require_channel_bucket_match = true`
- `enforce_unique_symbol_per_list = false`
- `enforce_unique_symbol_across_lists = false`
- `own_history_valuation_window_days = 720`

说明：
- `top_n_per_channel_low_value/trend/momentum` 若未在配置显式设置，代码默认值为 `10/10/10`
- `exclude_sic_codes` 若未显式设置，代码默认值为 `["6770"]`

### 6.3 常用可调参数组

- Universe 与流动性：`min_price`、`min_dollar_volume`、`enabled_exchanges`
- 估值与折价：`min_ps_discount`、`min_pe_discount`、`max_ps_percentile_in_sic`、`max_pe_percentile_in_sic`
- 质量与现金流：`min_fundamental_quality_score`、`min_interest_coverage`、`min_ocf_to_net_income`
- 价格维度：`min_drawdown_from_52w_high`、`max_price_to_sma200`、`max_60d_volatility`
- AI 关联：`min_ai_link_score`、`ai_link_*`
- 输出与性能：`max_workers`、`chunk_size`、`alpaca_max_requests_per_sec`、`sec_max_requests_per_sec`

## 7. 运行参数

```bash
python run_scan.py --help
```

常用参数：
- `--config`：配置文件路径（默认 `config.production.json`）
- `--max-symbols`：样本上限（在 watchlist 内按快照成交额降序截取）
- `--output`：主结果 CSV 路径
- `--diagnostics-output`：过滤诊断输出基路径
- `--network-report-output`：网络诊断 JSON 路径
- `--report-output`：Markdown 详细报告路径

## 8. 输出文件

默认命名基准：
- `outputs/ai_value_scan_YYYYMMDDTHHMMSSZ_<scope>_ranked.csv`
- `<scope>` 为 `full` 或 `sample<max_symbols>`

基于主文件会生成：
- 主清单：`..._ranked.csv`
- 主清单分通道：`..._ranked_core_ai.csv`、`..._ranked_ai_enabler.csv`、`..._ranked_ai_peripheral.csv`
- 行业趋势：`..._ranked_industry_trend.csv` 及其分通道文件
- 动量清单：`..._ranked_momentum.csv` 及其分通道文件
- 过滤诊断（按通道）：`..._ranked_diagnostics_<channel>.csv`
- 首因诊断（按通道）：`..._ranked_diagnostics_<channel>_first_fail.csv`
- 网络诊断：`..._ranked_network.json`
- Markdown 报告：`..._ranked_report.md`

## 9. 运行日志与诊断

### 9.1 终端日志

扫描日志格式：`[HH:MM:SS][LEVEL][+elapsed] message`  
回测日志格式：`[scope HH:MM:SS +elapsed] message`

包含：
- 阶段进度（`[1/6]` ~ `[6/6]`）
- SEC 长阶段进度
- 输出文件路径
- 结束时三张清单按通道的入选股票汇总

### 9.2 网络诊断 JSON

按服务（`alpaca`、`sec`）统计：
- 请求量、状态码分布、重试、异常
- 限速等待次数/耗时
- 缓存命中（`cache_hits`/`cache_misses`）
- 汇总标记：`had_rate_limit_or_network_issue`

## 10. 缓存与限速

默认开启本地缓存（目录 `cache/`）：
- Alpaca：assets/snapshots/bars（TTL 可配置）
- SEC：ticker mapping、submissions、companyfacts

相关参数：
- `alpaca_cache_enabled`
- `alpaca_cache_ttl_assets_sec`
- `alpaca_cache_ttl_snapshots_sec`
- `alpaca_cache_ttl_bars_sec`
- `alpaca_max_requests_per_sec`
- `sec_max_requests_per_sec`

## 11. 回测（可选）

入口：

```bash
python run_backtest.py --mode historical_replay --scan-config config.production.json
```

常用参数：
- `--mode historical_replay|existing_runs`
- `--outputs-dir`
- `--list-types low_value,industry_trend,momentum`
- `--top-n`、`--per-channel-top-n`
- `--start-date`、`--end-date`、`--rebalance-frequency`
- `--replay-max-symbols`、`--replay-asset-status`
- `--entry-price-mode next_open|next_close`
- `--exit-price-mode close|open`
- `--watchlist-history-dir data/watchlist_history`
- `--allow-latest-watchlist-fallback`（默认关闭，避免无快照时引入前视）
- `--disclosure-lookback-days`
- `--enable-perturbation|--no-perturbation`
- `--theme-source rules_proxy|historical_news|latest_scan|zero`

默认输出（`outputs/backtest_<mode>_<UTC>_*`）：
- `*_signals.csv`
- `*_events.csv`
- `*_summary.csv`
- `*_benchmarks.csv`
- `*_segments.csv`
- `*_report.md`
- `*_report_network.json`

## 12. 说明与限制

- 本项目用于研究与筛选，不构成投资建议。
- 历史回测为工程近似，不等价于完整 PIT 学术数据库回测。
- ETF 持仓抓取依赖第三方页面结构，建议定期抽检 watchlist 刷新结果。
- 配置扩展建议遵循：
  1. 在 `ScanConfig` 增加字段
  2. 在 `resolve_channel_profile` 接入通道覆盖
  3. 在过滤步骤或打分逻辑中显式使用
  4. 同步更新本 README
