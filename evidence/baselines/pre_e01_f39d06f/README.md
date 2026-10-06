# E01 基线 pre_e01_f39d06f

按照 docs/refactor_baseline_protocol.md 在干净的 main
（commit f39d06fe, PR #5 合并后）上捕获的 post-correctness / pre-E01 零漂移基线。

- 回放窗口 2023-01-01 → 2026-03-31（月度），冻结候选池 `pre_e01_f39d06f_ai_watchlist.csv`
  （实际文件名为 pre_e01_f39d06f_ai_watchlist.csv）与冻结快照目录
  `pre_e01_f39d06f_watchlist_history/`；
- risk_off / risk_on 两次历史回放均无 latest-watchlist fallback；
- tuner smoke：walk_forward，folds [2023]→2024、[2023+2024]→2025，训练使用
  label-end purge，未晋级，生产配置未修改；
- 完整清单、输入/输出哈希与实验契约见 pre_e01_f39d06f_manifest.json。

E1 迁移 PR 的验收方式：使用本目录中的冻结输入（不要重新复制 data/ 下的动态文件）、
相同窗口与参数重跑同一实验，然后运行 scripts/refactor_baseline.py compare，
输出 BASELINE_MATCH 才可合并。详见 docs/refactor_baseline_protocol.md 第 9 节。
