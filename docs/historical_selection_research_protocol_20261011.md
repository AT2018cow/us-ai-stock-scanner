# Historical Selection v1 — 研究、复现、Modal 执行及证据审核协议（2026-10-11）

> **性质：研究协议 + 有边界的实验执行入口；不是策略升级。**
> 本文面向实际操作者，按顺序执行即可。研究的目标是找出当前 Company Quality、Entry Quality、Action/Attention 和流动性筛选的可改进之处，并形成 **Generalized Selection v2 的有证据候选方案**。不能因为一次历史回测好看就切换生产规则。
>
> **优先级**：最新交接 `docs/work_handoff_after_pr57_20261011.md`（位于 `docs/handoff-after-pr57-20261011` 分支）及 `docs/generalized_end_to_end_research_v0.md` 是 Generalized-v0 的最新执行合同。本文新增的是**并行的历史研发轨道**，不替代 62-name 的 2026-10-12 非 formal 实验，不覆写旧 v1 prospective 历史。
>
> **本 PR 的边界**：只增加协议、为现有前台 Modal runner 增加 `company_quality` / `entry_quality` 数据集提取模式及小型测试。不更改 `Quality v1`、`Entry v1`、Action 映射、QQQ regime、生产 IEX/$2m gate、正式配置或候选池。

## 0. 最重要的判断规则（先读）

1. **可以现在使用历史数据研究和写实验代码，不必等 10 月 12 日收盘。**
2. 有三种不同证据：`retrospective exploratory`（探索性历史研究）、`temporally-separated diagnostic`（时间分段复核，不自动等于全新 OOS）、`prospective`（未来冻结后观察）。**不要把前两者写成第三种。**
3. 2026-10-11 才冻结的 `data/research/generalized_v0/` **不能伪装成 2026-10-09 的 PIT membership**。可回看这些证券的历史财务/行情以诊断机制，但标成 `post-hoc cohort / non-PIT membership`，不能据此宣称跨行业 alpha。
4. 2023–2026 年旧 watchlist 的 `union_superset_approx` 或 `latest_fallback` 并非当时真实 ETF 成分。允许探索、禁止按真实 PIT universe 宣称策略效果；`--allow-latest-watchlist-fallback` 必须保持关闭。
5. 候选发现、业务模式分类、AI 主题是**三种不同属性**；`core_ai`、`ai_enabler`、`ai_peripheral`、`ai_smallcap` 不能充当行业分类。
6. 每个信号日期只能使用当时可获得的 filing/price 信息；核对 `fundamental_data_asof`、`market_asof`、filing accession/公开日期、原始输入哈希、前向标签终止日。仅凭日期列不过未来日期不足以证明 SEC PIT 完美。
7. 新旧方案必须在**同一个 signal_date × symbol × 数据状态**下做配对对照；20/60/120d 重叠标签不能当作独立观测；不能只展示涨得最好的案例。
8. **不做**参数大搜索、自动选股池重构、全市场回测大工程、自动下单、账户 NAV、生产阈值调优、v1 history 覆写、Generalized-v0 `--formal`。
9. 若现有历史原始数据/缓存足够，则**只做离线分析**；不得为了“多跑一次”而重新抓取同样的 SEC/Alpaca 历史。

## 1. 应交付的研究成果及检查点

| 顺序 | 工作包 | 回答的问题 | 最低交付 |
| --- | --- | --- | --- |
| G0 | 数据/复现/覆盖度基线 | 哪些历史数据真正可用、可复现？ | `data_inventory.csv`, `coverage_and_integrity.md`, manifest |
| H1 | Quality v1 基线和跨模型适用性 | A/B/C 及缺失/置信度有区分度吗？财务口径在哪些行业不适用？ | Quality cohort/rank IC/concentration、案例分组 |
| H2 | Entry v1 基线与 `WATCH_BREAKOUT` 原因拆解 | READY、PULLBACK、BREAKOUT、DAMAGED 的后续变化有意义吗？ | Entry cohort/transition/persistence、`breakout_reason_cases.csv` |
| H3 | Action / Attention v1 与 Top-K 对照 | 谁被 15 名上限挡掉？B+READY 是否值得单独关注？ | Action cohort/compactness、`ranking_paired_by_date.csv`, `b_ready_cases.csv` |
| H4 | 流动性与 Universe 敏感性（有足够历史同源数据才执行） | 单日 IEX 代理与 20-session 是否有稳定误差？ | `liquidity_coverage.csv`, `liquidity_cases.csv` 或 INCONCLUSIVE |
| R | 统一评审与 v2 候选 | 哪些改变有证据支持、哪些应不动？ | `research_review.md`, `candidate_policy.md`, `reviewer_notes.md` |

**不能用空表冒充结论。** 完不成的组件写 `INCONCLUSIVE`、缺少何种数据、为什么缺少、下次如何补证据即可；G0 是所有后续工作的进入门槛。

## 2. G0 — 环境和历史数据检查（先做，不跑重计算）

### 2.1 准备代码和 Python 环境

使用 **Python 3.12**，从干净工作树开始。建议克隆/切换到**本 PR 的最终绿色 commit**；下面 `<REVIEWED_SHA>` 需要换成实际提交 SHA，**不是**旧的 main SHA。

```bash
git fetch origin
git checkout research/historical-selection-validation-protocol-20261011
git status --short                   # 应为空
git rev-parse HEAD                   # 记录完整代码 SHA

python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip install modal==1.5.5

.venv/bin/python -m unittest discover -s tests
```

如本地 venv 已正确安装，可跳过重建 venv，但不能跳过测试及 SHA 记录。必须等 **本 PR exact final head 的 GitHub Actions 测试通过**再作为正式实验的代码来源。

**不要打印/上传** `.env`、Alpaca 密钥、SEC user-agent 实际身份。代码读取 `.env` 并将其中列在白名单的必要键安全传入 Modal Secret；只允许向预期的 **infi** workspace 发送。首次使用 Modal 时先完成本机 `modal token set` 或已有 profile 的授权，命令始终显式加 `MODAL_PROFILE=infi`。

### 2.2 先盘点本地和 Modal 已存在的资产

```bash
find outputs -type f \( -name '*company_quality*.meta.json' -o \
  -name '*entry_quality*.meta.json' -o -name '*weight*.meta.json' \) -print 2>/dev/null
ls -ld data/watchlist_history 2>/dev/null || true

MODAL_PROFILE=infi .venv/bin/python -m modal volume ls \
  ai-scanner-research /post_pr23_baseline_202610/datasets
```

如果 Modal 返回“目录不存在”，只记 `not_found`，不要假设远端丢失了所有历史数据。检查其他明确知道的历史 run ID，不做全 Volume 大规模下载。

**严禁把旧 `weight_dataset_*.csv` 当成 Quality/Entry 全体**：它只有旧策略硬门槛幸存者。独立 Quality 评估要求 `dataset_kind=company_quality`，Entry 及 Action 评估要求 `dataset_kind=entry_quality`，同时 `pre_strategy_cross_section=true`；两个 dataset 都有同名的 `.meta.json`。不要直接改 metadata 假造数据种类。

为每个可用资产建立 `data_inventory.csv`，至少列：
`asset_id,path_or_volume,kind,sha256,bytes,code_sha,config_sha,start_date,end_date,n_rows,n_signal_dates,n_symbols,watchlist_source,feed,filing_provenance,cache_provenance,limitations,reuse_decision`。
未知项填 `unknown`，不可凭猜测填 PASS。记录哪些文件只是 Git 仓库的汇总而非原始 PIT 全量样本。

### 2.3 固定研究窗口、评价口径与对照

本轮优先**复用**已有、输入可追溯的历史集。如果必须重新提取，使用固定窗口（防止运行日期变化使样本偷偷增加）：

- 信号日期：**2023-01-01 至 2026-03-31**；每月评估，20/60/120 个**交易日**持有期。
- 进入和退出：`next_open` / `close`；交易成本：**单边 15 bps**；基准 **QQQ**；保持 `risk_off` **仅作为兼容的数据加载配置**，不是新的风险偏好策略。
- 样本角色：2023–2024 为解释性开发、2025 为时间分段复核、2026Q1 为**单独报告**的较新时间段。由于旧策略/研究曾接触部分相同历史数据，**这两个后段只称 temporal diagnostics，不自动称 pristine OOS**。
- 若某组前向 120 日标签尚未成熟，写 `missing/immature` 而非 0；检查 `label_end_120`。虽然截至 2026-10-09 上述信号窗口通常足以让 120 个交易日成熟，仍以数据中实际 label-end 为准。
- 先注册本协议中的比较器与字段，再查看对应后续收益；禁止看结果后改窗口、改标的或挑阈值。

若没有能证明历史日期的真实 ETF membership：全表标注 `retrospective with approximate historical universe`。**禁止**将这些结果用于宣布“通用美股 v2 已验证”；通用性需要今后的独立跨行业 PIT 候选池和实验。

## 3. 历史数据已在本地时：直接使用，无需 Modal 重新提取

假设已存在两个合规文件，分别记为：

```bash
QUALITY_DATA=/absolute/path/company_quality_dataset_risk_off.csv
ENTRY_DATA=/absolute/path/entry_quality_dataset_risk_off.csv
```

检查同名 `*.meta.json`、`dataset_kind`、`pre_strategy_cross_section`、时间窗口、`watchlist_source`、哈希和输入来源；不满足则**回到 G0 修复**，不得直接进入排名实验。

执行**只读离线评估**：

```bash
RUN_ID=historical_selection_v1_20261011_01
EXP=outputs/$RUN_ID
mkdir -p "$EXP/analysis"

.venv/bin/python scripts/evaluate_company_quality.py \
  --dataset "$QUALITY_DATA" --output-prefix "$EXP/analysis/quality_v1"
.venv/bin/python scripts/evaluate_entry_quality.py \
  --dataset "$ENTRY_DATA" --output-prefix "$EXP/analysis/entry_v1"
.venv/bin/python scripts/evaluate_action_states.py \
  --dataset "$ENTRY_DATA" --attention-cap 15 \
  --output-prefix "$EXP/analysis/action_v1"
```

三份原有评估程序生成 `*_cohorts.csv`、`*_concentration.csv`、Quality 的 `*_rank_ic.csv`、Entry 的 `*_transitions.csv`/`*_persistence.csv`、Action 的 `*_compactness.csv` 等。**这些是 v1 基线，不等于 H1–H4 已完成。** 下节还需要研究者增加配对诊断和人工案例复核。

## 4. 无可用 pre-strategy 历史集时：优先使用 Modal infi

### 4.1 为什么不直接重跑完整历史回测

`extract_weight_dataset.py` 已具备 `--dataset-kind company_quality|entry_quality`，可以直接提取经过日期截断的**旧 watchlist pre-strategy cross-section**；没有必要为了研究评分状态先重跑所有 `run_backtest.py` 或大规模历史 ETF 重建。

本 PR 为 `modal_baseline_executor.py` 新增 `--dataset-kind` 参数。它**不改变旧 `weight` 默认模式**；新数据集在不同文件名和独立 `_SUCCESS.json` 中存放，避免覆盖旧数据。Modal 的实际重计算是离线数据提取阶段，不是 `--formal`。

### 4.2 冻结输入（必须全部成功）

```bash
RUN_ID=historical_selection_v1_20261011_01
EXP="outputs/$RUN_ID"

# 请先确认存在真实的本地 PIT watchlist 快照目录。
test -d data/watchlist_history || {
  echo 'STOP: data/watchlist_history missing; record provenance and restore it first'
  exit 1
}
test -f data/ai_watchlist.csv || exit 1
mkdir -p "$EXP/frozen_inputs" "$EXP/logs"

cp configs/config.risk_off.json "$EXP/frozen_inputs/"
cp data/ai_watchlist.csv "$EXP/frozen_inputs/"
cp -a data/watchlist_history "$EXP/frozen_inputs/watchlist_history"

git rev-parse HEAD > "$EXP/code_sha.txt"
git status --short > "$EXP/git_status.txt"

sha256sum "$EXP/frozen_inputs/config.risk_off.json" \
          "$EXP/frozen_inputs/ai_watchlist.csv" \
          > "$EXP/frozen_inputs/input_sha256.txt"
find "$EXP/frozen_inputs/watchlist_history" -type f -print0 \
  | sort -z | xargs -0 -r sha256sum \
  > "$EXP/frozen_inputs/watchlist_history_sha256.txt"
```

`git_status.txt` 应为空；不可运行时一边刷新 watchlist、修改配置或清除缓存。若历史快照不完整，先判断 `--pre-snapshot-universe union` 的近似程度并在证据里写明，不得凭空补历史清单。

### 4.3 先提取 Quality，再提取 Entry；每次只有 **1 个**重型容器

本 runner 的研究容器已固定资源边界：

- CPU `(1.0, 2.0)` vCPU（请求 1、上限 2）；
- RAM `(8192, 16384)` MiB（请求 8GiB、上限 16GiB）；
- 单次远程超时 12 小时；
- 缓存 `ai-scanner-cache`、结果 `ai-scanner-research`，持久化到 Volume。
- **最大同时执行的远程重型提取容器数为 1**：先 Quality 完成再 Entry，避免共享 SEC/Alpaca 缓存的竞态、重复网络和不同数据状态。缓存协同瓶颈不靠盲目提高并发解决。离线小型分析可以本机顺序完成；独立离线 CPU 工作如确有必要再以 2–4 vCPU、4–8GiB 的小容器并行最多 2 项。

```bash
set -euo pipefail

MODAL_PROFILE=infi .venv/bin/python -m modal run \
  scripts/modal_baseline_executor.py \
  --run-id "$RUN_ID" --stage dataset --styles risk_off \
  --dataset-kind company_quality \
  --start-date 2023-01-01 --end-date 2026-03-31 \
  2>&1 | tee "$EXP/logs/modal_company_quality.log"

MODAL_PROFILE=infi .venv/bin/python -m modal run \
  scripts/modal_baseline_executor.py \
  --run-id "$RUN_ID" --stage dataset --styles risk_off \
  --dataset-kind entry_quality \
  --start-date 2023-01-01 --end-date 2026-03-31 \
  2>&1 | tee "$EXP/logs/modal_entry_quality.log"
```

上面的两条命令必须**逐条检查 exit code 和远端 `_SUCCESS.json`**，第一条失败时停止，不启动第二条。严禁 `--detach`、后台任务、随意使用默认 Modal profile、无界并发或者借用 `modal_executor.py` 的大规模调参器。

**故障处理**：如果 Modal 网络/进程意外中断，先到 Volume 查看相应 `_SUCCESS.json` 并核对 run spec / 文件哈希。dataset 阶段**不支持逐 signal-date checkpoint**；只有完整成功后能复用，失败后可用同一 spec 重试该数据集。若需要更改时间窗口、代码、config、`dataset_kind` 或输入，应使用**新 `RUN_ID`**，绝不能静默续用旧结果。反复 OOM 才考虑将 hard RAM limit 从 16GiB 提到 24GiB，先记录失败指标与变化理由；不要单纯增加并行数量。Modal 产生费用，应观察实际资源消耗。

检查结果路径：

```bash
MODAL_PROFILE=infi .venv/bin/python -m modal volume ls \
  ai-scanner-research "/$RUN_ID/datasets"

mkdir -p "$EXP/modal_download/datasets"
MODAL_PROFILE=infi .venv/bin/python -m modal volume get \
  --force ai-scanner-research \
  "/$RUN_ID/datasets" "$EXP/modal_download/datasets"
```

应能看到：
`company_quality_dataset_risk_off.csv`、`company_quality_dataset_risk_off.meta.json`、
`entry_quality_dataset_risk_off.csv`、`entry_quality_dataset_risk_off.meta.json`，
以及各自的 `*.SUCCESS.json`。文件名是本 PR 新增的合同；目录嵌套情况以 `modal volume ls` 和实际下载结果为准，不能猜路径。

随后：

```bash
QUALITY_DATA="$EXP/modal_download/datasets/company_quality_dataset_risk_off.csv"
ENTRY_DATA="$EXP/modal_download/datasets/entry_quality_dataset_risk_off.csv"

.venv/bin/python scripts/evaluate_company_quality.py \
  --dataset "$QUALITY_DATA" --output-prefix "$EXP/analysis/quality_v1"
.venv/bin/python scripts/evaluate_entry_quality.py \
  --dataset "$ENTRY_DATA" --output-prefix "$EXP/analysis/entry_v1"
.venv/bin/python scripts/evaluate_action_states.py \
  --dataset "$ENTRY_DATA" --attention-cap 15 \
  --output-prefix "$EXP/analysis/action_v1"
```

注意：`mkdir -p "$EXP/analysis"` 若此前尚未创建，需要先创建。评估脚本主要是 pandas 本地汇总；**无须**为这些小脚本再开 80 个 Modal 容器。如果本地确实内存不足，先报告原始 CSV 尺寸/峰值，再讨论独立远程只读评估，不修改扫描政策。

## 5. H1 — Company Quality 历史诊断（具体怎么做）

1. 检查 `quality_v1_cohorts.csv`、`quality_v1_rank_ic.csv`、`quality_v1_concentration.csv` 和 `quality_v1_report.md` 是否有有效数值。每个 grade A/B/C/UNRATED 都记录样本数、不同 symbol 数、不同 signal-date 数、缺失率及 QQQ 超额 20/60/120d（使用**同日期等权**为主要描述）。
2. 按 2023、2024、2025、2026Q1，以及当时 regime 分层；单独报告异常值和最大单股/单月贡献。报告 **A vs B vs C** 的方向一致性，不以一张 pooled 均值表下结论。
3. 对 `quality_confidence`、`quality_missing_codes`、`quality_risk_codes`、`quality_component_scores_json` 做 coverage/失败模式清单；检查缺失核心数据是否被误当成正面贡献、最新 filing 是否覆盖、非 USD/外籍报告是否明确 fail-closed。
4. 做 **10–20 个事前规则选出的反例/代表案例**（包括 A 但高风险、B/低 confidence、C 却历史走强、UNRATED）。选例规则按绝对缺失数量/score 与风险冲突度等固定，不可只选赢的。
5. **跨行业解释的严格边界**：历史旧 AI 候选池不代表通用 US Core；只有在具备独立核验的业务模式标签及其 PIT/审阅证据时才可跨组比较。否则用 `business_model_unverified` 与 `case-study only`，不要拿 ETF bucket 当 GICS。银行/券商/保险/REIT/unknown 不给出伪可比的 Quality v2 分数。

输出 `quality_coverage.csv`（symbol、日期、Quality、score、confidence、风险/缺失、filing/currency、分组核验状态）及 `quality_failure_cases.csv`（不少于 10 个有解释的风险案例；数据不足则列全部并说明）。**未经会计语义验证不提出行业专用权重。**

## 6. H2 — Entry 历史诊断和突破原因（具体怎么做）

1. 读取 `entry_v1_cohorts.csv`、`entry_v1_transitions.csv`、`entry_v1_persistence.csv`、`entry_v1_concentration.csv`；重点限定在 **Quality A/B** 的 Entry 对照，防止把低质量股票上涨当成好入场点。
2. 按当时 Entry state × Quality A/B × 年份/regime，对齐 20/60/120d 未来收益及 QQQ 超额、下行尾部/最大不利移动（若已有 PIT OHLC 路径可靠）；缺失指标标记 unavailable，不得用最终收益代替真实 MFE/MAE。
3. 对 `WATCH_BREAKOUT` 逐股逐日输出解释性标签 **不修改状态**。用 v1 的原始证据判断未达到 READY 的原因，例如 `SMA200<1`、`SMA50 不在 0.98–1.08`、`RS60<−0.03`、`20d return 不在 [−0.03,0.12]`、`60d return<0`、`drawdown>0.22` 或防守 regime 限制。多个原因可以并存，`reason_codes` 全部保留；若需要 `primary_reason`，按上面所列顺序固定优先级；其他无法解释的写 `OTHER/UNVERIFIED`。
4. 对 `ENTRY_READY` 研究之后的状态持久性、进入 `WATCH_PULLBACK` 和 `TREND_DAMAGED` 的比例，区分 “正确等待” 和 “看起来不错但迅速失效”。**现有月度数据只能描述观察点之间状态变化，不可以当成每日连续状态转移概率**。
5. QQQ 是冻结 v1 基线，SPY/行业 ETF 对照只有在历史 bars 完整、同源且股票/QQQ/SPY 使用相同交集交易日时才能做主要比较；没有可靠历史 SPY 对照则写 `NOT RUN`，不自动替换基准。

输出 `entry_state_by_year_regime.csv`、`breakout_reason_cases.csv`、`entry_ready_deterioration.csv`、`entry_failure_cases.csv`（包含无效/缺失示例）。所有诊断都是 trailing 规则产生的决策和真实后续表现，不能把仅用过去价格算的 trailing excess 当未来收益。

## 7. H3 — Action/Attention 15 名排序研究（具体怎么做）

**预先冻结两个排序器，后看收益**；研究级别的 Python 脚本可放在工作目录的 `research/`，不得修改生产的 `src/ai_value_scanner/decision/action.py` / `integrated.py`。

- **Baseline V1**：完全复现 `decision/integrated.py::_priority_sort_key`，先 Action 类别 `PRIORITY_REVIEW / WATCH_PULLBACK / WATCH_BREAKOUT / HOLD_MONITOR / AVOID`，后 Quality A/B/C/UNRATED、Quality score 降序、Entry score 降序、Quality confidence 降序、Entry confidence 降序、ticker。按日期、symbol 去重，数据不够时不要称 parity PASS。
- **Candidate E-first（唯一事前登记的排序候选）**：**只在相同 Action 类别、相同 Quality 等级内部**交换 Quality score 和 Entry score 的排序先后；其余顺序和 15 cap 不变。不新加权重、不换 universe、不借助未来收益选择候选。
- 同一天对比 top-5/top-15：保留的 symbol、掉出的 symbol、被 cap 压下但仍属 PRIORITY_REVIEW 的 symbol、20/60/120d QQQ 超额及下跌风险、同一股票跨月排名变化。统一相同信号日期、同一可评价样本和相同标签成熟/成本口径；结果按日期等权 + 年/市场 regime 汇总。
- **B + ENTRY_READY 只作为独立 secondary queue 假设**，分别与 A+READY、B+其他 Entry 比较 Quality 风险和后续分布；不直接把 B 全部升到 `PRIORITY_REVIEW`。
- 当前回测行没有真正的过去一日 `StockDecision` 时，不可声称重现线上 `Daily/Weekly` 的 “previous-state change” 逻辑；标签写 `historical priority/cap proxy`。

输出 `ranking_paired_by_date.csv`（date、n eligible、v1/candidate top5/top15 symbols、重叠、遗漏、配对指标、有效样本数）、`ranking_diff_cases.csv`（所有交换入/出对象，或数量过大时确定性取样并说明）、`b_ready_cases.csv`。拒绝基于某一年的最高 120d 回报反复调 E-first。

## 8. H4 — 历史流动性（有数据才做，不反过来改变前置门槛）

以 `docs/liquidity_gate_research_protocol_20261011.md` 为口径，判断是否存在**相同 Alpaca IEX feed** 的历史日线，能在同一个当时 session 对齐 20 个完整且有效的交易日，并能区分 corporate-action、暂停交易、缺失/陈旧和 ticker 变动。

- 比较：某交易日 daily bar 的 `close × volume` **vs** 同 feed 最近 20 个有效 session 的均值；
- 与 scanner 当前 `snapshot dollar_volume` **单独列出**，绝不声称这三个值相同；
- 展示 sample count、按日期/规模/已核验业务组的分层及近 $2m 边界案例；
- 对已被前置 gate 排除、从未生成 `StockDecision` 的证券，不能填出 Quality/Entry 或编造 “恢复后的 alpha”；
- 若不存在可信的历史 snapshot vs bars 同日期配对、或缺少 IEX split/会话证据，**直接 H4 = INCONCLUSIVE**；无需为凑 GO 而发起昂贵的全市场 SIP 重抓。

输出 `liquidity_coverage.csv`、`liquidity_cases.csv`（如可行）和 `liquidity_limitations.md`。本研究**不会修改** 200 万美元前置 gate。

## 9. 跨实验统一的安全/统计验收规则

**每个方向都按相同模板报告**：

- 对应代码 SHA、原始数据 SHA256、config SHA、观测单位、交易日数量、股票数量、missing/unsupported 比例；
- 完整的 `n_total / n_valid / n_missing / n_dates / n_symbols`，旧 watchlist 近似的占比、前向标签成熟比例、不同年份/regime 分布；
- 按日期等权的效果、symbol/date concentration、尾部/最差日期及反例；若同一股票/相邻日期多次出现，不能把事件数当独立样本数；
- v1 和候选在**完全相同的有效观测**上配对；变更来源、计算价格源、漏损数据、时间窗口，都属于不同实验；
- 2023–2024 的探索集可以看结果并明确标成 exploratory；2025/2026Q1 的复核窗口只对**在看其结果前写定**的候选进行一次规定比较。由于历史研究已多次接触这些年，不宜给它们“首次未见的 OOS”标签；
- 任何不可确认的 SEC filings/fact restatement、split adjustment、ticker/security identity、退市处理和数据权限，独立列出局限；缺失不能设为 0；
- 对多重假设、样本小/集中、1–2 个巨额赢家支撑的效果，结论降级为 INCONCLUSIVE；
- 不要因为 H1–H4 中任一项“没提升”就强推策略 v2。**No change** 是合法且重要的结论。

## 10. Review evidence to submit（事前冻结，逐项核对）

**提交位置：** `evidence-observations` 分支（非 `main`，无需 evidence-only PR），使用**全新的目录**：

```text
runs/historical-selection-v1/<RUN_ID>/
  README.md                         # 简短摘要、逐文件索引、实际命令、UTC、run ID
  study_manifest.json               # code/config/input SHA；窗口、成本、feed、来源、资源
  data_inventory.csv                # 本地和 Modal 发现的历史资产以及复用理由
  coverage_and_integrity.md         # PIT、年份、缺失、标签成熟、退市、来源限制
  validation_and_tests.md           # exact-head CI URL 和本地 unittest 输出摘要
  quality_v1_cohorts.csv            # 现有 evaluator 的实际结果
  quality_v1_rank_ic.csv
  quality_v1_concentration.csv
  quality_v1_report.md
  entry_v1_cohorts.csv
  entry_v1_transitions.csv
  entry_v1_persistence.csv
  entry_v1_concentration.csv
  entry_v1_report.md
  action_v1_cohorts.csv
  action_v1_compactness.csv
  action_v1_concentration.csv
  action_v1_report.md
  quality_coverage.csv
  quality_failure_cases.csv
  entry_state_by_year_regime.csv
  breakout_reason_cases.csv
  entry_ready_deterioration.csv
  entry_failure_cases.csv
  ranking_paired_by_date.csv
  ranking_diff_cases.csv
  b_ready_cases.csv
  liquidity_coverage.csv            # 若 H4 无数据，改交 liquidity_limitations.md
  liquidity_cases.csv               # 同上
  liquidity_limitations.md
  research_review.md                # H1/H2/H3/H4 的解释、负面结果、GO 分维度判断
  candidate_policy.md               # 可改、不可改、需新证据、后续验证
  reviewer_notes.md                 # 人工审核案例和已知限制
  analysis_code_manifest.md         # 运行的研究脚本路径+SHA/版本/参数
  SHA256SUMS                        # 对提交的普通文件逐一校验
```

所有 CSV 都要有列名/单位/样本范围说明。若临时分析代码对结论至关重要，应将其以**独立、可审计的研究代码 PR**或其精确 Git SHA 提供，不能只提交 CSV 而完全无法复算。分析不必以修改生产模块为代价。

**不要提交**：全量多 GB 原始 PIT 数据、Alpaca/SEC/EdgarTools 原始缓存、未授权分发的逐日 bars、`.env`、API key、SEC user-agent 实值、私人 manual notes、Modal Volume/checkpoint 全树、未经脱敏的大日志、虚拟环境、ZIP。原始大数据留在本地/授权的 Modal Volume，用 `SHA256`、列 schema、行数、日期/股票覆盖、获取方法和可以重复的 run spec 指认。任何受 provider 条款限制的内容都不要上传。

### README / manifest 必写的六个事实

1. 数据究竟来自**旧 AI research universe、通用 US Core、手工研究**中的哪类；`membership PIT` 是真是近似；
2. **实际 code SHA、config SHA、每个原始 CSV SHA**（不要只写分支名）；
3. 最近一次完整的 **signal date** 和实际 **label_end**，哪些 120d 未成熟；
4. Modal 工作区为 `infi`、具体 `run_id`、成功/失败、1× 重型容器、使用资源与异常；
5. 生产 Quality/Entry/Action/IEX/流动性 gate 是否保持原样；
6. 人工编辑过哪些衍生文件、哪些只能部分复核，以及所有失败和负面结果。

### 生成哈希（在待提交目录内执行）

```bash
cd "path/to/evidence-observations/runs/historical-selection-v1/$RUN_ID"
find . -type f ! -name SHA256SUMS -print0 \
  | sort -z | xargs -0 -r sha256sum > SHA256SUMS
sha256sum -c SHA256SUMS
```

之后把新目录直接提交到 `evidence-observations`，**不要** force-push、删除、覆盖旧证据，也不要合并证据分支到 main。提交后提供浏览器目录链接和**完整 evidence commit SHA**供审核。

若有 H1–H4 的一个子研究无法完成，必须提交对应的缺失说明、覆盖率和未能执行的命令及错误分类；其余子研究仍可获得独立 GO。

## 11. 审核门槛与下一个 PR（这点特别重要）

我将分开判断：

| 维度 | GO 需要看到的最低事实 | 否则 |
| --- | --- | --- |
| Engineering / integrity | exact-head CI、哈希/复现、dataset_kind、PIT/未来日期检查、v1 完全不变 | NO-GO |
| Data provenance / scope | 真实 vs 近似 universe 明确，行情、财报、未来收益日期能解释；没有无来源的替换 | INCONCLUSIVE / NO-GO |
| Quality research | 等级/置信度/缺失可追溯，跨模型语义诚实，异常案例被审查 | INCONCLUSIVE |
| Entry research | Quality A/B 条件分层，状态转移/突破原因/负面案例、日期匹配 | INCONCLUSIVE |
| Action / attention research | v1 排序 parity、同日配对 top-k、cap omissions、B+READY 案例 | INCONCLUSIVE |
| Liquidity research | 同 feed、PIT 20-session、缺失/split 清楚，不把 daily bars 当 scanner snapshot | INCONCLUSIVE |
| v2 policy readiness | 候选冻结、组件归因、负面证据与独立验证计划明确 | NO-GO to production if absent |

**研究 GO ≠ 策略 GO ≠ 生产推广 GO。** 本 PR 的完成条件是研究合同和执行入口经静态 review + CI 验证。实验完成后，我会读 `evidence-observations` 的原始可浏览文件，给出逐维度判断；只有证据充分且跨组件归因清楚，才建议建立**一个 outcome-sized 的 Generalized Selection v2 候选 Policy PR**。暂不在本 PR 中修改生产策略。

## 12. 出现问题时的操作建议

- `git status` 非空、配置或 watchlist 冻结哈希对不上：**停**，不要用变更后的数据混跑。
- `data/watchlist_history` 缺失：先盘点原始 PIT 资产；只靠今天 watchlist 可以做 post-hoc 诊断，不可宣称真正历史候选池。
- Modal 提示 profile 错、Volume 未授权、密钥缺失：确认 **infi** workspace、授权和本地 `.env` 是否配置；**不要把密钥发给 reviewer**。
- 出现 `_SUCCESS` 却数据缺失或原始文件哈希不同：标记为错误，禁止据此评分。
- `unittest` 或评估脚本报错：先保存失败摘要、定位根因，不通过手改 CSV 绕过验证。
- 只拿到公司基本面无 QQQ/SPY 可靠历史 bars：可以做 Quality 正确性/适用性诊断，Entry 相对强弱与前瞻效果分别 INCONCLUSIVE。
- 所有探索结论均应写出**为何可能错**，以及需要何种新的跨行业 PIT / prospective 数据才能确认。

**关联文档：** `docs/mvp_v1_strategy_audit_20261011.md`、`docs/generalized_end_to_end_research_v0.md`、`docs/general_purpose_discovery_and_quality_v2_design.md`、`docs/research_evidence_workflow.md`、`docs/post_pr23_baseline_experiment.md`。
