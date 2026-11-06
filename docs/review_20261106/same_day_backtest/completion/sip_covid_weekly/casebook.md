# 阶段失败与反例案例簿

固定取每条阶段边的最差/最好日期，属于事后解释，不用于选择新参数。阶段差异不是独立因果贡献。

| 阶段 | 类型 | 日期 | 配对差 | 父/子人数 | 主要移出名字与60d净收益 |
| --- | --- | --- | --- | --- | --- |
| eligible_all→quality_ab | worst | 2020-04-03 | -7.657pp | 503/330 | FSLY 315.17%, BILL 177.35%, TWLO 160.91% |
| eligible_all→quality_ab | best | 2020-06-19 | -0.078pp | 532/322 | PPLI -57.67%, SGRX -54.82%, VERI -53.95% |
| quality_ab→quality_ab_ready | worst | 2020-04-17 | -29.438pp | 330/1 | TRGP 143.22%, XYZ 103.67%, TTD 92.37% |
| quality_ab→quality_ab_ready | best | 2020-02-28 | +8.570pp | 330/18 | UAL -51.99%, RTX -51.27%, ATI -50.62% |
| quality_ab_ready→priority_review | worst | 2020-05-22 | -4.464pp | 2/1 | EQIX 15.23% |
| quality_ab_ready→priority_review | best | 2020-04-09 | +13.433pp | 6/2 | WEC -8.67%, AEE -6.20%, XEL -3.30% |
| priority_review→priority_top15 | worst | 2020-02-28 | +0.000pp | 13/13 | 无；可能仅改变权重 |
| priority_review→priority_top15 | best | 2020-02-21 | +4.733pp | 35/15 | MSI -25.79%, OMCL -24.01%, ETN -23.32% |
| quality_ab→action_eligible_ab | worst | 2020-05-15 | -0.129pp | 325/324 | HWM 61.47% |
| quality_ab→action_eligible_ab | best | 2020-06-05 | +0.022pp | 318/317 | HWM -3.07% |
| action_eligible_ab→weekly_top15 | worst | 2020-04-17 | -7.867pp | 329/15 | TRGP 143.22%, XYZ 103.67%, TTD 92.37% |
| action_eligible_ab→weekly_top15 | best | 2020-02-21 | +9.654pp | 317/15 | SABR -68.82%, UAL -68.16%, AAL -62.31% |
| priority_top15→fixed_usage | worst | 2020-03-27 | -20.629pp | 2/2 | 无；可能仅改变权重 |
| priority_top15→fixed_usage | best | 2020-02-07 | +0.000pp | 15/15 | 无；可能仅改变权重 |

原始指标、状态、风险代码及数据as-of见同目录casebook.json。若完整日期不足而使用已知结果子样本，comparison_basis会明确标注；缺失仍留在阶段覆盖表中。
