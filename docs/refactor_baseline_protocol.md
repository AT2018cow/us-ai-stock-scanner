# E01 重构前基线实验协议

状态：PR #5A 工具协议。目的不是重新调参或证明策略有效，而是冻结 **post-correctness / pre-E01** 的当前行为，供后续纯模块迁移逐项对照。

## 1. 基线原则

这轮实验必须满足：

- 从 PR #5A 合并后的干净 `main` 运行；
- 不修改 `configs/config.risk_off.json` / `configs/config.risk_on.json`；
- 不使用 `--promote`；
- 不使用 `--allow-latest-watchlist-fallback`；
- 不重建历史 ETF 成分；
- risk_off / risk_on 两次 backtest 之间不要刷新 watchlist；
- 固定历史窗口和固定输出前缀；
- baseline capture 前工作树必须 clean；
- `outputs/` 仍是 gitignored，本次 manifest/CSV 作为本地重构证据保存即可。

**不要用 `scripts/phase4_validation.py` 代替本协议。** 该脚本当前硬编码
`allow_latest_watchlist_fallback=True`，其定位是旧 Phase-4 体系级研究工具，不适合作为 E01 的零漂移基线。

## 2. 环境准备

在仓库根目录：

```bash
git checkout main
git pull --ff-only

.venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests

git status --short
git rev-parse HEAD
```

`git status --short` 应为空。记录实际 HEAD；baseline manifest 会再次自动记录 commit。

环境仍需要正常的 `.env`：

- `ALPACA_API_ENDPOINT`
- `ALPACA_API_KEY`
- `ALPACA_API_SECRET`
- `SEC_USER_AGENT`

## 3. 定义固定 baseline ID

建议：

```bash
BASE="pre_e01_$(git rev-parse --short HEAD)"
WATCHLIST="outputs/${BASE}_ai_watchlist.csv"
HIST="outputs/${BASE}_watchlist_history"

mkdir -p outputs
cp data/ai_watchlist.csv "$WATCHLIST"
rm -rf "$HIST"
mkdir -p "$HIST"
cp data/watchlist_history/*.csv "$HIST"/
```

后面的命令都使用同一个 `$BASE`、冻结后的 `$WATCHLIST` 和 `$HIST`。

为什么两个都要冻结：

- `data/ai_watchlist.csv` 是 fixed-current candidate pool，本身会随日常刷新变化；
- `pre_snapshot_universe=union` 会把快照历史中见过的股票加入 replay pool。未来新增快照可能扩大这个 union。

如果继续读取动态输入，即使代码完全没变，重构后重跑也可能产生不同 universe。baseline/refactor 对比必须始终使用这两份冻结副本。

## 4. risk_off 固定历史回放

窗口固定为 **2023-01-01 → 2026-03-31**。选择这个截止日是为了在
2026-10-06 时让 120 个交易日标签已经成熟，避免以后因“又多了未来行情”而改变基线。

```bash
.venv/bin/python run_backtest.py \
  --mode historical_replay \
  --scan-config configs/config.risk_off.json \
  --outputs-dir outputs \
  --output-prefix "${BASE}_risk_off" \
  --list-types low_value,industry_trend,momentum,research_pool \
  --horizons 20,60,120 \
  --start-date 2023-01-01 \
  --end-date 2026-03-31 \
  --rebalance-frequency monthly \
  --watchlist-csv-path "$WATCHLIST" \
  --watchlist-history-dir "$HIST" \
  --theme-source rules_proxy \
  --pre-snapshot-universe union
```

**不要添加** `--allow-latest-watchlist-fallback`。

## 5. risk_on 固定历史回放

```bash
.venv/bin/python run_backtest.py \
  --mode historical_replay \
  --scan-config configs/config.risk_on.json \
  --outputs-dir outputs \
  --output-prefix "${BASE}_risk_on" \
  --list-types low_value,industry_trend,momentum,research_pool \
  --horizons 20,60,120 \
  --start-date 2023-01-01 \
  --end-date 2026-03-31 \
  --rebalance-frequency monthly \
  --theme-source rules_proxy \
  --pre-snapshot-universe union
```

两次 backtest 之间不要刷新 `data/ai_watchlist.csv`。

## 6. anchored walk-forward tuner smoke

这一步只验证 PR #2 后的 OOS 选择路径真实跑通，**不是重新发现生产参数**。

使用 risk_off、固定三个完整年度、固定 seed、4 个候选、monthly rebalance，并关闭 perturbation 以降低成本：

```bash
.venv/bin/python scripts/tune_parameters.py \
  --base-config configs/config.risk_off.json \
  --param-space configs/tuner.param_space.json \
  --outputs-dir outputs \
  --output-prefix "${BASE}_tuner_risk_off" \
  --windows "2023:2023-01-01:2023-12-31,2024:2024-01-01:2024-12-31,2025:2025-01-01:2025-12-31" \
  --selection-mode walk_forward \
  --search-mode random \
  --max-candidates 4 \
  --random-seed 42 \
  --rebalance-frequency monthly \
  --watchlist-csv-path "$WATCHLIST" \
  --watchlist-history-dir "$HIST" \
  --no-perturbation \
  --no-promote
```

验收重点是：

- summary 中 `selection_mode=walk_forward`；
- folds 为 `2023 → 2024`、`2023+2024 → 2025`；
- training 仍执行 label-end purge；
- 没有生产配置被改写。

baseline tuner smoke 建议使用默认本地 executor。冻结的 `$HIST` 是本地输入；不要在同一 baseline 中临时切换 executor 或 snapshot 来源。

## 7. 捕获 baseline manifest

三组产物完成后：

```bash
.venv/bin/python scripts/refactor_baseline.py capture \
  --baseline-id "$BASE" \
  --risk-off-prefix "${BASE}_risk_off" \
  --risk-on-prefix "${BASE}_risk_on" \
  --tuning-prefix "${BASE}_tuner_risk_off" \
  --watchlist "$WATCHLIST" \
  --watchlist-history-dir "$HIST" \
  --replay-start 2023-01-01 \
  --replay-end 2026-03-31 \
  --rebalance-frequency monthly \
  --output "outputs/${BASE}_manifest.json"
```

capture 会 fail-fast：

- 工作树 dirty；
- 任一必要 backtest CSV 缺失；
- tuner `results/summary` 缺失；
- watchlist/config/param-space 不存在。

manifest 包含：

- git commit / branch / dirty 状态；
- risk_on / risk_off config SHA256；
- tuner param-space SHA256；
- watchlist SHA256、symbol-set SHA256、行数；
- 冻结 watchlist-history 目录的文件清单与目录 SHA256；
- backtest deterministic CSV SHA256；
- canonical summary metrics；
- signal date/list/scenario contract；
- events / segments shape；
- network/cache provenance（记录但不作为 deterministic file hash gate）；
- tuner picks / walk-forward folds / results SHA256。

## 8. 人工检查

建议至少打开：

```text
outputs/${BASE}_risk_off_report.md
outputs/${BASE}_risk_on_report.md
outputs/${BASE}_risk_off_report_network.json
outputs/${BASE}_risk_on_report_network.json
outputs/${BASE}_tuner_risk_off_report.md
outputs/${BASE}_manifest.json
```

检查：

1. risk_on / risk_off 都是正确的 `strategy_style`；
2. `watchlist_source` 没有 latest-watchlist fallback，且 report 中的 watchlist path 指向冻结的 `$WATCHLIST`；
3. network provenance 中如果使用 stale fallback，原因和 data-asof 有记录；
4. tuner 没有 promote；
5. manifest 的 `git.commit` 是本次 PR #5A 合并后的 `main`；
6. `git diff -- configs/config.risk_off.json configs/config.risk_on.json` 为空。

## 9. E01 后如何比较

每个纯结构迁移 PR 完成后，使用**相同输入、相同窗口、相同参数**重新生成一组不同前缀的产物，例如：

```bash
NEW="e01_config_$(git rev-parse --short HEAD)"
```

运行与第 4–6 节相同的实验，只把 output prefix 换成 `$NEW`，并且继续使用原 baseline 的 `$WATCHLIST` / `$HIST`，不要重新复制当前 `data/ai_watchlist.csv` 或 `data/watchlist_history/`。然后：

```bash
.venv/bin/python scripts/refactor_baseline.py compare \
  --baseline "outputs/${BASE}_manifest.json" \
  --risk-off-prefix "${NEW}_risk_off" \
  --risk-on-prefix "${NEW}_risk_on" \
  --tuning-prefix "${NEW}_tuner_risk_off" \
  --watchlist "$WATCHLIST" \
  --watchlist-history-dir "$HIST" \
  --replay-start 2023-01-01 \
  --replay-end 2026-03-31 \
  --rebalance-frequency monthly
```

成功输出：

```text
BASELINE_MATCH
```

即表示以下部分完全一致：

- 输入 config / watchlist / param-space hash；
- deterministic backtest CSV；
- canonical summary；
- signal contract；
- tuner results / picks / walk-forward folds。

报告 Markdown 和 network JSON 带有运行时 provenance/timestamp，因此保存用于人工审查，但不要求整个文件 byte-for-byte 相同。

任何 `BASELINE_MISMATCH` 都应先解释，再合并机械重构 PR；不要为了让比较通过而更新 baseline。只有明确批准的行为变化才能建立新 baseline。
