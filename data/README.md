# 输入数据与观察池

本目录包含程序的候选池、人工输入和部分研究参考数据。ETF 成分用于发现候选公司。

| 路径 | 用途 |
| --- | --- |
| `ai_watchlist.csv`、`ai_smallcap_manual.csv` | AI 主题候选池及人工维护的小盘候选。 |
| `watchlist_history/` | 观察池历史快照，用于保留当时的候选池来源。 |
| `benchmarks/` | 基准成分等参考数据。 |
| `research/` | 研究所用的候选池、归因与数据质量资料。 |
| `theme_watchlist_*.csv`、`theme_cohorts.csv`、`theme_history/` | 各主题观察池、队列及历史记录。 |
| `venture_watchlist_*.csv`、`venture_universe.csv`、`venture_cohorts.csv` | Venture 研究使用的候选池和队列。 |
| `flow/` | 本地资金流研究数据。 |

目录中既有 Git 跟踪的输入，也有被忽略的本地历史和运行数据。配置及候选池刷新方式见[项目 README](../README.md)，研究方向和历史文档见 [docs 索引](../docs/README.md)。
