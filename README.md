# AI Undervalued US Stocks Scanner (Alpaca + SEC)

基于 Alpaca 行情/交易元数据与 SEC EDGAR 基本面数据，对美股 `AI 观察清单`执行多通道筛选。项目的核心生产策略是 `Low-Value`：在 AI 相关观察池中寻找估值处于低位、质量可接受、且没有明显价值陷阱特征的股票。

**架构**（2026-09-24 起）：双风格并行——`risk_off`（低吸防守 + QQQ SMA200 深熊熔断）与
`risk_on`（双动量进攻），两套配置独立扫描、独立观察，不合并权重。每周用
`observation_scan.py` 同时跑两个风格。

程序同时输出辅助清单：
- `Low-Value`：核心清单，估值与质量优先。
- `Industry-Trend`：辅助观察清单，用于识别产业趋势和主题联动，不作为生产参数通过/失败的主目标。
- `Momentum`：辅助观察清单，用于识别价格动量，不作为生产参数通过/失败的主目标。
- `Research Pool`：宽口径研究池，用于人工扩展研究，不作为自动投资结论。

项目默认只扫描本地 watchlist 中的股票，不执行全市场无约束遍历。

定位说明：本项目是保守型 Low-Value 研究筛选器。它优先减少明显高估、现金流较弱、基本面恶化或主题关联不足的候选，而不是追求输出数量。正常市场环境下，`Low-Value` 清单可能只有少量股票，甚至为空；`Industry-Trend`、`Momentum` 和 `Research Pool` 用于辅助研究，不代表自动买入候选。

**实盘试点**：见 §15 与 `docs/live_pilot_protocol.md`——分层权重（keep/watch/drop +
momentum 五层）的实盘语义与 2021-2026 实证依据。

## 1. 核心能力

- Watchlist-only 扫描（候选池可控，执行速度稳定）
- 三池并行通道：`core_ai`、`ai_enabler`、`ai_peripheral`
- 三张并行清单：`low_value`、`industry_trend`、`momentum`
- 宽口径研究池：`research_pool`，用于人工扩展研究
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
python scripts/refresh_ai_watchlist.py --config configs/config.risk_off.json --output data/ai_watchlist.csv
```

### 3.4 运行扫描

示例（限制扫描数量）：

```bash
python run_scan.py --config configs/config.risk_off.json --max-symbols 300
```

全量 watchlist：

```bash
python run_scan.py --config configs/config.risk_off.json
```

### 3.5 官方配置

自 2026-09-24 起采用**两风格架构**（原 balanced 与 risk_off 收益相关性 0.999，已归档）：

- `configs/config.risk_off.json`（默认配置，防守腿）：低吸回调 + 质量 + QQQ 深度熊市熔断（SMA200 破线熄火）。
- `configs/config.risk_on.json`（进攻腿）：双动量结构——QQQ 绝对动量开关 + momentum 清单相对选择（`momentum_min_return_60d=0.10`）。
- 观察期协议见 `docs/two_style_observation_protocol.md`：`python scripts/observation_scan.py` 同时输出两风格，不做权重与轮动。

两风格各自的验证证据与历史沿革见 `docs/style_evolution_history.md`（Phase 0-4 完整记录）。

另有一套候选生产配置：

- `configs/config.strict_candidate.json`：基于 strict-list 调参复核得到的候选参数，聚焦 `low_value`、`industry_trend`、`momentum` 三张并行扫描清单，不作为默认配置自动使用。

历史调参/实验配置已归档到 `configs/archive/`，不再作为日常运行入口。

当前维护两套调参空间：

- `configs/tuner.param_space.json`：通用参数搜索空间。
- `configs/tuner.param_space.3layer.json`：三层过滤专用参数搜索空间。

调参空间同时覆盖并行清单阈值与研究池参数，例如 `research_pool_min_score`。`research_pool_top_n` 会影响扫描输出规模；在历史回放中，回测层还会受 `--top-n` 约束。

### 3.6 定期调参（anchored OOS walk-forward）

入口：

```bash
python scripts/tune_parameters.py \
  --base-config configs/config.risk_off.json \
  --param-space configs/tuner.param_space.json \
  --search-mode auto \
  --max-candidates 36
```

默认行为：
- 默认按“过去 3 个完整自然年 + 当年 YTD”做分段回测（可用 `--windows` 覆盖）。
- 默认 `--selection-mode walk_forward`，按 anchored folds 做真正的时间隔离。例如 2026 年运行时：
  - 2023 选参 → 2024 held-out；
  - 2023+2024 选参 → 2025 held-out；
  - 2023+2024+2025 选参 → 2026 YTD held-out。
- 训练窗口中的 20/60/120d 前向标签会记录 `label_end_date`；凡标签终点跨入下一 held-out 窗口的事件都会从训练评分中 purge，避免仅按 `signal_date` 切年造成边界泄漏。
- `--selection-mode pooled` 仅保留作研究诊断；它会让所有窗口共同参与排序，因此禁止与 `--promote` 联用。
- 默认评估 `low_value`、`industry_trend`、`momentum`、`research_pool`，默认以 `low_value` 作为 `--primary-list-types`。
- 调参结果同时输出并行清单分层指标（`strict_*`）和研究池分层指标（`research_pool_*`）。
- 多目标打分包含收益、相对 QQQ 超额、胜率、波动/非重叠事件回撤诊断、覆盖率约束。这里的 drawdown 是抽样诊断，不是账户净值回撤。
- **默认只评估，不覆盖任何生产配置**。
- 只有显式传 `--promote` 才会写配置，而且一次 tuning run 只能写回其 `--base-config` 所属 style；最终候选必须由最后一个 held-out 窗口之前的数据选出，并通过该 held-out 窗口验证。

若只评估三张并行扫描清单，可通过 `--list-types low_value,industry_trend,momentum` 排除 `research_pool`。若要改变生产评价目标，可显式设置 `--primary-list-types`。

## 4. Watchlist 机制

### 4.1 运行时行为

- `run_scan.py` 只读取本地 `watchlist_csv_path`（默认 `data/ai_watchlist.csv`）
- 扫描前不会自动刷新 watchlist
- watchlist 缺失或为空时会直接报错并终止
- **ETF 只用于构建当前选股底单/watchlist，不是历史回测的数据依赖。** 不追踪、不重建历史 ETF 成分；walk-forward 的时间隔离针对参数选择和前向收益标签，不改变这一 universe 原则。

### 4.2 CSV 字段规范

扫描端要求以下必填列：
- `symbol`
- `bucket`（`core_ai`/`ai_enabler`/`ai_peripheral`/`ai_smallcap`）
- `etf_count`
- `etfs`
- `enabled`

`updated_utc` 建议保留，但不是扫描必需列。

### 4.4 小盘研究层（`ai_smallcap` bucket）

ETF 持仓页内嵌数据实际只含前 ~25 大持仓，因此 ETF 并集天然漏掉未被重仓的小盘热门股（如 AMKR）。`ai_smallcap` 层用于补足这部分候选，主要流向 `research_pool`（宽口径研究池），也可进入三张清单（有独立的通道阈值与 triage 规则）。该通道为**辅线观察层**：扫描与研究池保留，但默认不进入交易计划候选（`--include-smallcap` 可恢复）。

构建入口（三源合并，已在 ETF 名单中的标的会被跳过，`SRC:` 前缀为来源标记，不计入 `etf_count`）：

```bash
python scripts/build_smallcap_universe.py --config configs/config.risk_off.json
```

- `nasdaq`：Nasdaq Screener 全宇宙过滤（Technology 板块 AI 相关行业，或任意板块的 AI 电力行业 `Electric Utilities: Central`/`Power Generation`/`Electrical Products`；市值 `--market-cap-min/max` 默认 3 亿–800 亿 + 日成交量下限；公司注册地限美国及半导体盟友（爱尔兰/英国/台湾/荷兰/瑞士/德国/日韩/新加坡/以色列，中国除外），名称须过普通股过滤以剔除优先股/票据/权证），约数百只。
- `yahoo`：Yahoo `most_actives/day_gainers/day_losers` 热门榜，但**只保留同时通过 Nasdaq 行业筛的标的**（Yahoo 热榜无行业字段，不过滤会混入零售/meme 等非 AI 热门股）。
- `manual`：`data/ai_smallcap_manual.csv` 手工清单（`symbol,note` 两列），零依赖、可版本控制。

常用参数：`--sources nasdaq,yahoo,manual`、`--max-symbols 400`（默认上限）、`--offline`（仅用手工清单）、`--dry-run`（只打印不写盘）。每次执行会先清空旧 `ai_smallcap` 行再重建（幂等）；运行顺序建议：先 `refresh_ai_watchlist.py`，再本脚本，最后 `run_scan.py`。

### 4.3 默认 ETF 三池（来自 `configs/config.risk_off.json`，三配置共享该清单）

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

生产使用口径：
- `Low-Value` 是核心生产清单，适合优先人工复核。
- `Industry-Trend` 用于观察产业趋势和主题联动，可能包含估值已经偏高的强势股。
- `Momentum` 用于观察价格动量，可能包含并不低估的股票。
- `Research Pool` 是宽口径研究扩展池，会保留 `theme_only` 等候选，不能作为自动投资结论。
- 当 `Low-Value` 入选数量很少时，通常表示当前参数下没有足够多股票同时满足估值、质量、价格行为和主题关联要求，不应简单理解为程序异常。

### 5.3 AI 关联度评分

`ai_link_score`（0~1）由四部分组成：
- `ai_etf_consensus_score`（权重 0.40）：`min(持有该股的主题 ETF 数 / 4, 1)`——机构共识度
- `ai_disclosure_score`（权重 0.35）：SEC submissions 文本（公司描述 + 最近 20 个申报的
  表格/描述/items）命中 5 组关键词（ai_compute / data_center / semiconductor /
  **power_grid（含 nuclear——电力/核能副主题由此得分）** / commercial_signal）的
  覆盖度与密度：`0.7 × 组覆盖率 + 0.3 × 词密度`
- `ai_market_link_score`（权重 0.15）：与 8 只基准 ETF（AIQ/BOTZ/SMH/SOXX/XLK/
  XLI/XLU/PAVE——刻意混合半导体/工业/公用/基建）收益中位数的**对称跟随度**：
  `1 − |个股收益 − 基准收益| / 容忍度`（20d 容忍 0.25、60d 容忍 0.40，权重 0.4/0.6）
- `ai_backlog_signal`（权重 0.10）：`min(最新季度 backlog / TTM 营收 / 0.2, 1)`

**market_link 的对称语义是设计意图而非缺陷**（2026-09-28 审计确认）：
引入于 `312a657`（2026-05-29，"联动强度"），此后未改动。它测的是"与 AI 复合体的
**相关性**"——方向归动量维度管（return_20d/60d 门槛与权重），深熊保护归 QQQ 熔断管
（2022 全年空仓已实证）。**分 regime 实证（2021-2026）**：market_link 的 IC 在
下跌市为 +0.04~+0.01（不显著为负）、全期 120d +0.046~+0.069（t=2.5~3.1）——
"奖励跟随下跌"未造成实际伤害；composite ai_link_score 在下跌市 IC +0.10~+0.13
（t=4.5~7.1）依然强正。**多主题引擎（docs/multi_theme_expansion.md）继承此对称语义。**

组件级 IC（v2 数据集，2021-2026）：etf_consensus 最强（120d +0.13~+0.15，t=11~13）；
backlog 弱正；**disclosure_score 60d IC ≈ -0.02（t=-1.85）**——申报文本里堆砌 AI 关键词
（"AI washing"）的公司轻微跑输。此观察仅记录，不据此改权重（权重扫描的教训：样本内
IC 改进未能在组合级样本外存活），观察期持续跟踪。

### 5.4 低估与质量口径（关键点）

- 估值：`ps`、`pe`、`ev_to_ebit`、`fcf_yield`
- 行业相对估值：`ps_percentile_in_sic`、`pe_percentile_in_sic`
- 个股历史估值分位：`ps_hist_percentile`、`pe_hist_percentile`
  - 基于"历史价格 + 历史 TTM 分母 + 历史股本"重建估值序列计算
  - 来源字段：`*_hist_percentile_source`、`*_hist_observation_count`
- 质量与稳健性：
  - 盈利/现金流（可切换 `use_adjusted_quality_metrics`、`use_ttm_metrics`）
  - 资产负债与现金化（如 `interest_coverage`、`net_debt_to_ebitda`、`ocf_to_net_income`）
  - 营运与稀释（如 `receivables_growth_gap`、`inventory_growth_gap`、`shares_yoy`）

### 5.5 指标清单与验证状态（2026-09-27）

全部指标的验证覆盖矩阵见 `outputs/metrics_coverage_matrix.md`。按计算路径分五类：

| 类别 | 指标 | 验证方式与结果 |
|---|---|---|
| SEC 流量（TTM 重建） | revenue、net_income、adjusted_net_income、operating_cash_flow、free_cash_flow、ebit、adjusted_ebit、interest_expense、depreciation_and_amortization、capex | 7 家族全总体不变量（680 公司）：I2（推导 vs 申报方自报离散值）**零不匹配**；运作窗口年度闭合违反率 0.19%（7 条，逐条归因为申报方自身数据现实）。覆盖率 65.7%~88.8%，其余公司按设计回退年报值（名单见 `ttm_population_validation_*_coverage.csv`） |
| SEC 存量（资产负债表） | shares_outstanding、total_debt、cash、receivables、inventory、current_assets/liabilities、net_debt | 总体自洽：market_cap=shares×price 中位比率 1.000 零偏离；net_debt=total_debt−cash 零偏差；股本另有专门修复（dei 合并/单位检测/陈旧置空） |
| 衍生比率 | net_margin、current_ratio、ocf_to_net_income、interest_coverage、net_debt_to_ebitda、ps/pe、fcf_yield、accrual_ratio、current_debt_ratio、SIC/历史分位 ×4、adv_participation、slippage、YoY ×5、growth_gap ×2 | 边界检查 + 越界抽样复算：越界行全部复算一致（合法极值公司，如疫情年 LUV OCF/NI=739） |
| 价格特征（Alpaca） | price、dollar_volume、return_20d/60d、volatility_60d、avg_dollar_volume_20d、drawdown_from_52w_high、range_position_52w、price_to_sma200、days_below_sma200 | 跨源逐位一致（26,116 对前向收益两次独立提取）、bars 完整性核查通过 |
| AI/主题启发式 | ai_link_score（=ETF 共识 0.40 + 披露 0.35 + 市场联动 0.15 + backlog 0.10）、watchlist_etf_count、expectation_proxy、cycle_proxy、fundamental_quality_score | 无会计恒等式；经验验证有最强排名力（IC t=5.7~6.0）。"有用性"已验证，无"记账对错"概念 |

### 5.6 两层 scored 过滤架构（2026-09-24 起，全部清单生效）

`filter_mode=scored`（默认）下，每张清单的过滤步骤分为两层：

- **硬门**：核心可交易性（价格/成交额/市值/watchlist/通道/SIC）+ 风格结构门槛
  （risk_off 的回撤/区间位置/价格相对 SMA200；risk_on 的站上 SMA200/正动量；
  QQQ SMA200 熔断对所有清单生效）——未过即出局。
- **软评分**：其余全部阈值（估值/质量/动量细项）不再直接淘汰，改为对幸存者
  逐项判定通过/不通过，以 `soft_pass_rate` 计入 `composite_score`（权重见
  各通道 `score_weights.soft_pass_rate`）。

三张清单（low_value / industry_trend / momentum）与回测引擎使用同一
`partition_filter_steps` 分层（`apply_scored_or_hard_filters`），生产与回测口径一致。

`composite_score` = Σ(维度权重 × 横截面归一化分) + soft_pass_rate × 权重
− 0.2 × 高估惩罚 − 0.2 × 恶化惩罚。维度权重见各通道 `score_weights` /
`momentum_score_weights`（配置文件为权威值）。

## 6. 配置说明

默认扫描配置：`configs/config.risk_off.json`（`run_scan.py` 默认读取该文件；balanced 已归档）。

### 6.1 参数生效顺序与覆盖关系

1. `run_scan.py` CLI 参数先应用（例如 `--max-symbols` 会覆盖配置中的 `max_symbols`）。
2. 全局参数来自配置文件顶层（`ScanConfig` 顶层字段）。
3. 通道参数来自 `channel_profiles.<channel>`，会覆盖同名全局参数。
4. 未在配置中出现的字段，使用代码默认值（`ScanConfig` 默认值）。
5. 配置采用 fail-fast 校验：未知字段、错误类型、非法范围或交叉约束会在启动时直接报错；仅 `_theme_meta` / `_venture_meta` 等以下划线开头的文档元数据不会进入运行时配置。
6. `config.risk_on.json` / `config.risk_off.json` 通过顶层 `strategy_style` 显式声明风格身份；扫描报告写入 `Strategy-Style:`，下游优先读取该字段，不再依赖文件名推断。

### 6.2 全局参数与阈值（以 `configs/config.risk_off.json` 为基准参考）

说明：下表用于说明参数作用与调节方向；精确默认值以对应配置文件内容为准（`config.risk_off.json` / `config.risk_on.json` / `config.strict_candidate.json`；balanced 已归档）。

#### 6.2.1 运行、并发、缓存、限速

| 参数 | 默认值（risk_off） | 作用 |
|---|---:|---|
| `config_schema_version` | `1` | 配置契约版本；缺省按 v1 兼容读取，显式出现未知版本会 fail-fast。 |
| `strategy_style` | `risk_off` | 生产双风格显式身份（risk_on/risk_off）；主题、venture、校准配置可为 `null`。 |
| `max_symbols` | `null` | 扫描上限（`null` 表示扫描完整 watchlist）。 |
| `max_workers` | `8` | 并发线程数。 |
| `chunk_size` | `200` | 拉取数据的批处理大小。 |
| `request_timeout_sec` | `20` | HTTP 请求超时秒数。 |
| `alpaca_max_requests_per_sec` | `2.5` | Alpaca 限速上限。 |
| `sec_max_requests_per_sec` | `5.0` | SEC 限速上限。 |
| `alpaca_cache_enabled` | `true` | 是否启用 Alpaca 本地缓存。 |
| `alpaca_cache_ttl_assets_sec` | `21600` | `assets` 缓存 TTL（秒）。 |
| `alpaca_cache_ttl_snapshots_sec` | `120` | `snapshots` 缓存 TTL（秒）。 |
| `alpaca_cache_ttl_bars_sec` | `21600` | `bars` 缓存 TTL（秒）。网络失败使用过期缓存时不会刷新原文件 mtime；network JSON/Markdown 会记录 source、feed、市场数据 `data_asof`、最大 cache age、降级原因和 stale-fallback 标记。 |
| `cache_dir` | `cache` | 缓存目录（默认值来自代码）。 |
| `output_dir` | `outputs` | 输出目录（默认值来自代码）。 |

#### 6.2.2 Watchlist 与 AI 关联评分

| 参数 | 默认值（risk_off） | 作用 |
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

| 参数 | 默认值（risk_off） | 作用 |
|---|---:|---|
| `enabled_exchanges` | `NYSE,NASDAQ,AMEX,ARCA,BATS` | 交易所白名单。 |
| `min_price` | `1.0` | 最低股价。 |
| `min_market_cap` | `300000000` | 最低市值。 |
| `max_market_cap` | `null` | 最高市值（`null` 为不限制）。 |
| `min_dollar_volume` | `2000000` | 当日最低成交额。 |
| `min_avg_dollar_volume_20d` | `null` | 20 日平均成交额下限（可选）。 |

#### 6.2.4 财务口径与正值开关

| 参数 | 默认值（risk_off） | 作用 |
|---|---:|---|
| `use_ttm_metrics` | `true` | 优先使用 TTM 指标。 |
| `use_adjusted_quality_metrics` | `true` | 质量与盈利相关指标使用“调整后”口径。 |
| `nonrecurring_addback_revenue_cap` | `0.25` | 非经常损益回补上限（占营收比例上限）。 |
| `require_positive_revenue` | `true` | 收入必须为正。 |
| `require_positive_net_income` | `true` | 净利润必须为正。 |
| `require_positive_operating_cash_flow` | `true` | 经营现金流必须为正。 |
| `require_positive_free_cash_flow` | `true` | 自由现金流必须为正。 |
| `require_positive_ebit` | `true` | EBIT 必须为正。 |

#### 6.2.5 价值、质量与风险硬过滤阈值

下表为**全局值**（risk_off 基准）；通道可覆盖同名阈值（如 risk_off 的 `core_ai`
覆盖 `min_ps_discount=0.05`、`min_drawdown_from_52w_high=0.05`、`max_range_position_52w=0.82`、
`max_price_to_sma200=1.12` 等，精确值以配置文件为准）。scored 模式下除核心硬门与风格
结构门外，这些阈值作为软维度判定（通过/不通过计入 soft_pass_rate）。

| 参数 | 全局值（risk_off） | 作用 |
|---|---:|---|
| `min_fundamental_quality_score` | `0.64` | 质量综合分下限。 |
| `min_revenue` | `10000000` | 收入下限。 |
| `min_net_income` | `10000000` | 净利润下限。 |
| `min_operating_cash_flow` | `0.0` | 经营现金流下限。 |
| `min_free_cash_flow` | `20000000` | 自由现金流下限。 |
| `min_ebit` | `0.0` | EBIT 下限。 |
| `min_net_margin` | `null` | 净利率下限（可选；core_ai 覆盖为 0.05）。 |
| `max_ps` / `max_pe` | `null` / `null` | 绝对 PS/PE 上限（可选）。 |
| `max_ev_to_ebit` | `32.0` | EV/EBIT 上限。 |
| `min_fcf_yield` | `0.005` | FCF Yield 下限。 |
| `min_ps_discount` | 全局无；core_ai `0.05`、ai_enabler `0.05`、ai_peripheral `0.01`、ai_smallcap `0.02` | 相对行业 PS 折价下限。 |
| `min_pe_discount` | 全局无；core_ai `0.02`、ai_enabler `0.02`、ai_peripheral `-0.05` | 相对行业 PE 折价下限。 |
| `max_ps_percentile_in_sic` | `0.6` | SIC 内 PS 分位上限。 |
| `max_pe_percentile_in_sic` | `0.6` | SIC 内 PE 分位上限。 |
| `own_history_valuation_window_days` | `720` | 历史估值分位回看窗口（天）。 |
| `max_ps_hist_percentile` | `0.6` | 个股历史 PS 分位上限。 |
| `max_pe_hist_percentile` | `0.6` | 个股历史 PE 分位上限。 |
| `min_revenue_yoy` | `-0.1` | 营收同比下限。 |
| `min_net_income_yoy` | `-0.25` | 净利润同比下限。 |
| `max_net_debt_to_ebitda` | `2.2` | 杠杆上限。 |
| `min_interest_coverage` | `4.5` | 利息覆盖倍数下限。 |
| `max_current_debt_ratio` | `0.75` | 流动负债占流动资产比上限。 |
| `min_current_ratio` | `1.0` | 流动比率下限。 |
| `min_ocf_to_net_income` | `0.7` | 现金利润匹配度下限。 |
| `max_accrual_ratio` | `0.22` | 应计比率上限。 |
| `max_receivables_growth_gap` | `0.4` | 应收增速相对营收增速的偏离上限。 |
| `max_inventory_growth_gap` | `0.65` | 存货增速相对营收增速的偏离上限。 |
| `max_shares_yoy` | `0.05` | 股本同比稀释上限。 |
| `min_expectation_proxy` | `-0.2` | 预期代理指标下限。 |
| `min_cycle_proxy` | `null` | 周期代理指标下限（可选）。 |

#### 6.2.6 价格行为与波动阈值

| 参数 | 全局值（risk_off） | 作用 |
|---|---:|---|
| `price_lookback_days` | `420` | 价格特征计算回看天数。 |
| `min_drawdown_from_52w_high` | 全局无；core_ai `0.05`、ai_smallcap `0.05`（风格结构硬门） | 52 周高点回撤下限。 |
| `max_range_position_52w` | 全局无；core_ai `0.82`、ai_peripheral `0.95`（风格结构硬门） | 52 周区间位置上限。 |
| `max_price_to_sma200` | 全局无；core_ai `1.12`、ai_enabler `1.15`（风格结构硬门） | 价格/SMA200 上限。 |
| `min_days_below_sma200` | `5`（core_ai 等 `0`） | 连续低于 SMA200 的最少天数。 |
| `min_return_20d` / `min_return_60d` | `null` / `null`（core_ai `-0.1`/`-0.12`） | 20/60 日收益下限。 |
| `max_20d_return` | `0.12` | 20 日收益上限（防短期过热）。 |
| `max_60d_volatility` | `0.75`（core_ai `0.68`） | 60 日波动率上限。 |
| `min_drawdown_percentile` | 全局无；core_ai `0.2` | 回撤分位下限（横截面）。 |
| `min_avg_dollar_volume_20d_percentile` | 全局无；core_ai `0.2` | 流动性分位下限（横截面）。 |
| `max_60d_volatility_percentile` | 全局无；core_ai `0.8` | 波动率分位上限（横截面）。 |
| `benchmark_trend_filter_symbol` / `_sma_days` | `QQQ` / `200` | **主熔断**：QQQ 低于 SMA200 时全部清单无信号（2022 实证全年空仓）。 |

#### 6.2.7 可交易性、分散化、评分稳健性

| 参数 | 默认值（risk_off） | 作用 |
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
| `pe_cash_backing_haircut` | `1.0` | PE 系便宜信用按 OCF/NI 现金支撑度修剪的强度（0~1）。归一化后仅收缩中位以上（便宜侧）的 `pe_discount` / `pe_percentile_low` / `pe_hist_percentile_low` 信号：净利率被非经营收益（如投资浮盈）虚高 → OCF/NI 低 → PE 显得虚假便宜，其分数贡献按 `1 - 强度×(1-OCF/NI)` 折扣（OCF/NI 钳制在 0~1，缺失按 1 处理）。贵侧与缺失数据完全不受影响；`0` 恢复旧行为。 |

#### 6.2.8 覆盖率模式、去重与输出数量

| 参数 | 默认值（risk_off） | 作用 |
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
| `research_pool_top_n` | `50` | 宽口径研究候选池输出上限。 |
| `research_pool_min_score` | `2.0` | 宽口径研究候选池最低研究评分。 |
| `low_value_allowed_research_priorities` | `["research_now","watch_for_pullback"]` | `low_value` 主清单允许的研究优先级。 |
| `low_value_excluded_research_risks` | `["possible_value_trap","weak_ai_link","negative_momentum"]` | `low_value` 主清单排除的研究风险标签。 |
| `low_value_min_research_score` | `0.0` | `low_value` 主清单最低研究评分。 |

#### 6.2.9 `triage_rules` 分层规则（实盘权重的实证依据）

`low_value` 通过硬过滤与打分后应用 `triage_rules`，标记为 `keep/watch/drop`；
`momentum` 清单不打 triage，改用 `research_priority` 五层。实盘权重倍数
（依据 2021-2026 幸存者数据集的 120d 前向收益实证，详见
`docs/live_pilot_protocol.md` §3.1）：

| 来源 | 标签 | 判定语义 | 实盘权重 | 120d 实证（组合口径） |
|---|---|---|---|---|
| low_value | keep | composite ≥ 0.45~0.58 且 ps/pe 折价 ≥ 阈值（按通道） | 1.0x | risk_off +6.06%（胜率 73.5%）；risk_on +17.70% |
| low_value | watch | 仅一项达标 | 0.5x | risk_off +3.32%；risk_on +9.74% |
| low_value | drop | 双项均不达标（scored 架构下实际不触发，已记录为死层） | 0x | — |
| momentum | research_now | 动量+AI+估值全达标 | 1.0x | +13.08%（胜率 63.5%） |
| momentum | watch_for_pullback | 动量强但有追高风险 | 1.0x | +9.29%（胜率 75.5%） |
| momentum | theme_only | 仅有 AI 主题（最弱可买层） | 0.5x | +6.25%（胜率 73.6%） |
| momentum | avoid_for_now | AI 关联弱（research pool 语义） | 0.5x | +8.76% |
| momentum | left_side_watch | 左侧下跌接刀 | **0x 排除** | +1.05%（胜率 43.8%） |

注意：两风格共用同一 triage 阈值与 momentum 机器；风格分化由 low_value 的
硬门结构（risk_off 要求回撤深度，risk_on 要求站上 SMA200）与评分权重承担。
`research_now`/`watch_for_pullback` 是最可信的两层；当前实证下
`avoid_for_now` 的"回避"语义面向 research pool，momentum 语境中表现中游。

### 6.3 通道参数（`channel_profiles.<channel>`）

每个通道（`core_ai`、`ai_enabler`、`ai_peripheral`、`ai_smallcap`）都可覆盖以下参数。
`ai_smallcap` 为小盘研究层专用通道（见 4.4）：`min_watchlist_etf_count` 为 `0`（来源标记不计入 ETF 数），
`min_ai_link_score` 较低（ETF 共识项天然为 0），趋势/动量成交额门槛为 1000 万美元；其成员自动获得
`ai_infrastructure_exposure` 研究标签（按 bucket 主题归属，而非 ETF 持仓推断）：

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
- `--config`：配置文件路径（默认 `configs/config.risk_off.json`）
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
- Low-Value 核心清单：`..._ranked.csv`
- Low-Value 分通道清单：`..._ranked_core_ai.csv`、`..._ranked_ai_enabler.csv`、`..._ranked_ai_peripheral.csv`
- Industry-Trend 辅助清单：`..._ranked_industry_trend.csv` 及其分通道文件
- Momentum 辅助清单：`..._ranked_momentum.csv` 及其分通道文件
- Research Pool 宽口径研究候选池：`..._ranked_research_pool.csv`
- 过滤诊断（按通道）：`..._ranked_diagnostics_<channel>.csv`
- 首因诊断（按通道）：`..._ranked_diagnostics_<channel>_first_fail.csv`
- 网络诊断：`..._ranked_network.json`
- Markdown 报告：`..._ranked_report.md`（报告头部含 `Config:` 行，下游工具据此识别风格）

实盘试点相关输出：
- 交易计划：`outputs/trade_plan_<UTC>.md` + `.csv`（由 `generate_trade_plan.py` 生成，
  含分层→权重图例、持仓明细、熔断器状态、基线预期）
- 数据质量周检：`outputs/ttm_population_validation*.md` + `*_coverage.csv`
  （680 家公司逐项覆盖矩阵）

控制台结束时会打印完整入选股票简表。`Low-Value` 简表是核心生产清单；`Industry-Trend`、`Momentum` 和 `Research Pool` 简表用于辅助人工研究。

关键研究解释字段：
- `research_priority`：研究优先级，取值为 `research_now`、`watch_for_pullback`、`left_side_watch`、`theme_only`、`avoid_for_now`。
- `research_score`：研究评分，综合估值、质量、AI 关联、成长、动量和风险扣分。
- `research_tags`：正向标签，例如 `cheap_relative_to_history`、`cheap_relative_to_peers`、`cash_flow_value`、`quality_compounder`、`strong_ai_link`、`ai_infrastructure_exposure`、`momentum_breakout`。
- `research_risks`：风险标签，例如 `high_absolute_valuation`、`expensive_relative_to_peers`、`weak_growth`、`negative_momentum`、`possible_value_trap`。
- `research_summary`：基于上述字段生成的简短解释。

`..._ranked_research_pool.csv` 不经过三张并行扫描清单的完整硬过滤；它基于 watchlist、价格/流动性预筛和已计算指标生成，用于发现需要人工复核的潜在标的，不等同于买入清单。`theme_only` 表示主题或估值线索存在但质量、动量、AI 关联或风险标签仍不足以进入核心清单。

`left_side_watch`（左侧观察）：标的满足"便宜 + 高质量（quality ≥ 0.70）+ 营收/净利正增长 + AI 关联"但处于下跌趋势（`negative_momentum`）时不降级为 `theme_only`，而是在研究池中保留更高可见性并附带 `negative_momentum`、`possible_value_trap` 风险标签，供人工判断左侧介入时机。`negative_momentum` 仍在 `low_value_excluded_research_risks` 中，因此左侧观察标的不会进入 `low_value` 主清单（不自动买入）。

`max_accrual_ratio` 过滤只惩罚高正值应计（利润未转化为现金）；负应计（经营现金流显著超过净利润）是盈利质量好的信号，不会被剔除。

## 9. 运行日志与诊断

### 9.1 终端日志

扫描日志格式：`[HH:MM:SS][LEVEL][+elapsed] message`  
回测日志格式：`[scope HH:MM:SS +elapsed] message`

包含：
- 阶段进度（`[1/6]` ~ `[6/6]`）
- SEC 长阶段进度
- 分层过滤诊断（`base_hard` / `quality_or_theme_hard` / `valuation_hard`）
- 输出文件路径
- 结束时三张并行扫描清单按通道的入选股票汇总
- 结束时宽口径研究候选池汇总

### 9.2 网络诊断 JSON

按服务（`alpaca`、`sec`）统计：
- 请求量、状态码分布、重试、异常
- 限速等待次数/耗时
- 缓存命中（`cache_hits`/`cache_misses`）
- 汇总标记：`had_rate_limit_or_network_issue`
- 扫描上下文中的分层漏斗与首因集中度：
  - `scan_context.diagnostics_layer_summary`
  - `scan_context.first_fail_concentration_summary`

### 9.3 前置硬过滤分层

- `base_hard`：交易与可执行性基础门槛（价格/成交额/市值/watchlist/sic 等）
- `quality_or_theme_hard`：财务质量与主题关联门槛（盈利、现金流、杠杆、AI link 等）
- `valuation_hard`：估值与价量风格门槛（估值分位、折价、位置、波动等）

说明：
- 当前代码支持在 `channel_profiles.<channel>` 中覆写更多前置门槛（如 `require_positive_*`、`min_revenue`、`min_net_income`、`max_ps`、`max_pe`），用于拉开 `risk_on / risk_off` 的分流差异。

## 10. 缓存与限速

默认开启本地缓存（目录 `cache/`）：
- Alpaca：assets/snapshots/bars（TTL 可配置）
- SEC：ticker mapping、submissions、companyfacts

SEC 缓存采用**增量更新**机制：
- **submissions**（每个 ~176 KB）：每次扫描都重新拉取（`sec_cache_ttl_submissions_sec`，默认 0 = 始终刷新），作为变更检测器。全量 ~680 个公司约需 2.3 分钟。
- **companyfacts**（每个 ~4 MB，全量 1.9 GB）：只在 submissions 显示有新 filing 且 filing 日期晚于缓存写入时间时才重拉。对于无新 filing 的公司（通常 95%+），4 MB 的 facts 缓存直接命中，不产生网络请求。
- 无需手动删除 `cache/` 即可获取最新基本面数据。

相关参数：
- `alpaca_cache_enabled`
- `alpaca_cache_ttl_assets_sec`
- `alpaca_cache_ttl_snapshots_sec`
- `alpaca_cache_ttl_bars_sec`
- `alpaca_max_requests_per_sec`
- `sec_max_requests_per_sec`
- `sec_cache_ttl_submissions_sec`（默认 0 = 每次刷新）

## 11. 回测（可选）

入口：

```bash
python run_backtest.py --mode historical_replay --scan-config configs/config.risk_off.json
```

常用参数：
- `--mode historical_replay|existing_runs`
- `--outputs-dir`
- `--list-types low_value,industry_trend,momentum,research_pool`
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
- `*_events_signal_diagnostics.csv`：每个再平衡日、清单、通道、过滤层的输入数、剩余数、剔除数和通过率。
- `*_events_signal_channel_summary.csv`：每个再平衡日、清单、通道的候选数、入选数、入选股票、首要失败原因和 near-miss 原因。
- `*_report.md`
- `*_report_network.json`

`*_events.csv` 中的 `event_status` 用于区分回测事件质量：
- `valid`：入选股票均可计算 forward return。
- `partial_valid`：部分入选股票可计算 forward return。
- `no_signal`：该再平衡日没有任何入选股票，通常表示筛选条件过严或候选池不足。
- `unpriced`：有入选股票，但无法取得有效 forward return，通常与价格数据缺失、窗口过短或退市处理有关。

`*_summary.csv` 和 `*_segments.csv` 会统计 `n_no_signal_events`、`n_unpriced_events`、`n_partial_valid_events`，用于区分“没有选出股票”和“选出股票但无法定价”。

## 12. 参数调优（自动化）

调参输入：
- `configs/tuner.param_space.json`：参数轴定义（`path` + `values`）
- `configs/tuner.param_space.3layer.json`：三层过滤专用参数轴，覆盖流动性、通道级估值分位、通道级 FCF yield 和动量成交额门槛。

生产评价口径：
- `--list-types` 控制回测输出哪些清单。
- `--primary-list-types` 控制哪些清单参与候选参数评分和护栏判断，默认 `low_value`。
- `industry_trend`、`momentum`、`research_pool` 默认只作为辅助诊断，不决定生产参数是否通过。

核心约束参数：
- `--min-total-valid-events`：候选参数整体最少有效事件数。
- `--min-window-valid-events`：每个回测窗口最少有效事件数。
- `--coverage-ratio-floor`：有效事件数占总事件数的下限。
- `--min-strict-total-valid-events`：当同时评估 `research_pool` 时，三张并行扫描清单的最少有效事件数。
- `--strict-coverage-ratio-floor`：当同时评估 `research_pool` 时，三张并行扫描清单覆盖率下限。
- `--min-strict-avg-win-rate`：当同时评估 `research_pool` 时，三张并行扫描清单平均胜率下限。
- `--max-acceptable-drawdown`：最大可接受回撤，超过后候选失败。
- `--min-avg-return`：平均绝对收益下限，默认 `0.0`。
- `--min-avg-excess-vs-qqq`：平均相对 QQQ 超额收益下限，默认 `0.0`。
- `--min-avg-win-rate`：平均胜率下限，默认 `0.52`。
- `--min-positive-window-score-ratio`：综合得分为正的窗口比例下限，默认 `0.5`。
- `--min-positive-excess-window-ratio`：相对 QQQ 超额收益为正的窗口比例下限，默认 `0.5`。
- `--max-empty-window-ratio`：无有效信号窗口比例上限，默认 `0.25`。
- `--negative-return-penalty-weight`、`--negative-excess-penalty-weight`、`--low-win-rate-penalty-weight`、`--positive-window-penalty-weight`、`--positive-excess-window-penalty-weight`、`--empty-window-penalty-weight`：未达到收益、超额、胜率、正窗口比例、正超额窗口比例、空窗口比例要求时的惩罚权重。

调参输出（默认在 `outputs/`）：
- `tuning_<UTC>_results.csv`：每个候选参数组的评分与约束结果
- `tuning_<UTC>_report.md`：Top 候选与三配置选型说明
- `tuning_<UTC>_summary.json`：本次调参摘要（run id / picks / 文件路径）

`results.csv` 的关键分层字段：
- `strict_total_valid_events`、`strict_coverage_ratio`：三张并行扫描清单（`low_value`、`industry_trend`、`momentum`）的有效事件和覆盖率。
- `research_pool_total_valid_events`、`research_pool_coverage_ratio`、`research_pool_avg_excess_vs_qqq`：研究池的有效事件、覆盖率和相对 QQQ 超额。
- `coverage_ratio`、`avg_return`、`avg_excess_vs_qqq`：默认代表 `--primary-list-types` 指定的生产评价清单；当前默认是 `low_value`。

near-miss 诊断：
- `top_first_fail` 表示按过滤链顺序首次失败的条件。
- `top_near_miss` 表示“如果只放开这一个条件，本来可以通过其它条件”的主要瓶颈。
- 当 `top_first_fail` 和 `top_near_miss` 不一致时，应优先参考 `top_near_miss` 判断最值得调的阈值。

推荐运行频率：
- 生产扫描：可日内多次
- watchlist 刷新：每周一次（或ETF有明显变动时）
- 参数调优：每周一次或双周一次（与生产扫描解耦）

建议上线流程：
1. 先跑 `scripts/tune_parameters.py` 生成新参数。
2. 审阅 `tuning_*_report.md` 与 `tuning_*_results.csv`。
3. 使用新参数运行 `run_scan.py`，确认输出质量后再投入日常使用。

## 13. 工具脚本参考

### 13.1 `scripts/observation_scan.py` —— 双风格观察扫描

观察期的标准入口：依次运行 risk_off 和 risk_on 两个配置的完整扫描，并输出对照摘要。

```bash
# 标准（两风格全量扫描）
.venv/bin/python scripts/observation_scan.py

# 限制标的数（快速试验）
.venv/bin/python scripts/observation_scan.py --max-symbols 100

# 仅打印最近一次扫描的观察摘要（不重跑）
.venv/bin/python scripts/observation_scan.py --skip-scan
```

每次扫描自动归档 watchlist 快照到 `data/watchlist_history/`（用于 PIT 回测）。观察指标与审查触发条件见 `docs/two_style_observation_protocol.md`。

### 13.2 `scripts/refresh_ai_watchlist.py` —— 刷新 ETF 持仓 watchlist

```bash
python scripts/refresh_ai_watchlist.py --config configs/config.risk_off.json --output data/ai_watchlist.csv
```

从 ETF 持仓页面抓取标的并集，重建 `data/ai_watchlist.csv`。建议每周运行一次。

### 13.3 `scripts/build_smallcap_universe.py` —— 构建小盘研究层

```bash
python scripts/build_smallcap_universe.py --config configs/config.risk_off.json
```

合并 Nasdaq 筛选、Yahoo 热榜和 `data/ai_smallcap_manual.csv` 到 `ai_smallcap` bucket。幂等重建。运行顺序：refresh watchlist → smallcap builder → scan。

### 13.4 `scripts/tune_parameters.py` —— 参数调优

```bash
# 本地执行
python scripts/tune_parameters.py \
  --base-config configs/config.risk_off.json \
  --param-space configs/tuner.param_space.json \
  --max-candidates 36

# Modal 云并行执行（每候选一个容器，--executor modal）
python scripts/tune_parameters.py \
  --base-config configs/config.risk_on.json \
  --param-space configs/tuner.param_space.momentum.json \
  --max-candidates 80 --executor modal
```

详见 §12（参数调优）。`--executor modal` 需要已配置 Modal（见 `scripts/modal_executor.py`）。
默认不会覆盖生产配置；需要晋级时显式加 `--promote`，且只能写回与 `--base-config` 同一 style。
`--allow-latest-watchlist-fallback` 默认关闭；显式开启仅用于研究（会引入前视成分并打印警告）。

### 13.5 `scripts/calibrate_thresholds.py` —— 产出量校准

```bash
python scripts/calibrate_thresholds.py --base-config configs/config.risk_off.json
```

读取最近一次扫描的诊断文件，检查三张清单的行数是否落在目标区间（默认 8-15 行），生成 `conservative` / `production` / `aggressive` 三档配置文件。纯本地操作，不跑回测。

### 13.6 `scripts/modal_executor.py` —— Modal 云执行器

tune_parameters 的 `--executor modal` 选项的后端。每个候选在独立 Modal 容器内执行完整回测，评分逻辑在本地。需要 Modal Volume `ai-scanner-cache`（包含 SEC 缓存）和 `.env` 中的 API 密钥。

### 13.7 `scripts/phase4_validation.py` —— 体系级验证

```bash
.venv/bin/modal run scripts/phase4_validation.py
```

将全部生产配置在 Modal 三容器并行回放（`--executor` 的体系级版本），拉回 events/benchmarks/segments 用于组合分析。主要用于架构级验证（如两风格对比）。

### 13.8 `scripts/audit_gap12_regression.py` —— 财务口径回归审计

```bash
python scripts/audit_gap12_regression.py --config configs/config.risk_off.json
```

对比 baseline 与新版本的 gap-12 财务指标计算结果，用于验证数据管道变更后是否引入回归。

### 13.9 `scripts/build_due_diligence_cards.py` —— 尽调卡片

从最新扫描结果生成每只入选股票的尽调卡片（含风险标签、估值指标、AI 关联度等），输出为结构化格式。

### 13.10 `scripts/build_investment_list.py` —— 投资清单

从最新扫描结果生成最终投资清单（含综合风险标签），基于 Low-Value + Research Pool 合并输出。

### 13.11 `scripts/validate_small_scale.py` —— 小规模验证

```bash
python scripts/validate_small_scale.py --config configs/config.risk_off.json --max-symbols 100
```

用少量标的快速验证扫描管线（引擎/配置/数据/输出列）是否正常，适合部署前冒烟。

### 13.12 `scripts/validate_ttm_population.py` —— 全总体数据质量门槛（周检）

```bash
.venv/bin/python scripts/validate_ttm_population.py
```

对 watchlist 全部 ~680 家公司验证 7 个流量家族（revenue/NI/OCF/capex/EBIT/D&A/利息）
的 TTM 重建：I1（4 季度之和=年报）+ I2（推导值 vs 申报方自报离散值）。PASS 条件：
I2=0 且运作窗口违反率 <1%。输出逐公司覆盖矩阵（`*_coverage.csv`，4,760 行）。
**实盘试点协议的周检门槛：连续 2 周 FAIL 暂停新开仓。**

### 13.13 `scripts/generate_trade_plan.py` —— 生成选股快速参考（兼容名 trade_plan）

```bash
.venv/bin/python scripts/generate_trade_plan.py --capital 100000
# 可选：--risk-on-alloc / --risk-off-alloc（观察镜头，非资金分割）
#       --max-position-pct 0.10 --max-positions-per-sleeve 10 --cash-buffer-pct 0.10
#       --include-smallcap（默认关闭：ai_smallcap 为辅线观察层，不进交易计划）
```

从最新双风格扫描生成供人工复核的快速参考摘要（`outputs/trade_plan_<UTC>.md/.csv`）。历史文件名 `trade_plan` 为兼容保留；脚本**不连接券商、不读取真实持仓、不生成订单、不自动交易**。参考摘要只接受带 `Config:` 头、时间戳可解析且足够新鲜的一对报告；默认要求最新报告 ≤12 小时、两风格时间差 ≤6 小时，拒绝用旧报告补位：
排序规则：low_value 与 momentum 的 composite 出自不同权重向量、量纲不可直接比较
（2026-10-02 中位数 sweep 后 momentum ~1.2-1.3 vs low_value ~0.6-0.8），袖珍选择按
**各清单内、按通道分组的百分位名次（list_pct）** 排序——最佳 keep 与最佳 momentum
并列 1.0 公平竞争，各清单内部排序质量（权重 sweep 优化的对象）保持不变；置信度取
标的两清单最高档（keep+momentum 双入选不会被代表行降档）。
分层→参考权重图例、双风格合并候选（置信度累加，单标的参考权重 ≤10%）、QQQ 熔断器状态、
基线预期（诚实数字含 t 值）。风格识别以报告头 `Config:` 行为准。
QQQ < SMA200 时按 live pilot 规则不生成“新开仓参考名单”，不能用 `--allow-no-breaker` 绕过。
只有熔断器数据不可用/陈旧（>4 天）时，才允许用 `--allow-no-breaker` 显式绕过数据可用性检查
（报告打标）；全部仓位触及单仓上限时，未部署部分保留现金并在报告中单独列示。

### 13.14 `scripts/ic_analysis.py` —— 截面 IC 分析

```bash
.venv/bin/python scripts/ic_analysis.py \
  --dataset outputs/weight_dataset_risk_off_v2.csv \
  --scan-config configs/config.risk_off.json
```

对幸存者数据集计算 composite 与各维度对前向收益的 Spearman IC（按日期聚合、t 检验、
分年/分状态/分维度）。用于诊断哪些维度有排名力。

### 13.15 `scripts/extract_weight_dataset.py` —— 幸存者数据集提取

```bash
.venv/bin/python scripts/extract_weight_dataset.py \
  --scan-config configs/config.risk_off.json --start-date 2021-01-01 \
  --output outputs/weight_dataset_risk_off_v2.csv
```

复用回测 PIT 基础设施，把每个再平衡日的全部硬门幸存者 + 完整指标 + 20/60/120d
前向收益落盘（约 5 万行）。是权重扫描与 IC 分析的输入。零 Modal 成本。
`--allow-latest-watchlist-fallback` 默认关闭（与回测一致）；显式开启仅用于研究，
产物元数据 `watchlist_source` 如实记录成分来源（含前视警告）。

### 13.16 `scripts/sweep_score_weights.py` —— score_weights 离线扫描

```bash
.venv/bin/python scripts/sweep_score_weights.py \
  --dataset outputs/weight_dataset_risk_off_v2.csv \
  --scan-config configs/config.risk_off.json --n-candidates 1000
```

预计算归一化矩阵后对权重候选做纯线代评分（train/valid 分割防过拟合）。
2026-09-26 结论为阴性（保留基线权重），脚本保留用于复验。

### 13.17 `scripts/apply_consensus_weights.py` / `watch_tuning_results.py`

- `apply_consensus_weights.py`：把权重扫描结论写入生产配置（含生效值验证）。
- `watch_tuning_results.py`：Modal 调参任务的结果看护（进程退出即备份产物，防丢失）。

### 13.18 多主题工具链（docs/multi_theme_expansion.md）

```bash
# ① 主题底单：抓取主题 ETF 持仓 + 影子体检（漏斗 autopsy，不动生产）
.venv/bin/python scripts/build_theme_universe.py            # 全部主题
.venv/bin/python scripts/build_theme_universe.py --theme nuclear

# ② 生成/重新生成主题扫描配置（configs/config.theme.<name>.json ×5）
.venv/bin/python scripts/generate_theme_configs.py

# ③ 运行主题扫描（与 AI 扫描完全同构：scored 架构、三清单、QQQ 熔断）
.venv/bin/python run_scan.py --config configs/config.theme.nuclear.json
```

主题注册表：`configs/theme_universe.json`（源 ETF/基准篮/关键词组/主题分门槛）。
当前主题：nuclear / quantum / biotech / rare_earth / critical_minerals。
theme_link = 0.40×主题ETF共识 + 0.15×主题基准联动 + 0.10×backlog（披露组件
权重 0——SEC submissions 无业务描述文本，见 §5.3；文本源修复后重验证）。
主题扫描**不归档** watchlist 快照（`archive_watchlist_snapshots=false`），不进入
AI 的 PIT 序列。阶段 3（试点接入）前的校准积压见设计文档。

### 13.19 `scripts/daily_run.py` —— 每日运行入口（推荐）

```bash
.venv/bin/python scripts/daily_run.py  # 工作日：三套观察流 + 归档；默认不生成交易计划
.venv/bin/python scripts/daily_run.py --generate-trade-plan --capital N  # 需要快速参考时显式生成
.venv/bin/python scripts/daily_run.py --skip-scan --evaluate  # 只跑 cohort 结算
```

按星期自动调度（详见 §15 与 `docs/theme_observation_protocol.md`）：
- **工作日**：AI 双风格扫描 + 五主题扫描 + Venture sleeve 扫描 + cohort 归档
- **周一额外**：数据质量门槛（validate_ttm_population）+ 主题篮子刷新 + Venture 底单重建
- **周五额外**：全量 cohort 结算（--evaluate 传播到各观察脚本）
- 周末仅 `--evaluate` 可用（市场关闭）
- 扫描完成后自动跑左侧名单资金流（`flow_tracker.py`，`--skip-flow` 跳过）
- **不会每日自动生成 trade plan**；它只是完整报告的人工快速参考，需要时显式传 `--generate-trade-plan`
- 参考摘要不连接券商、不读取历史/当前持仓、不下单；`--capital` 只用于把模型权重换算成便于阅读的参考名义金额
- 显式生成参考摘要时，本次 AI 双风格扫描失败会 fail-closed；周一若数据质量周检失败也不会生成新的参考摘要

### 13.20 `scripts/flow_tracker.py` —— 左侧名单大单流统计

```bash
.venv/bin/python scripts/flow_tracker.py --auto-left-side --days 8
.venv/bin/python scripts/flow_tracker.py --symbols CRDO,VST --days 8
```

对给定标的回填 SIP 逐笔成交（按日缓存到 `data/flow/`，可续跑），输出
$100K/$1M 大单买方主动性（tick rule 近似）、场外占比与 3 日价格联合判定
（`accumulate_confirm` / `accumulate_unconfirmed` / `distribute` / `mixed`）。
定位是注释层（不进选股闸门）；单日流向是噪声，以多日聚合为准。
- 日志：`.debug_logs/daily_YYYYMMDD.log`

## 14. 说明与限制

- 设计、逻辑与计算审查记录：[2026-10-03 问题清单与优化建议](docs/design_and_calculation_review_20261003.md)（含复现证据、优先级和修复验收条件；记录不代表问题已修复）。
- 模块重构方案：[2026-10-03 拆分边界与渐进迁移计划](docs/modular_refactoring_plan_20261003.md)（含公共计算契约、依赖方向、兼容迁移和验收标准；方案尚未实施）。
- 本项目用于研究与筛选，不构成投资建议。
- 历史回测为工程近似，不等价于完整 PIT 学术数据库回测。
- ETF 持仓抓取依赖第三方页面结构，建议定期抽检 watchlist 刷新结果。
- 配置扩展建议遵循：
  1. 在 `ScanConfig` 增加字段
  2. 在 `resolve_channel_profile` 接入通道覆盖
  3. 在过滤步骤或打分逻辑中显式使用
  4. 同步更新本 README

## 15. 实盘试点操作流程（Live Pilot）

完整规则见 `docs/live_pilot_protocol.md`（预注册，含资金分级 P0 纸面→P1 25%→
P2 50%→P3 100% 与降级条件）。日常观察运行：

```bash
.venv/bin/python scripts/daily_run.py
```

按星期自动执行：工作日跑 AI 双风格 + 五主题 + Venture 三套观察扫描 + cohort 归档；
周一额外跑数据质量门槛 + 主题篮子刷新 + venture 三层底单重建；周五额外跑 cohort 结算。
**trade plan 是人工快速参考，不是自动交易任务。** 需要把完整扫描压缩成简表时显式生成：

```bash
.venv/bin/python scripts/daily_run.py --generate-trade-plan --capital 100000
```

可选参数：`--evaluate`（非周五强制结算）、`--skip-scan`（跳过扫描只跑维护）、
`--skip-flow`（跳过资金流注释层）。

手动分步命令（与 daily_run.py 等价）：

```bash
# ① 每周：双风格观察扫描（信号源，自动归档 PIT 快照）
.venv/bin/python scripts/observation_scan.py

# ② 每周：数据质量门槛（必须 PASS；连续 FAIL 暂停开仓）
.venv/bin/python scripts/validate_ttm_population.py

# ③ 可选：把完整双风格扫描压缩成便于人工阅读的快速参考
.venv/bin/python scripts/generate_trade_plan.py --capital 100000

# ④ 人工复核并自行决策
#    trade_plan 只是参考摘要：不连接券商、不读取持仓、不生成订单、不自动交易。
#    次日开盘、参考权重、财报窗口、止损和 QQQ<SMA200 等字段仅用于展示预注册研究/
#    人工执行协议的上下文，是否交易及如何执行完全由用户自行决定。

# ⑤ 五主题 + Venture sleeve（P0 纸面观察，互不阻塞）
.venv/bin/python scripts/theme_observation_scan.py                  # 五主题
.venv/bin/python scripts/theme_observation_scan.py --sleeve venture # Venture
.venv/bin/python scripts/theme_observation_scan.py --evaluate       # 周五结算到期 cohort
```

输出示例（`trade_plan_*.md` 核心段）：

```
- 熔断器: QQQ close=744.44 vs SMA200=665.55 → trend_ok=True
- 总资金: $100,000 | 可部署 90%（现金缓冲 10%）| 单仓上限 10%
- 持有期: 120 个交易日（分批滚动，每月一个新 cohort）

## 双风格合并仓（两风格同时选中，置信度最高）（7 个仓位）
| MU | ...momentum(watch_for_pullback)... | 9.0% | 9,000 |
| QCOM | ...momentum(research_now)... | 9.0% | 9,000 |
...
### risk_off 独有（3 个仓位）
| CHKP | low_value | keep | 4.5% | 4,500 |   ← 20-F 年报申报者，数据滞后 ~9 个月（已知）
```

参考协议（用于人工复核和研究记录，不是程序交易指令）：
- drop/left_side_watch、watch/theme_only 的权重规则是参考分层语义；
- 跳空、熔断、止损等规则用于解释研究/人工交易协议，程序不会自动执行；
- paper cohort 仍按既定周期结算，用于记录 120d 超额 vs QQQ、超额胜率；
- 阶段评估由人工根据协议复核。

历史基线（Phase 4R v2，2023-2026，诚实数字）：risk_on low_value 120d 超额
+4.94pp/期（t=1.82 未达显著）、momentum +1.16pp（t=0.53）；risk_off 持仓期
-3.89pp（t=-2.86，职责=熔断保护+绝对收益）。截面排名 IC t=3~7（已验证）。
完整语义见 `outputs/performance_final_verified.md`。
