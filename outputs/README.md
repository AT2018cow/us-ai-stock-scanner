# 输出目录

本目录保存扫描、报告和研究运行产生的本地文件。各子目录可能随运行增加。目录说明由 Git 管理，生成的数据和报告保留在本地。

| 路径 | 用途 |
| --- | --- |
| [reports/](reports/README.md) | 离线阅读首页、各期日报、周报和个股详报。日常从 `reports/index.html` 进入。 |
| [decisions/](decisions/README.md) | 按交易日和策略风格保存正式决策快照、最新指针及发布回执，是报告来源和复核依据。 |
| [scans/](scans/README.md) | 按月份归档的原始扫描 CSV、Markdown 和诊断输出。 |
| `ai_value_scan_*` | 尚在根目录的扫描输出。文件名中的时间为 UTC，一次扫描通常对应多个文件。 |
| `decision_samples/` | 限制扫描数量的样本决策快照。 |
| `intraday/`、`preview_intraday_*/` | 盘中监控留痕与临时预览，按运行时使用的 IEX 数据和时间阅读。 |
| `decision_previews/`、`decision_experiments/` | 历史预览和实验快照，其中部分文件被研究脚本和文档引用。 |
| `review_20261106/`、`review_followup_20261106/`、`sip_eod_migration/` | 选股审查、修复复核与 SIP 迁移相关的冻结数据、评估和运行记录。 |
| `historical_selection_*/`、`m4_revalidation_*/`、`mvp_v11_*/`、`posthoc_62*/` | 历史选股及策略验证的工作数据和结果。 |
| `swing_historical_bounded_20261125/` | 中短线有界历史比较的输入、路径结果和核验材料，解读见[研究报告](../docs/swing_historical_bounded_20261125/README.md)。 |
| `_archive_pre_mvp_202610/`、`_archive_superseded_20261019/` | 较早运行和被替代结果的本地归档。 |

研究材料的解释、样本边界和复现入口见 [docs 索引](../docs/README.md)，部分原始数据由其中的脚本按具体路径读取。请根据对应研究文档核对依赖后再移动文件。

执行和归档规则见[项目目录说明](../README.md#81-目录约定与每月整理)。
