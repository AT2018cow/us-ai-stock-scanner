# 阶段失败与反例案例簿

固定取每条阶段边的最差/最好日期，属于事后解释，不用于选择新参数。阶段差异不是独立因果贡献。

| 阶段 | 类型 | 日期 | 配对差 | 父/子人数 | 主要移出名字与60d净收益 |
| --- | --- | --- | --- | --- | --- |
| eligible_all→quality_ab | worst | 2020-10-30 | -13.466pp | 535/308 | MARA 836.02%, DDD 553.57%, RIOT 511.05% |
| eligible_all→quality_ab | best | 2021-10-29 | +7.595pp | 635/346 | BKSY -70.94%, CLSK -70.36%, DRK -69.39% |
| quality_ab→quality_ab_ready | worst | 2018-12-31 | -14.660pp | 305/5 | ENPH 95.81%, LSCC 70.84%, OLED 66.85% |
| quality_ab→quality_ab_ready | best | 2022-01-31 | +14.674pp | 357/19 | NBIS -61.55%, SHOP -58.02%, NFLX -56.75% |
| quality_ab_ready→priority_review | worst | 2026-05-29 | -16.360pp | 6/2 | OOMA 14.22%, VRSN 2.37%, EBAY -3.86% |
| quality_ab_ready→priority_review | best | 2022-09-30 | +11.728pp | 4/2 | ALB -21.20%, CTS -6.35% |
| priority_review→priority_top15 | worst | 2018-03-29 | -8.620pp | 56/15 | ONTO 37.43%, QLYS 19.43%, VPG 18.56% |
| priority_review→priority_top15 | best | 2019-08-30 | +6.915pp | 68/15 | EXPE -24.03%, ECL -11.48%, EBAY -10.79% |
| quality_ab→action_eligible_ab | worst | 2019-01-31 | -0.378pp | 306/304 | PAYS 102.36%, RAMP 36.02% |
| quality_ab→action_eligible_ab | best | 2021-09-30 | +0.230pp | 343/341 | PLTK -35.93%, CGNT -24.30% |
| action_eligible_ab→weekly_top15 | worst | 2026-05-29 | -15.673pp | 457/15 | PAYS 92.87%, MGNI 66.41%, PRCH 65.73% |
| action_eligible_ab→weekly_top15 | best | 2022-01-31 | +13.172pp | 357/15 | NBIS -61.55%, SHOP -58.02%, NFLX -56.75% |
| priority_top15→fixed_usage | worst | 2020-03-31 | -20.789pp | 3/3 | 无；可能仅改变权重 |
| priority_top15→fixed_usage | best | 2026-05-29 | +19.806pp | 2/2 | 无；可能仅改变权重 |

原始指标、状态、风险代码及数据as-of见同目录casebook.json。若完整日期不足而使用已知结果子样本，comparison_basis会明确标注；缺失仍留在阶段覆盖表中。
