# 阶段失败与反例案例簿

固定取每条阶段边的最差/最好日期，属于事后解释，不用于选择新参数。阶段差异不是独立因果贡献。

| 阶段 | 类型 | 日期 | 配对差 | 父/子人数 | 主要移出名字与60d净收益 |
| --- | --- | --- | --- | --- | --- |
| eligible_all→quality_ab | worst | 2022-11-18 | -2.531pp | 614/358 | PRCH 115.23%, AI 92.61%, FSLY 84.94% |
| eligible_all→quality_ab | best | 2022-02-11 | +5.944pp | 631/355 | CVNA -74.10%, GDRX -72.24%, IONQ -70.08% |
| quality_ab→quality_ab_ready | worst | 2022-11-04 | -17.594pp | 366/15 | META 98.87%, AEHR 92.70%, ACLS 84.15% |
| quality_ab→quality_ab_ready | best | 2022-01-28 | +17.272pp | 353/12 | NBIS -58.52%, CRNC -53.67%, SHOP -51.76% |
| quality_ab_ready→priority_review | worst | 2022-08-12 | -23.854pp | 3/1 | BAH 13.80%, TMUS 2.30% |
| quality_ab_ready→priority_review | best | 2022-09-30 | +11.728pp | 4/2 | ALB -21.20%, CTS -6.35% |
| priority_review→priority_top15 | worst | 2022-01-14 | -4.688pp | 50/15 | CF 64.89%, CTVA 25.65%, GD 14.64% |
| priority_review→priority_top15 | best | 2022-02-25 | +2.939pp | 21/15 | CNXC -25.66%, ACIW -23.31%, TDG -14.41% |
| quality_ab→action_eligible_ab | worst | 2022-12-02 | -0.084pp | 358/357 | DRS 32.73% |
| quality_ab→action_eligible_ab | best | 2022-04-01 | +0.116pp | 365/363 | FA -39.75%, GXO -35.96% |
| action_eligible_ab→weekly_top15 | worst | 2022-05-06 | -15.377pp | 362/15 | AEHR 89.39%, ENPH 80.65%, PLAB 62.68% |
| action_eligible_ab→weekly_top15 | best | 2022-01-28 | +12.426pp | 353/15 | NBIS -58.52%, CRNC -53.67%, SHOP -51.76% |
| priority_top15→fixed_usage | worst | 2022-09-30 | -8.392pp | 2/2 | 无；可能仅改变权重 |
| priority_top15→fixed_usage | best | 2022-08-12 | +25.884pp | 1/1 | 无；可能仅改变权重 |

原始指标、状态、风险代码及数据as-of见同目录casebook.json。若完整日期不足而使用已知结果子样本，comparison_basis会明确标注；缺失仍留在阶段覆盖表中。
