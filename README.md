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
python scripts/refresh_ai_watchlist.py --config configs/config.balanced.json --output data/ai_watchlist.csv
```

### 3.4 运行扫描

示例（限制扫描数量）：

```bash
python run_scan.py --config configs/config.balanced.json --max-symbols 300
```

全量 watchlist：

```bash
python run_scan.py --config configs/config.balanced.json
```

### 3.5 官方配置

当前维护三套正式配置：

- `configs/config.risk_off.json`：质量优先，样本更少，防守属性更强。
- `configs/config.balanced.json`：质量与覆盖率平衡，作为默认扫描配置。
- `configs/config.risk_on.json`：覆盖率优先，适合风险偏好较高阶段。

历史调参/实验配置已归档到 `configs/archive/`，不再作为日常运行入口。

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

### 4.3 默认 ETF 三池（来自 `configs/config.balanced.json`）

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

默认扫描配置：`configs/config.balanced.json`（`run_scan.py` 默认读取该文件）。

### 6.1 参数生效顺序与覆盖关系

1. `run_scan.py` CLI 参数先应用（例如 `--max-symbols` 会覆盖配置中的 `max_symbols`）。
2. 全局参数来自配置文件顶层（`ScanConfig` 顶层字段）。
3. 通道参数来自 `channel_profiles.<channel>`，会覆盖同名全局参数。
4. 未在配置中出现的字段，使用代码默认值（`ScanConfig` 默认值）。
5. 配置中的未知字段会被忽略（不会报错，也不会生效）。

### 6.2 全局参数与阈值（`configs/config.balanced.json`）

说明：下表用于说明参数作用与调节方向；精确默认值以对应配置文件内容为准（`config.risk_off.json` / `config.balanced.json` / `config.risk_on.json`）。

#### 6.2.1 运行、并发、缓存、限速

| 参数 | 默认值（balanced） | 作用 |
|---|---:|---|
| `max_symbols` | `null` | 扫描上限（`null` 表示扫描完整 watchlist）。 |
| `max_workers` | `8` | 并发线程数。 |
| `chunk_size` | `200` | 拉取数据的批处理大小。 |
| `request_timeout_sec` | `20` | HTTP 请求超时秒数。 |
| `alpaca_max_requests_per_sec` | `2.5` | Alpaca 限速上限。 |
| `sec_max_requests_per_sec` | `5.0` | SEC 限速上限。 |
| `alpaca_cache_enabled` | `true` | 是否启用 Alpaca 本地缓存。 |
| `alpaca_cache_ttl_assets_sec` | `21600` | `assets` 缓存 TTL（秒）。 |
| `alpaca_cache_ttl_snapshots_sec` | `120` | `snapshots` 缓存 TTL（秒）。 |
| `alpaca_cache_ttl_bars_sec` | `21600` | `bars` 缓存 TTL（秒）。 |
| `cache_dir` | `cache` | 缓存目录（默认值来自代码）。 |
| `output_dir` | `outputs` | 输出目录（默认值来自代码）。 |

#### 6.2.2 Watchlist 与 AI 关联评分

| 参数 | 默认值（balanced） | 作用 |
|---|---:|---|
| `watchlist_csv_path` | `data/ai_watchlist.csv` | 扫描输入 watchlist 路径。 |
| `watchlist_fetch_timeout_sec` | `20` | watchlist 刷新脚本网络超时。 |
| `watchlist_core_etfs` | 15 个 ETF | 生成 `core_ai` 池的 ETF 源。 |
| `watchlist_enabler_etfs` | 16 个 ETF | 生成 `ai_enabler` 池的 ETF 源。 |
| `watchlist_peripheral_etfs` | 12 个 ETF | 生成 `ai_peripheral` 池的 ETF 源。 |
| `ai_link_benchmark_etfs` | 8 个 ETF | 计算 `ai_market_link_score` 的基准篮子。 |
| `ai_link_etf_count_saturation` | `4` | ETF 计数映射到 `ai_etf_consensus_score` 的饱和值。 |
| `ai_link_disclosure_keyword_cap` | `6` | 披露关键词计分上限。 |
| `ai_link_market_return_tolerance_20d` | `0.25` | 20 日收益与基准偏离容忍度。 |
| `ai_link_market_return_tolerance_60d` | `0.4` | 60 日收益与基准偏离容忍度。 |
| `ai_link_backlog_ratio_cap` | `0.2` | backlog 信号归一化上限。 |

#### 6.2.3 Universe 与流动性门槛

| 参数 | 默认值（balanced） | 作用 |
|---|---:|---|
| `enabled_exchanges` | `NYSE,NASDAQ,AMEX,ARCA,BATS` | 交易所白名单。 |
| `min_price` | `1.0` | 最低股价。 |
| `min_market_cap` | `300000000` | 最低市值。 |
| `max_market_cap` | `null` | 最高市值（`null` 为不限制）。 |
| `min_dollar_volume` | `2000000` | 当日最低成交额。 |
| `min_avg_dollar_volume_20d` | `null` | 20 日平均成交额下限（可选）。 |

#### 6.2.4 财务口径与正值开关

| 参数 | 默认值（balanced） | 作用 |
|---|---:|---|
| `use_ttm_metrics` | `true` | 优先使用 TTM 指标。 |
| `use_adjusted_quality_metrics` | `true` | 质量与盈利相关指标使用“调整后”口径。 |
| `nonrecurring_addback_revenue_cap` | `0.25` | 非经常损益回补上限（占营收比例上限）。 |
| `require_positive_revenue` | `true` | 收入必须为正。 |
| `require_positive_net_income` | `false` | 净利润必须为正（当前关闭）。 |
| `require_positive_operating_cash_flow` | `true` | 经营现金流必须为正。 |
| `require_positive_free_cash_flow` | `false` | 自由现金流必须为正（当前关闭）。 |
| `require_positive_ebit` | `true` | EBIT 必须为正。 |

#### 6.2.5 价值、质量与风险硬过滤阈值

| 参数 | 默认值（balanced） | 作用 |
|---|---:|---|
| `min_fundamental_quality_score` | `0.56` | 质量综合分下限。 |
| `min_revenue` | `10000000` | 收入下限。 |
| `min_net_income` | `-20000000` | 净利润下限（允许小幅亏损）。 |
| `min_operating_cash_flow` | `0.0` | 经营现金流下限。 |
| `min_free_cash_flow` | `-100000000` | 自由现金流下限。 |
| `min_ebit` | `0.0` | EBIT 下限。 |
| `min_net_margin` | `null` | 净利率下限（可选）。 |
| `max_ps` / `max_pe` | `null` / `null` | 绝对 PS/PE 上限（可选）。 |
| `max_ev_to_ebit` | `38.0` | EV/EBIT 上限。 |
| `min_fcf_yield` | `0.005` | FCF Yield 下限。 |
| `min_ps_discount` | `0.15` | 相对行业 PS 折价下限。 |
| `min_pe_discount` | `0.10` | 相对行业 PE 折价下限。 |
| `max_ps_percentile_in_sic` | `0.6` | SIC 内 PS 分位上限。 |
| `max_pe_percentile_in_sic` | `0.6` | SIC 内 PE 分位上限。 |
| `own_history_valuation_window_days` | `720` | 历史估值分位回看窗口（天）。 |
| `max_ps_hist_percentile` | `0.7` | 个股历史 PS 分位上限。 |
| `max_pe_hist_percentile` | `0.7` | 个股历史 PE 分位上限。 |
| `min_revenue_yoy` | `-0.1` | 营收同比下限。 |
| `min_net_income_yoy` | `-0.25` | 净利润同比下限。 |
| `max_net_debt_to_ebitda` | `4.0` | 杠杆上限。 |
| `min_interest_coverage` | `2.0` | 利息覆盖倍数下限。 |
| `max_current_debt_ratio` | `0.75` | 流动负债占流动资产比上限。 |
| `min_current_ratio` | `1.0` | 流动比率下限。 |
| `min_ocf_to_net_income` | `0.7` | 现金利润匹配度下限。 |
| `max_accrual_ratio` | `0.3` | 应计比率上限。 |
| `max_receivables_growth_gap` | `0.55` | 应收增速相对营收增速的偏离上限。 |
| `max_inventory_growth_gap` | `0.9` | 存货增速相对营收增速的偏离上限。 |
| `max_shares_yoy` | `0.08` | 股本同比稀释上限。 |
| `min_expectation_proxy` | `-0.2` | 预期代理指标下限。 |
| `min_cycle_proxy` | `null` | 周期代理指标下限（可选）。 |

#### 6.2.6 价格行为与波动阈值

| 参数 | 默认值（balanced） | 作用 |
|---|---:|---|
| `price_lookback_days` | `420` | 价格特征计算回看天数。 |
| `min_drawdown_from_52w_high` | `null` | 52 周高点回撤下限。 |
| `max_range_position_52w` | `null` | 52 周区间位置上限。 |
| `max_price_to_sma200` | `null` | 价格/SMA200 上限。 |
| `min_days_below_sma200` | `5` | 连续低于 SMA200 的最少天数。 |
| `min_return_20d` / `min_return_60d` | `null` / `null` | 20/60 日收益下限。 |
| `max_20d_return` | `0.18` | 20 日收益上限（防短期过热）。 |
| `max_60d_volatility` | `0.85` | 60 日波动率上限。 |
| `min_drawdown_percentile` | `null` | 回撤分位下限（横截面）。 |
| `min_avg_dollar_volume_20d_percentile` | `null` | 流动性分位下限（横截面）。 |
| `max_60d_volatility_percentile` | `null` | 波动率分位上限（横截面）。 |

#### 6.2.7 可交易性、分散化、评分稳健性

| 参数 | 默认值（balanced） | 作用 |
|---|---:|---|
| `assumed_position_usd` | `250000` | 估算冲击成本的单票仓位。 |
| `max_adv_participation` | `0.05` | 交易参与度（仓位/ADV）上限。 |
| `max_estimated_slippage_bps` | `45.0` | 估算滑点上限。 |
| `max_per_sector_per_list` | `3` | 单行业在单清单中的上限。 |
| `max_per_watchlist_etf_source_per_list` | `null` | 单 ETF 来源上限（可选）。 |
| `score_winsor_lower_q` | `0.05` | 打分 winsor 下分位。 |
| `score_winsor_upper_q` | `0.95` | 打分 winsor 上分位。 |
| `score_penalty_overvaluation` | `0.2` | 高估惩罚系数。 |
| `score_penalty_deterioration` | `0.2` | 基本面恶化惩罚系数。 |

#### 6.2.8 覆盖率模式、去重与输出数量

| 参数 | 默认值（balanced） | 作用 |
|---|---:|---|
| `metric_hard_filter_coverage_mode` | `balanced` | 硬过滤覆盖率模式：`high_coverage_only` / `balanced` / `all_metrics`。 |
| `force_hard_filter_low_coverage_metrics` | `false` | 是否将低覆盖指标强制纳入硬过滤。 |
| `low_coverage_soft_score_weights` | `{current_debt_ratio_low:0.03, inventory_growth_gap_low:0.03}` | 低覆盖指标默认作为软约束时的加权。 |
| `require_channel_bucket_match` | `true` | 是否要求符号与通道 bucket 匹配。 |
| `enforce_unique_symbol_per_list` | `false` | 单清单跨通道是否去重。 |
| `enforce_unique_symbol_across_lists` | `false` | 三清单之间是否去重。 |
| `exclude_sic_codes` | `["6770"]` | 按 SIC 代码排除。 |
| `top_n_per_channel_low_value` | `10` | `low_value` 每通道输出上限。 |
| `top_n_per_channel_trend` | `10` | `industry_trend` 每通道输出上限。 |
| `top_n_per_channel_momentum` | `10` | `momentum` 每通道输出上限。 |

#### 6.2.9 `triage_rules` 分层规则

`triage_rules` 仅作用于 `low_value` 清单，结构如下：
- `keep.<channel>.min_composite_score`
- `keep.<channel>.min_ps_discount`
- `keep.<channel>.min_pe_discount`
- `drop.max_composite_score`
- `drop.require_both_value_premium`

作用：在通过硬过滤后，将 `low_value` 进一步标记为 `keep/watch/drop`，用于人工复核优先级。

### 6.3 通道参数（`channel_profiles.<channel>`）

每个通道（`core_ai`、`ai_enabler`、`ai_peripheral`）都可覆盖以下参数：

- 与全局同名的门槛：`min_ai_link_score`、`min_ps_discount`、`min_pe_discount`、`max_ps_percentile_in_sic`、`max_pe_percentile_in_sic`、`max_ev_to_ebit`、`min_fcf_yield`、`min_revenue_yoy`、`min_net_income_yoy`、`min_fundamental_quality_score`、`min_net_margin`、`min_avg_dollar_volume_20d`、`min_drawdown_from_52w_high`、`max_range_position_52w`、`max_price_to_sma200`、`min_days_below_sma200`、`min_return_20d`、`min_return_60d`、`max_20d_return`、`max_60d_volatility`、`min_drawdown_percentile`、`min_avg_dollar_volume_20d_percentile`、`max_60d_volatility_percentile`。
- 专业质量过滤：`max_net_debt_to_ebitda`、`min_interest_coverage`、`max_current_debt_ratio`、`min_current_ratio`、`min_ocf_to_net_income`、`max_accrual_ratio`、`max_receivables_growth_gap`、`max_inventory_growth_gap`、`max_shares_yoy`、`max_ps_hist_percentile`、`max_pe_hist_percentile`、`min_expectation_proxy`、`min_cycle_proxy`、`max_adv_participation`、`max_estimated_slippage_bps`。
- 低覆盖指标硬过滤开关：`hard_filter_current_debt_ratio`、`hard_filter_inventory_growth_gap`。
- 通道约束：`require_channel_bucket_match`、`min_watchlist_etf_count`。
- 打分权重：`score_weights`（`low_value` 使用）。

`industry_trend` 额外支持：
- `trend_min_watchlist_etf_count`
- `trend_min_return_60d`
- `trend_max_60d_volatility`
- `trend_min_avg_dollar_volume_20d`
- `trend_score_weights`

`momentum` 额外支持：
- `momentum_min_return_20d`
- `momentum_min_return_60d`
- `momentum_min_price_to_sma200`
- `momentum_max_drawdown_from_52w_high`
- `momentum_max_60d_volatility`
- `momentum_min_avg_dollar_volume_20d`
- `momentum_min_watchlist_etf_count`
- `momentum_score_weights`

### 6.4 阈值调节方向（如何改参数）

- 提高 `min_*`：更严格，入选数量通常减少。
- 降低 `min_*`：更宽松，入选数量通常增加。
- 降低 `max_*`：更严格，入选数量通常减少。
- 提高 `max_*`：更宽松，入选数量通常增加。
- 对 `_percentile` 参数：越接近 `0` 越严格（要求越便宜/更低波动分位）。
- 参数设为 `null`：关闭该条硬过滤。
- `metric_hard_filter_coverage_mode` 从 `high_coverage_only -> balanced -> all_metrics`：硬过滤覆盖指标逐步增加、淘汰会更严格。

### 6.5 配置示例（按通道覆盖）

```json
{
  "min_market_cap": 500000000.0,
  "max_ev_to_ebit": 35.0,
  "channel_profiles": {
    "core_ai": {
      "min_ai_link_score": 0.45,
      "max_ps_hist_percentile": 0.65,
      "trend_min_return_60d": -0.03
    },
    "ai_enabler": {
      "min_ai_link_score": 0.33,
      "min_ps_discount": 0.03,
      "momentum_min_return_20d": 0.035
    }
  }
}
```

上例中，`core_ai.max_ev_to_ebit` 若未显式指定，将继承全局 `max_ev_to_ebit=35.0`。

## 7. 运行参数

```bash
python run_scan.py --help
```

常用参数：
- `--config`：配置文件路径（默认 `configs/config.balanced.json`）
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
python run_backtest.py --mode historical_replay --scan-config configs/config.balanced.json
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
