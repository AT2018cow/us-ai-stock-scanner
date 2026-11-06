# 阶段失败与反例案例簿

固定取每条阶段边的最差/最好日期，属于事后解释，不用于选择新参数。阶段差异不是独立因果贡献。

| 阶段 | 类型 | 日期 | 配对差 | 父/子人数 | 主要移出名字与60d净收益 |
| --- | --- | --- | --- | --- | --- |
| eligible_all→quality_ab | worst | 2025-07-31 | -5.604pp | 524/347 | SNDK 345.14%, IREN 311.48%, CIFR 309.21% |
| eligible_all→quality_ab | best | 2021-10-29 | +3.913pp | 391/246 | MQ -65.77%, ASAN -65.54%, HOOD -65.03% |
| quality_ab→quality_ab_ready | worst | 2022-09-30 | -29.090pp | 256/1 | FICO 47.44%, CAT 45.30%, SLB 41.99% |
| quality_ab→quality_ab_ready | best | 2025-12-31 | +6.099pp | 308/64 | MNDY -54.74%, DOCS -47.28%, DUOL -46.98% |
| quality_ab_ready→priority_review | worst | 2026-05-29 | -11.935pp | 5/2 | VRSN 1.43%, EBAY -3.55%, CAT -5.90% |
| quality_ab_ready→priority_review | best | 2021-09-30 | +5.836pp | 6/5 | FSLR -9.03% |
| priority_review→priority_top15 | worst | 2025-12-31 | -5.079pp | 49/15 | DOCN 60.48%, WDC 41.61%, DVN 40.19% |
| priority_review→priority_top15 | best | 2026-01-30 | +6.586pp | 29/15 | CBRE -13.75%, ILMN -11.68%, EXPD -9.24% |
| quality_ab→action_eligible_ab | worst | 2021-11-30 | -5.474pp | 270/103 | MOS 39.71%, SLB 33.02%, FICO 32.26% |
| quality_ab→action_eligible_ab | best | 2022-11-30 | +2.319pp | 272/102 | LUMN -38.28%, NRG -24.26%, DVN -22.73% |
| action_eligible_ab→weekly_top15 | worst | 2026-05-29 | -17.373pp | 401/15 | MGNI 64.89%, PAYC 63.60%, QLYS 56.80% |
| action_eligible_ab→weekly_top15 | best | 2026-01-30 | +9.934pp | 375/15 | EPAM -45.45%, VISN -44.74%, MNDY -41.80% |
| priority_top15→fixed_usage | worst | 2021-09-30 | -17.324pp | 5/5 | 无；可能仅改变权重 |
| priority_top15→fixed_usage | best | 2022-03-31 | +21.735pp | 1/1 | 无；可能仅改变权重 |

原始指标、状态、风险代码及数据as-of见同目录casebook.json。若完整日期不足而使用已知结果子样本，comparison_basis会明确标注；缺失仍留在阶段覆盖表中。
