# 2026-11-06 修复、优化与专项验收

基线代码：`830702b73749c92be20f02a3463669f1b8e7dbd8`；实施在工作区，精确计算源码 SHA256 见各 evidence manifest。本页承接 [原审查](README.md)，原审查中的“未修复”描述为审查时状态。

## 交付范围

| 项目 | 实施与行为 | 验收依据 |
| --- | --- | --- |
| R01 负 EBITDA 杠杆 | 仅 EBITDA>0 计算正常杠杆比率；净负债为正且 EBITDA<=0 输出明确风险、不给杠杆正面证据，并阻止 Quality A | 六格矩阵、强公司反例、扫描/回放共享 accounting |
| R02 非有限值 | NaN/±Inf 在会计入口变成缺失；底层全缺失兼容评分为中性0.5，覆盖率为0，不再得到1.0 | 4种缺失输入的5维全排列1024例、非有限原始负债、合法财务独立金值 |
| R03 不完整价格窗口 | 保留坏数据所在位置；严格校验正数/有限价格和交易日缺口；不完整窗口不输出60日波动率；缺失/无效波动率使 Entry 为 INSUFFICIENT_DATA | 首/中/尾坏价、缺失交易日、scan/replay适配一致、v1/v2门禁 |
| 优化1 会计案例 | 非经常损益只调整一次；人工可算的 FCF、杠杆、利息覆盖、现金转化；复用税务/投资利得防御用例 | `test_review_20261106_repairs.py` + SEC/TTM专项 |
| 优化2 人工注意力 | 新增逐次/逐周复核统计、重复占位、升级后降级、截尾标记、真实耗时与拒绝原因日志接口；日报卡片显示状态变更，周报提示质量/估值/事件复核重点 | `review_selection_utility.py attention`、合成升级/降级/截尾案例 |
| 优化3 Entry增量 | 固定同日 Quality A/B 池，对比 Entry Ready 子集；20/60/120日、日期等权、年度/regime、集中度和按标签结束日选取非重叠区间；严格校验标签日期 | `review_selection_utility.py entry`、独立数值期望及标签错配用例 |
| 优化4 反方与集中度 | 详细报告置前展示GAAP与调整后盈利估值、固定市值下盈利±20%敏感性、事件日历未知状态和完整反方证据；名单展示sector/SIC行业暴露 | context在canonical builder中计算，renderer只格式化；Quality不随价格动量变化的回归用例 |

`review_context.py` 只计算研究解释，不改变 Quality/Entry/Action 映射。估值敏感性没有新增公平价格或收益预测。财报年龄仍是已有提示，新增报告明确说明它不能确认下一次业绩发布日期。ETF来源继续仅为候选发现背景；行业披露是共同业务风险提示，不冒充实际相关系数或组合仓位。

## 最终验收结果

- 全量 unittest：**1305项，全部通过**（30.247秒）；机器记录见 [acceptance.json](evidence/acceptance.json)。
- SEC/TTM/PIT **152项**、公司行动/价格 **65项**、缓存 **107项**、快照发布 **34项**，四组均通过。
- `git diff --check`通过；输入与源码SHA核对通过；紧凑证据附[SHA256SUMS](evidence/SHA256SUMS)。

## 四项专项验证

[专项机器记录](evidence/special_validation.json)列出完整测试模块、数量、结果和源码哈希。重跑：

```bash
.venv/bin/python docs/review_20261106/validate_special.py
```

1. **SEC / TTM / PIT**：累计现金流拆季、年度/Q4重建、扫描与回放适配、申报后修订可见性、capex tag、主体/股本和非经营利得防御。
2. **公司行动与历史价格**：正/反向拆股连续性、价格×成交量不变、原始价格×申报股数估值约定、跨拆股前向标签、缺失价格/交易日的两端适配一致。
3. **缓存失效**：旧计算版本拒绝命中；同accession原始facts变化、配置、ticker map、周期申报、pending与TTL边界及并发缓存写入。
4. **快照与发布**：数据适配→canonical决策→不可变快照→validator→latest指针→cron；渲染/替换失败注入、并发同日写入，以及并发指针不得倒退。

专项检查额外发现并修复：原快照临时目录仅包含PID，同进程并发会互删暂存树；latest指针日期检查与替换存在竞争窗口。现在每次写入使用独立暂存路径，latest发布在文件锁内重新检查日期并原子替换。测试验证一次成功发布、失败清理、旧指针保留与日期单调性。

专项结果是离线契约验证，加本地既有快照/解析缓存盘点；没有重新联网抽取全部SEC原始数据，也没有对所有公司会计事实作人工审计。交易日连续性使用现有NYSE日历；特殊休市等日历边界仍继承其覆盖范围。

## 当前输入触达与兼容性

- 只读盘点本地963份解析缓存，全部为v9；其中33份具有正净负债、非正EBITDA和旧负比率。该数字是本地缓存库存，不能等同于33只当前入选公司。
- 解析缓存升级到v10，旧结果下次刷新必须重新计算。没有删除原始SEC缓存；第一次刷新可能比缓存命中更慢。
- Quality与Entry的v1/v2策略标识升级为`2026-11-06`，防止修复前后计算混记为同一政策。已发布快照保持不可变；相同日/风格的旧版本快照复用会按现有版本检查拒绝混用。
- 新renderer revision为`mvp_report_renderer_2026-11-06b`；兼容无新增上下文的`2026-11-06a`精确渲染。明确识别既有`2026-10-18b`为历史版本，仅做结构/契约检查并告警；未知版本仍拒绝。
- 16份本地既有快照通过相应兼容性检查，都有历史版本警告，未宣称逐字节复验通过。

## 已实际运行的研究结果

[Entry对照](evidence/entry/README.md)使用既有冻结的25,025行、39个决策日期数据（2023年至2026Q1）。这段历史使用近似候选池，保留原数据的会计覆盖和标签修复边界；本次重算当前Quality/Entry，不重新抓取数据。前向回报口径（含成本与进出场）见其manifest的`input_contract`。这是回溯诊断，不能叫新OOS或因果入场优势。

当前Quality A/B共15,909行；其中Entry Ready子集的日期等权增量（20/60/120日）约为**-0.105/-0.717/-0.254个百分点**；非重叠样本为26/13/7个日期，增量约为-0.285/+0.003/-0.135个百分点。

完整冻结数据的20/60/120日分别有54/58/63行的股票与QQQ标签结束日不一致；这些行均未进入本次Quality A/B池，该池的标签错位为0。完整盘点见manifest中的`full_dataset_outcome_integrity`，合格池检查见`outcome_integrity`。查明标签函数会把远期重新出现的价格当作下一交易日，现已拒绝超过信号7个日历日的入场、超过持有窗口日历包络的退出，以及非有限/非正价格。旧冻结文件保留原样，不能把本次筛选后的对照外推成整份旧数据已修复。

详细年度、regime、非重叠结果和逐日期原始汇总见CSV；研究结果不自动调整生产阈值。相同Quality池中的Ready子集并未提供稳定的正向增量，不能仅凭Entry状态强就提高确信度。

[人工注意力统计](evidence/attention/README.md)使用13份production快照。按已观察快照顺序统计；首份快照的新/重复状态未知，不把缺失历史当作“首次发现”。“升级失效”表示随后5次观察内Action降级，不代表真实交易亏损；观察不足且未见降级的案例标为截尾。

当前没有人工复核日志，耗时与拒绝原因均留空；已提供CSV模板和验证入口，不虚构这些结果。

## 使用方法

输出必须指定新目录，防止覆盖此前研究证据；工具禁止向正式不可变快照目录写入。

```bash
.venv/bin/python scripts/review_selection_utility.py \
  --output outputs/review_next/attention \
  attention --snapshots outputs/decisions --style production

# 人工日志列：decision_date,symbol,review_status,review_minutes,rejection_reason
# review_status取reviewed/rejected/follow_up；rejected必须有原因。
.venv/bin/python scripts/review_selection_utility.py \
  --output outputs/review_next/attention_with_logs \
  attention --snapshots outputs/decisions --style production --reviews path/to/reviews.csv

.venv/bin/python scripts/review_selection_utility.py \
  --output outputs/review_next/entry \
  entry --dataset outputs/historical_selection_v1_20261011_03/repaired/entry_quality_dataset_risk_off.v3.csv

.venv/bin/python -m unittest discover -s tests
```

复核统计附输入哈希和源码哈希，不改写输入快照。`outputs/`中的工作产物与缓存继续不进入Git，本目录仅收录紧凑可浏览的验收证据。
