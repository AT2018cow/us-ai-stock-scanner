# E01 基线 pre_e01_f39d06f

按照 `docs/refactor_baseline_protocol.md` 在干净的 `main`
（commit `f39d06fe`, PR #5 合并后）上捕获的 post-correctness / pre-E01 零漂移基线。

- 回放窗口：2023-01-01 → 2026-03-31，monthly；
- 冻结候选池：`pre_e01_f39d06f_ai_watchlist.csv`；
- 冻结快照目录：`pre_e01_f39d06f_watchlist_history/`（32 个 snapshot）；
- risk_off / risk_on 两次历史回放均无 latest-watchlist fallback；
- tuner smoke：`walk_forward`，folds `[2023]→2024`、`[2023+2024]→2025`，训练使用 label-end purge，未晋级，生产配置未修改；
- 完整输入/输出 hash、summary/signal contract、network provenance 与 tuner folds 见 `pre_e01_f39d06f_manifest.json`。

## 后续 E01 使用方式

本目录现在是 canonical baseline input/evidence。**不要重新复制 `data/` 下的动态 watchlist。**

从仓库根目录定义：

```bash
BASE_DIR="evidence/baselines/pre_e01_f39d06f"
BASE_MANIFEST="$BASE_DIR/pre_e01_f39d06f_manifest.json"
WATCHLIST="$BASE_DIR/pre_e01_f39d06f_ai_watchlist.csv"
HIST="$BASE_DIR/pre_e01_f39d06f_watchlist_history"
NEW="e01_config_$(git rev-parse --short HEAD)"
```

按 `docs/refactor_baseline_protocol.md` 第 4–6 节重跑 risk_off、risk_on 和 tuner smoke，只把 output prefix 换成 `$NEW`，并始终传：

```text
--watchlist-csv-path "$WATCHLIST"
--watchlist-history-dir "$HIST"
```

然后比较：

```bash
.venv/bin/python scripts/refactor_baseline.py compare \
  --baseline "$BASE_MANIFEST" \
  --risk-off-prefix "${NEW}_risk_off" \
  --risk-on-prefix "${NEW}_risk_on" \
  --tuning-prefix "${NEW}_tuner_risk_off" \
  --watchlist "$WATCHLIST" \
  --watchlist-history-dir "$HIST" \
  --replay-start 2023-01-01 \
  --replay-end 2026-03-31 \
  --rebalance-frequency monthly
```

成功结果必须是：

```text
BASELINE_MATCH
```

baseline manifest 保留了最初 capture 时的 `outputs/...` 路径作为 provenance；比较时**路径位置本身不属于语义 identity**。输入身份由 watchlist/watchlist-history/config/param-space 的 SHA256 保证，因此把同一冻结文件从 `outputs/` 移到本 evidence 目录不会产生假 mismatch。

## 归档完整性说明

原实验的 manifest 将每种风格下列 7 类 CSV 都纳入 deterministic hash gate：

- `events_signals`
- `events`
- `summary`
- `benchmarks`
- `segments`
- `events_signal_diagnostics`
- `events_signal_channel_summary`

当前仓库 evidence 已归档 `events / summary / benchmarks`，但原始提交时没有一并保存以下 8 个 diagnostic CSV：

```text
pre_e01_f39d06f_risk_off_events_signals.csv
pre_e01_f39d06f_risk_off_segments.csv
pre_e01_f39d06f_risk_off_events_signal_diagnostics.csv
pre_e01_f39d06f_risk_off_events_signal_channel_summary.csv
pre_e01_f39d06f_risk_on_events_signals.csv
pre_e01_f39d06f_risk_on_segments.csv
pre_e01_f39d06f_risk_on_events_signal_diagnostics.csv
pre_e01_f39d06f_risk_on_events_signal_channel_summary.csv
```

这**不影响 baseline gate**：它们的 SHA256、signal contract 和 shape 已冻结在 manifest 中，后续重跑仍会被严格比较。影响仅在 mismatch 后的人工诊断——当前无法直接打开旧版这 8 个文件做逐行 diff。

如果原始本地 outputs 仍存在，可以以后补归档，但只有在每个文件 SHA256 与 manifest 的对应 `deterministic_sha256` 完全一致时才能加入；不要重新生成文件冒充原始 evidence。

## 数据漂移警告（2026-10-06 首次 E1 对比实验发现）

SEC EDGAR 是活数据：2026-10-06 10:00 UTC 的落盘使 661 家公司 facts 被重取
（GOOGL 新申报 accession 0001193125-26-412669 处于 pending 状态），其 per-date
特征随之变化，导致 risk_on 选股集合翻转（301/468 行差异中 288 行涉及 GOOGL）。
因此**跨天比较全窗口确定性哈希必然 mismatch，且不能归因于代码变更**。

判定代码等价的方法（本次已验证）：
1. 同一数据状态下新旧代码背靠背运行，events CSV 必须逐字节一致（已通过：
   短窗口 risk_on eqtest 新旧代码完全一致）；
2. risk_off 全窗口在新旧代码+跨落盘窗口下汇总完全一致（辅助证据）。

后续 E1 迁移 PR 应在**同一数据窗口内**完成新旧代码的背靠背对比，而不是与
基线 manifest 跨天比对哈希；manifest 比较仅用于验证输入契约未变。

## PR #10 gate 记录（2026-10-07）

按"同数据状态背靠背"方法验证 PR #10（base 4c68a4c vs head a15d7e2，共享缓存、
相同冻结输入与参数，全标准窗口双风格 + 6 个月特征矩阵对比，各约 5300 行 × 91 列）：

- 市场数据 10 列、benchmarks.csv（双风格）、watchlist_etf_count：逐字节一致
- 全部差异归因于 PR #10 声明的 intentional changes：#1 年报回退（OCF None→value
  4688 行，AAPL/IBM 抽查为正确值）、#2 修正案 PIT（调整项变化 2059 行）、
  #3 真实年度同比（level YoY 约 1600 行变化 + 170 行转 None）、#5 缺失申报来源
  保守处理（value→None）
- 因果链闭环：pe 100% ← adjusted_NI ← 99.8% 调整项；ai_link 100% ← backlog ←
  revenue；survivor 翻转（AAL 出 / ADP 入）← OCF 可得性
- 无未解释差异；summary 偏移方向不一致（avg_return 均值 -0.04pp / -0.07pp），
  属数据修正而非系统性偏差
- 结构化 gate 记录：`evidence/gates/pr10_same_data_state_20261007.json`
- 原始证据文件：`outputs/gate10_{base,pr10}_{risk_off,risk_on}_*`（仅本地保留，未归档/未记录 SHA256；此限制已在 gate manifest 中显式标注）

## PR #12 gate 记录（2026-10-08）

方法：复制缓存到 /tmp/frozen_cache 并将全部 680 个 facts_meta 标记为 covered
（跳过 D02 pending refetch），base 72c437 vs head df4a9c6 顺序执行、共享冻结缓存。

- 特征矩阵提取（6 个月，~5374 行 × 113 列）：**逐字节一致** (f8dabfe03b13)
- 全量回放 events/benchmarks/summary/events_signals：**全部逐字节一致**
- rank_and_pick_symbols_with_diagnostics 全部 624 次调用：**输出逐字节一致** (f44860c47128e4abb0a68a5229d05ede)
- score_and_rank 全部 1404 次调用：**输出逐字节一致**
- 结论：**零漂移，PR #12 为纯行为无关重构**

### 重要教训：D02 pending 与并发运行

D02 pending 机制使每次运行重取 ~661 个 facts。当多进程并发运行时，各进程
在缓存处于不同状态时读取数据，导致结果不可复现（如 SNOW/PSX 出现在一侧）。
**解决方法**：在 gate 运行前复制缓存并将全部 facts_meta 标记为 covered，
使所有进程读取同一冻结状态。此方法已记录为标准 gate 流程。

## PR #13 gate 记录（2026-10-08）

方法：PR #12 冻结缓存流程，base ae0d481 vs head e309430，顺序执行。

- 特征矩阵：base 5374行 vs pr13 5339行（-35行 = SMA200 修正效果）
- 差异1 SMA200修正：19个近期上市股票从base消失（APH/NBIS/FAST等），
  共同行 price_to_sma200/days_below_sma200 零差异（0 val_diff）
- 差异2 日历天窗口：drawdown 2772行值变化（max=0.593），
  range 3451行值变化（max=0.706）
- 下游效应（因果链闭合）：peer_median 99行、soft_pass_count 435行、
  回放选择19行/25符号
- 无未解释差异 → **合并**

## PR #14 gate 记录（2025-11-06）

方法：PR #12 冻结缓存流程，base 8cae14e vs head 1e5b736，顺序执行。

- 提取（6个月，5339行×113列）：逐字节一致 (ee60aea9ec5b)
- 回放 events/benchmarks/summary/events_signals：全部逐字节一致
- 结论：**零漂移，PR #14 为纯行为无关重构**
