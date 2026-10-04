# 项目设计、逻辑与计算审查记录（2026-10-03）

## 1. 范围、结论与证据边界

审查基线：`674c7cbde3612d960cdb39b3d80c76246b16686a`。本文汇总本次会话中发现的计算错误、逻辑问题、设计缺口及优化建议，并补充记录核查中发现的文档与运行状态问题。所有项目均为待处理记录，本文的创建不代表代码已修复。

检查范围：`src/ai_value_scanner/scanner.py`、`backtest.py`，调参与权重扫描脚本、双风格和多主题观察、每日运行、交易计划、配置、相关测试及协议文档。

总体判断：研究筛选方向合理，已有较好的财务重建、诊断和离线测试基础；扫描／回测的特征口径、策略评价与账户执行之间仍有缺口。修正基础计算与评价口径，应优先于增加主题或继续优化参数。

审查期间已运行 `.venv/bin/python -m unittest discover -s tests`，202 项测试全部通过。另使用合成数据、现有测试 fixture 和模拟缓存复现若干错误。没有调用真实行情／SEC 接口，没有运行完整历史重放或执行交易，尚未量化实际公司、历史输出和历史收益受影响的范围。

证据等级：

- **已复现**：通过离线调用当前函数得到具体错误结果。
- **代码确认**：代码路径存在明确口径差异或缺失；触发条件可说明，但尚未重跑实际业务数据。
- **设计缺口**：工具实现没有覆盖协议或评价所要求的行为，不等同于每次运行都会出错。
- **待验证风险**：机制存在局限，影响方向／程度需要进一步实证，不能作为已证实的收益损失。
- **工程优化／文档问题**：提高可维护性、可追溯性或消除语义歧义。

优先级：P0 为基础数据、计算或评价可信度的前置修复；P1 为账户执行、运行依赖及评价闭环；P2 为后续维护和研究优化。优先级表示建议处理顺序，不是实测损失大小。

## 2. 问题总表

| ID | 问题 | 证据等级 | 优先级 |
|---|---|---|---|
| C01 | 调整后 EBITDA 重复计入非经常性损益 | 已复现 | P0 |
| C02 | 回测同比使用相邻披露值而非约一年前数据 | 已复现 | P0 |
| C03 | 最大回撤遗漏初始净值 | 已复现 | P0 |
| C04 | PIT 存量序列可能选中同份申报中的旧报告期 | 已复现 | P0 |
| C05 | 回测没有执行扫描的非经常性利润调整 | 代码确认 | P0 |
| C06 | 回测主题关联度仍使用硬编码权重 | 代码确认 | P0 |
| D01 | 派生财务缓存未绑定计算配置和原始数据版本 | 已复现／代码确认 | P0 |
| D02 | SEC facts 日期比较可能漏掉同日新申报 | 已复现 | P0 |
| D03 | 行情陈旧缓存缺少统一的新鲜度与降级标记 | 代码确认／设计缺口 | P1 |
| R01 | union 早期回放使用未来 ETF 共识及通道元数据 | 代码确认 | P0 |
| R02 | 历史股票池残余幸存者偏差及当前元数据近似 | 待验证风险 | P1 |
| R03 | 多窗口历史选参未形成完整的样本外 walk-forward | 设计缺口 | P0 |
| R04 | 权重训练／验证边界没有清除前向收益重叠 | 代码确认 | P0 |
| R05 | 重叠事件收益复利不能代表账户最大回撤 | 代码确认／设计缺口 | P0 |
| L01 | 单次计划预算与滚动 cohort 账户预算脱节 | 设计缺口 | P1 |
| L02 | 选股事件回测没有复现交易计划的组合规则 | 设计缺口 | P1 |
| L03 | 上游失败后每日流程仍生成计划并打印操作指导 | 代码确认 | P1 |
| L04 | 双风格报告配对没有批次一致性和新鲜度约束 | 代码确认 | P1 |
| L05 | 分级、验证历史及账户风险状态尚未机器化闭环 | 设计缺口 | P1 |
| T01 | 主题／venture 纸面结算没有拆股修正 | 代码确认 | P0 |
| T02 | 主题结算缺少基准超额、成本和缺价状态评价 | 设计缺口 | P1 |
| T03 | 日常归档与月度／周度 cohort 协议口径不统一 | 代码确认／设计缺口 | P1 |
| T04 | 新主题继承 AI 研究标签、阈值和市场熔断假设 | 待验证风险 | P2 |
| T05 | 主题子扫描失败未汇总为非零退出状态 | 代码确认 | P1 |
| E01 | 核心模块过大，特征计算重复 | 工程优化 | P2 |
| E02 | 配置校验不足，风格通过过滤步骤名隐式推断 | 工程优化／待验证风险 | P1 |
| E03 | 测试缺少跨流程口径与独立公式验证 | 代码确认／工程优化 | P0 |
| E04 | 数据缺失、软评分及分层标签的语义需明确 | 待验证风险／文档问题 | P2 |
| E05 | IEX 流动性刻度与账户真实头寸需明确区分 | 设计约束／工程优化 | P1 |
| E06 | 文档、日志承诺与当前实现存在漂移 | 代码确认／文档问题 | P2 |

## 3. 计算与扫描／回测口径

### C01：调整后 EBITDA 重复调整

位置：[scanner.py](../src/ai_value_scanner/scanner.py)，`load_one_fundamental`，基线约第 3462–3491 行；[现有测试](../tests/test_gap12_metrics.py)，`test_load_one_fundamental_computes_new_metrics`。

`adjusted_ebit = ebit + addback - gain` 已完成调整；`adjusted_da = da + addback - gain` 再调整一次，两者相加实际等于 `ebit + da + 2 × (addback - gain)`。

现有 fixture：EBIT=250，D&A=58，费用加回=8，收益扣除=2。当前输出 320；同一净调整只计一次应为 `250 + 58 + 8 - 2 = 314`。现有测试恰好断言 320，因此测试通过掩盖了公式错误。

影响：净债务／EBITDA 分母、质量分和相关过滤／评分；净加回为正时可能低估杠杆，净收益调整时方向相反。

建议：在项目当前调整语义下使用 `adjusted_ebit + da`；另审查非经常性项目是否相互重叠、是否属于 EBIT，以及 D&A 缺失是否允许当零。后几个问题尚未证实为具体错误，不应自动视为已确认重复。

验收：fixture 输出 314；净调整分别为正、负、零时都只计一次；修改错误测试预期，独立验证杠杆比率。实际数据影响须另行重算。

### C02：回测同比基数错误

位置：[scanner.py](../src/ai_value_scanner/scanner.py)，`pick_latest_and_prev_ttm`、`pick_latest_and_year_ago_with_forms`；[backtest.py](../src/ai_value_scanner/backtest.py)，`latest_and_prev_asof`、`build_cross_section_asof`。

扫描 TTM 同比寻找报告期相隔 320–410 天的基数；回测直接取前一个可见序列值，再命名为 `*_yoy`。季度披露时这通常是相邻 TTM 的增长，并非同比。存量指标的比较基数也存在同类差异。

离线复现：2024 年各季度收入 25，2025 年各季度 30。最新 TTM=120，一年前=100，扫描同比=20%；回测前值=115，输出约 4.35%。

影响：收入／利润／现金流增长、股本稀释、应收／库存增长及增长差、恶化惩罚和候选排序。

建议：PIT 事实保留报告期、披露时间和版本，先按 `asof` 选择可见事实，再按报告期寻找同比基数。没有合适同比值时明确缺失，不使用相邻值冒充同比。扫描存量函数的“无年度值则回退次新值”也应单独标注口径。

验收：相同可见事实下扫描／回测同比一致；覆盖季度、年报、52／53 周财年、缺失基期和重述。

### C03：最大回撤漏掉初始净值

位置：[tune_parameters.py](../scripts/tune_parameters.py)，`max_drawdown_for_series`，基线第 322 行。

函数从首期收益之后的净值开始计算峰值，没有初始净值 1.0。

| 输入收益 | 正确最大回撤 | 当前函数输出 |
|---|---:|---:|
| `[-0.20]` | −20% | 0% |
| `[-0.20, -0.10]` | −28% | −10% |

两例均已复现。影响调参回撤护栏和风险排序。

建议：将初始净值纳入峰值计算；与 R05 的账户净值口径分开修复，补上初始净值并不能解决事件重叠问题。

验收：两例得到 −20% 和 −28%；覆盖先跌后涨、创新高后回撤、空序列。用独立已知净值序列核对。

### C04：PIT 存量序列误选旧报告期

位置：[backtest.py](../src/ai_value_scanner/backtest.py)，`build_level_series`，基线第 456 行。

同一披露日期只保留遍历遇到的第一条值，没有按 `end` 选择最新报告期。同份年报可能包含当期与往年对照，因此结果依赖数组顺序，而不仅是注释声称的 tag 优先级。

离线复现：同一 tag、同一披露日期，先出现 2023 年末值 80，再出现 2024 年末值 100，函数返回 80。

影响：股本、现金、债务、流动资产／负债等存量指标，进一步影响市值、估值和质量。

建议：先对每个时点的可见事实选最新报告期，再处理同报告期的 tag 优先级与重述版本；保留原始期间字段，避免过早降为仅含 `(visible, value)` 的序列。

验收：调换同 tag 数据顺序不改变结果；上述案例返回 100；不同日期的后续重述不能让旧报告期覆盖更新报告期。

### C05：回测“调整后利润”未执行扫描调整

位置：[backtest.py](../src/ai_value_scanner/backtest.py)，`build_cross_section_asof`，基线第 2130 行；[scanner.py](../src/ai_value_scanner/scanner.py)，`load_one_fundamental`。

回测直接将 `adjusted_net_income` 和 `adjusted_ebit` 赋为原始利润；扫描读取非经常性费用／收益，并应用营收比例上限。生产两风格启用了 `use_adjusted_quality_metrics=true`，这不是只影响未启用功能的差异。

影响：利润率、PE、EV／EBIT、利息覆盖、现金化指标、调整后增长及排序可能与实际扫描不同。回测财务路径固定重建 TTM，也需要核对 `use_ttm_metrics=false` 的配置语义。

建议：共享支持 PIT 输入的财务特征实现，同时落实 TTM／年报与利润调整开关；先处理 C01、C02、C04，再重算策略结果。

验收：同一时点、同一配置、同一可见原始事实下，扫描／回测核心财务字段逐项一致；调整开关与上限确实改变两条路径的输出。

### C06：回测主题关联度权重硬编码

位置：[scanner.py](../src/ai_value_scanner/scanner.py)，约第 6117 行；[backtest.py](../src/ai_value_scanner/backtest.py)，约第 2255 行；[主题配置生成](../scripts/generate_theme_configs.py)。

扫描读取 `ai_link_weight_*`，回测仍固定为 0.40／0.35／0.15／0.10。主题配置将 disclosure 权重设为 0，但回测不遵循该设置。默认 AI 权重相同时此差异可能暂不显现。

建议：提取公共关联度计算函数，统一组件输入、权重、截断与缺失值语义；共享过滤／评分函数不等于整个特征路径已一致。

验收：默认权重与历史公式一致；修改任一组件权重时两条路径同步变化；主题 disclosure=0 时回测不贡献该组件。

## 4. 缓存、数据新鲜度与历史信息

### D01：派生缓存不绑定配置和来源版本

位置：[scanner.py](../src/ai_value_scanner/scanner.py)，`load_one_fundamental`，`parsed_fund_<CIK>.json` 读取／写入。

缓存含已计算的 TTM、同比、非经常性调整等，但 key 只有 CIK，读取主要检查 TTL 与 submissions 文件存在。没有核对相关配置、解析代码版本或原始 facts／submissions 版本。

已复现：模拟未过期缓存后，传入 `use_ttm_metrics=false`、`nonrecurring_addback_revenue_cap=0`，仍返回旧缓存中的 TTM 和非零费用加回。原始文件已刷新但派生缓存尚未过期的情形也缺少版本校验，此分支为代码确认，未另行运行真实刷新任务。

建议：派生缓存携带相关配置指纹、计算版本、原始数据版本；读取时一致才复用。只把影响财务计算的配置纳入 key，避免每个评分参数变化都重复解析原始数据。

验收：TTM／调整上限改变、原始 facts 更新、计算版本升级均失效；仅输出数量改变可继续命中；不同配置运行顺序不影响结果。

### D02：同日申报可能漏刷 facts

位置：[scanner.py](../src/ai_value_scanner/scanner.py)，`SecClient.get_companyfacts`，约第 1415 行。

刷新判断将 `filingDate` 转成日期零点，与 facts 缓存文件 mtime 比较。缓存当日 01:00 UTC 写入、同日稍后有新申报时，日期零点小于 mtime，判断无需更新。模拟缓存已复现旧 facts 被返回；此遗漏可能持续到另一项更新条件触发，不能假定第二天自动修正。

建议：以 accession number 或明确的申报版本作为变化检测器；接受时间可作辅助。记录 facts 已覆盖的申报版本，处理 SEC facts 更新可能滞后于 submissions 的情况，不能仅凭下载时间宣称覆盖新申报。

验收：同日新申报触发刷新；无新申报继续命中；新申报先出现而 facts 尚未更新时，记录待更新状态并在合理窗口内重试。

### D03：行情缓存降级缺少统一标记

位置：[scanner.py](../src/ai_value_scanner/scanner.py)，`_load_cache_stale`、`get_snapshots`、`get_daily_bars`；[交易计划](../scripts/generate_trade_plan.py)，`check_breaker_state`。

接口异常时会使用陈旧缓存；bars 降级结果还可能再次保存到缓存。文件 mtime 不能代表市场数据截至时间。QQQ 熔断器已有陈旧日期检查，这是应保留的保护，但个股数据没有同样明确的统一质量契约。

建议：记录源数据 `asof`、获取时间、feed、来源与降级原因，区分新鲜数据和降级数据；按研究／纸面／交易计划用途定义允许的新鲜度。保留有价值的降级读取，禁止它被误报为成功刷新。

验收：网络失败并使用旧缓存时，报告可识别降级；重写文件不改变数据 `asof`；计划检查所用个股和基准的数据时点。

### R01：早期 union 回放含未来 ETF 特征

位置：[backtest.py](../src/ai_value_scanner/backtest.py)，`build_union_watchlist_map`、`resolve_watchlist_asof`、`build_cross_section_asof`。

当前 union 功能已经实现，`pre_snapshot_universe` 默认 `union`。首次快照以前，股票的 bucket、ETF 数量及来源取自后来快照或当前名单；ETF 数量随后进入关联度评分，bucket 也影响通道过滤／评分。股票池因此不仅是一个方便的候选 allowlist。

按 PIT 财报和价格过滤只证明股票当时有数据，无法使未来 ETF 共识变成当时已知信息。关闭 `allow_latest_watchlist_fallback` 也不能使默认 union 元数据回放自动变为严格 PIT。

建议：将候选 superset 与可用历史特征分开；早期无历史依据的特征禁用、使用预注册代理，或明确保留为近似研究。分开输出 strict 与 approximate 结果，禁止混用证据等级。

验收：每条信号说明 universe 和特征的时间来源；早期结果不被标为严格 PIT；变更未来 ETF 数量不会改变声明为 strict 的早期信号。

### R02：幸存者偏差和当前元数据近似

位置：[backtest.py](../src/ai_value_scanner/backtest.py)，`build_union_watchlist_map`、`build_universe_for_replay`、`build_theme_scores_rules_proxy`；[股票池历史](../data/watchlist_history)。

历史快照从 2026-09-22 起存在。union 仍不能纳入此前消失且从未出现在名单中的公司；当前 SEC symbol／CIK 映射、资产状态、名称和 SIC 也不是完整历史证券主数据。rules_proxy 基于当前元数据，不应默认视为严格 PIT 主题证据。

这些是已知数据范围与近似限制，尚未量化偏差大小；不能把所有当前公司的历史记录都判为错误，也不能声称偏差已消除。

建议：保存发现／消失及 symbol／CIK 变化事件；评估缺失退市名称和状态优先截断的敏感性；证据随 universe 来源分层。逐步扩充历史证券主数据，保持研究工具可用。

验收：报告说明 snapshot 覆盖、近似窗口、缺失名称和截断规则；历史近似结果与真实前向观察分别展示。

## 5. 策略验证与调参

### R03：多窗口选参不等于完整样本外 walk-forward

位置：[tune_parameters.py](../scripts/tune_parameters.py)，`default_windows_tokens`、候选窗口循环、`pick_profile_candidates` 和 promotion。

同一候选在多段历史窗口评估，再汇总这些窗口选择参数，属于跨时期历史筛选；没有完整实现“只用前段选参、冻结配置、仅在后段验证”的滚动流程。默认还会将通过护栏的候选自动写入生产配置。

建议：明确区分探索、验证和晋级；采用滚动训练／验证和最终未参与选择的留出区间。参数搜索历史本身也需要留档。默认生成候选，生产晋级由明确命令执行；这是后续改进建议，本文不改变现有配置。

验收：每个样本外时点的配置只能来自更早的训练数据；保存训练／验证区间、选参时间、配置 hash；没有干净验证证据的近似研究产物不自动晋级。

### R04：训练／验证收益标签重叠

位置：[sweep_score_weights.py](../scripts/sweep_score_weights.py)，约第 406 行及后续训练／验证筛选。

仅按信号日期划分训练／验证。训练期尾部信号的 60／120 交易日前向收益可能延伸进验证期，因此两边并非完全隔离。

建议：保留实际进入／退出交易日期；按标签终点清除跨边界训练样本，并根据验证方式设置必要间隔。不能仅按自然日粗略估计持有期。

验收：用于选参的每个训练标签终点均早于验证边界；边界测试覆盖节假日、60／120 交易日和缺价。

### R05：事件复利回撤并非账户回撤

位置：[tune_parameters.py](../scripts/tune_parameters.py)，`evaluate_window`；[backtest.py](../src/ai_value_scanner/backtest.py)，`event_backtest`、`non_overlapping_cumulative`。

调参按事件顺序复利 `portfolio_return`。周／月度信号配合 120 交易日持有会重叠，不能把每一期都当成独占账户的顺序交易。回测摘要已有非重叠累计收益处理，但该机制没有使调参回撤成为账户净值回撤。

建议：用实际 cohort 资金和逐日持仓净值计算账户回撤；事件均值／胜率用于选股诊断。若暂时只用不重叠事件，应明确它是抽样诊断，仍不等同于滚动账户实盘。

验收：多个重叠 cohort 不会重复使用同一资金；回撤来自账户权益序列；不把条件于“有信号”的收益直接解释为含空仓期的策略收益。

## 6. 交易计划与日常运行

### L01：单次计划无法保证跨 cohort 账户约束

位置：[generate_trade_plan.py](../scripts/generate_trade_plan.py)，约第 483 行；[实盘协议](live_pilot_protocol.md)，滚动持有与仓位规则。

每次计划按 `capital × (1 - cash_buffer_pct)` 分配，但不读取现有持仓、历史 cohort、实际现金或待执行订单。10% 上限针对本次名单，并非账户累计敞口。

示例：同一股票连续两个 cohort 都被分配总资金 10%，若旧仓未到期，执行两次计划可能形成约 20% 的名义投入。具体市值比例还随价格变化，不能只累加原始买入金额替代当前敞口。

建议：先建立账户／cohort 台账，区分总资产、现有敞口、本期预算、到期释放额和待成交订单；按交易后累计敞口约束单名上限。确认 `--capital` 是总账户资本还是本期预算，消除两种语义混用。

验收：重复入选不会突破账户级单名上限；重叠 cohort 总投入不超可用额度；幂等重跑不会生成重复可执行买单。

### L02：回测与交易计划的组合构造不同

位置：[backtest.py](../src/ai_value_scanner/backtest.py)，`event_backtest`；[generate_trade_plan.py](../scripts/generate_trade_plan.py)，`sleeve_positions`、跨风格合并与资金分配。

事件回测主要计算入选股票等权前向收益；计划使用 keep／watch／momentum 分层、名单内排序、跨风格置信度合并、单名封顶和现金缓冲。回测没有完整复现月度资金占用、跳空放弃、单仓止损、账户回撤暂停与阶段资金比例。

建议：保留选股事件分析，新增复用计划构造器的账户模拟。跨列表 percentile 排序已有改进，不宜恢复不同权重尺度的原始 composite 直接比较；现有原始分数平局处理和展示行选择应明确只用于元数据还是也影响资金。

验收：同一时点计划／模拟选择和权重一致；模拟执行协议规则；单独报告选股能力与实际组合表现。

### L03：上游失败仍执行下游计划

位置：[daily_run.py](../scripts/daily_run.py)，约第 175–222 行。

`ok &= run(...)` 累计失败，但后续调用继续执行。扫描或周检失败后仍调用交易计划，并打印操作指导，最后才以非零状态退出。记录失败不等于阻断依赖。

建议：区分依赖与独立任务；AI 计划依赖合格 AI 信号与按协议有效的验证状态。主题／venture 观察可独立继续。下游不得把旧计划作为本次成功结果展示。

验收：AI 信号构建失败时不发布新的可执行 AI 计划；周检状态按 L05 的明确规则处理；运行摘要能区分失败、依赖跳过、独立完成和纸面结果。

### L04：报告配对缺少时点与批次约束

位置：[generate_trade_plan.py](../scripts/generate_trade_plan.py)，`latest_scan_pair`；[observation_scan.py](../scripts/observation_scan.py)。

目前按报告 `Config:` 头分别找到最新 risk_off／risk_on，解决了风格误标，但未要求属于同一次成功观察批次、相容数据日期或允许的新鲜度。一个风格失败时可能配上历史另一个风格；旧版无头报告还会回退 mtime 猜测。

建议：产出结构化 manifest，含 batch id、run id、配置 hash、数据截至时间、完成状态和输出路径；计划消费明确成功批次。旧产物可供研究浏览，不应靠猜测生成可执行计划。

验收：两个风格数据时点不相容／批次失败时明确拒绝或降级；完整、合法的空信号批次不被当成失败；不通过文件修改时间推断业务来源。

### L05：协议状态没有机器化闭环

位置：[live_pilot_protocol.md](live_pilot_protocol.md)、[generate_trade_plan.py](../scripts/generate_trade_plan.py)、[validate_ttm_population.py](../scripts/validate_ttm_population.py)。

阶段 P0–P3、连续周检失败、验证结果有效期、账户回撤和实际止损主要由文档及人工执行。计划不读取这些持久状态。QQQ 熔断新鲜度检查和仓位封顶已有实现，应保留，但不能据此称整套风控已自动化。

建议：结构化保存验证 PASS／FAIL、时间、覆盖范围与连续失败次数；保存阶段、阶段起始权益及计划是否仅纸面。机器门槛应忠实实现既有协议，先消除“必须 PASS”与“连续两周 FAIL 暂停”等表述歧义，不擅自新增或放宽资金规则。

验收：阶段配额、暂停状态及验证有效期明确影响可执行预算；人工执行环节在报告中明确标注；纸面结果不会被误当买入指令。

## 7. 主题与 venture 观察

### T01：纸面结算未修正拆股

位置：[theme_observation_scan.py](../scripts/theme_observation_scan.py)，`evaluate_matured`；[backtest.py](../src/ai_value_scanner/backtest.py)，`build_bar_db`。

结算读取 raw bars，直接计算下一交易日开盘到第 120 个交易日收盘的价格比，没有调用拆股修正。1 拆 2、入场原始价 100、退出原始价 50、持股数翻倍且总价值不变的案例，会被当前表达式算成 −50%。这是代码路径确认和算术例子，尚未以真实成熟 cohort 验证影响。

建议：复用已有 authoritative split 处理并统一信号特征／前向收益的价格单位；记录拆股数据失败状态。不能把 split-adjusted close 直接用于“raw close × raw filed shares”的历史估值计算。

验收：正向／反向拆股且价值不变时纸面收益为零；无拆股时不变；拆股信息缺失可识别；theme 与 venture 使用一致结算。

### T02：主题评价不完整

位置：[theme_observation_scan.py](../scripts/theme_observation_scan.py)，`evaluate_matured`；[theme_observation_protocol.md](theme_observation_protocol.md)。

目前结算只有绝对价格收益；虽读取 QQQ，未输出相对 QQQ 或主题基准篮超额，协议已明确承认该缺失。没有一致的交易成本口径，缺价／退市等情况多数保持 open 或跳过，不能当作有效盈利观察。退市如何处理需要独立规则，不能将一切接口缺价自动判为退市。

建议：补充同期基准、主题篮定义、成本前后收益、数据质量和缺价状态；按 cohort 组合而非仅按个股行数评价。优先保持主题 P0 隔离，先完善评价再考虑其晋级证据。

验收：同进入／退出窗口的三种收益口径齐全；基准成分来源可追溯；缺价、未成熟、无信号和退市假设分开计数，不只汇总能定价的赢家。

### T03：观察频率与 cohort 语义不统一

位置：[daily_run.py](../scripts/daily_run.py)、[theme_observation_scan.py](../scripts/theme_observation_scan.py)，`archive_cohort`；[主题协议](theme_observation_protocol.md)、[实盘协议](live_pilot_protocol.md)。

每日扫描会按扫描日期归档 cohort；去重 key 为 theme／list／entry_date／symbol。协议同时出现月度滚动 cohort、每周观察及周度成熟样本要求。每日有记录不等于每日新建独立资金 cohort，同一天重复扫描也可能把不同时间的候选并到同一日期记录。

建议：区分每日 signal observation 与明确频率的 portfolio cohort；保存 cohort id、信号时间、实际入场日及冻结批次。同日重跑采用明确的替换或快照策略，避免事后合并入选名单。

运行顺序补充：周一 daily runner 先跑主题／venture 扫描，再刷新主题篮与 venture 底单，因此刷新默认从后续扫描生效。若要求当日使用新底单，应将对应构建任务置于扫描之前；若有意延后，应明确记录使用的 universe 版本。这是依赖与时点的优化建议，不将该顺序本身判为确定错误。

验收：协议与代码频率一致；重跑语义可说明；样本量不把重叠日度记录当独立样本；保留空信号和失败状态的区别。

### T04：新主题继承 AI 校准假设

位置：[generate_theme_configs.py](../scripts/generate_theme_configs.py)、[scanner.py](../src/ai_value_scanner/scanner.py)，`build_research_assessment`；[多主题设计](multi_theme_expansion.md)。

主题复用 AI 的 research tags、基础阈值和 QQQ 主熔断，生成配置主要通过放宽风险／priority 门槛、调整研究分下限适配。单 ETF 主题的 consensus 区分度有限；submissions 元数据关键词也不能等价为完整业务披露分析。这些为模型假设局限，尚不能直接判定对应策略无效。

建议：共享计算引擎，分离主题语义与校准参数；逐主题验证评分分布、恒定组件、基准选择和熔断适用性。AI 的历史 IC 不自动成为新主题证据；披露组件的有效性应按实际输入重新判断。

验收：主题独立记录特征覆盖和前向表现；组件缺失／恒定可识别；任何主题专属规则变更预先登记，不因单期收益临时改门槛。

### T05：主题失败没有正确传递运行状态

位置：[theme_observation_scan.py](../scripts/theme_observation_scan.py)，`main`。

子扫描非零退出后打印 FAILED 并 `continue`，未累计错误并在主脚本退出时返回失败。因此单个甚至多个主题失败时，上层 daily runner 仍可能看到脚本返回 0。它与“无信号”的正常结果不是同一状态。

建议：保持各主题可独立继续，汇总每主题成功／失败／无信号，最终返回可识别的部分失败状态；将运行状态写入 manifest。

验收：模拟一个或全部子任务失败，上层能识别；合法空清单仍为成功；失败不会产生代表成功空信号的伪 cohort。

## 8. 工程结构与语义优化

### E01：模块拆分应围绕公共计算契约

具体模块边界、依赖方向、五批迁移步骤和验收标准见[模块拆分与渐进重构方案](modular_refactoring_plan_20261003.md)。

基线 `scanner.py` 6,840 行，`backtest.py` 3,866 行。客户端、缓存、财务提取、特征、过滤、研究标签、报告和主流程集中在两个大模块；多处特征计算重复是上述口径漂移的直接维护风险。

建议：渐进拆分为配置、数据客户端、事实重建／PIT、公共特征、策略评分、账户／cohort、评价与报告。CLI 保持薄入口，保留单进程／本地存储；当前没有必要为了拆模块引入微服务或分布式基础设施。

验收：先通过字段一致性测试抽取公共特征，再移动代码；避免只有文件拆分而计算仍重复。性能改进需以缓存正确性和测量为前提。

### E02：配置契约与风格选择需要显式化

位置：[scanner.py](../src/ai_value_scanner/scanner.py)，`ScanConfig.from_dict`、`resolve_channel_profile`、`partition_filter_steps`。

顶层未知 key 当前会警告后忽略，不能再描述为“完全静默”；但配置缺少完整的类型、范围及组合校验，通道字典整体替换而非默认深合并，嵌套阈值／权重拼写的可验证性不足。风格由是否出现名为 `min_price_to_sma200` 的步骤推断，和业务配置存在隐式耦合。

建议：增加明确的 style／schema version，显式声明硬门／软项；校验字段、范围、权重及 null 语义。`_theme_meta` 等元数据使用明确命名空间；保留兼容入口，并对生产配置采用严格检查。不要未经审查把现有整体替换改成深合并，以免继承不应存在的通道。

验收：拼错的关键字段可定位；非法组合启动时失败；关闭单个阈值不隐式改变风格；生成配置与加载结果可对照。

### E03：测试通过不证明公式正确

位置：[tests](../tests)、[EBITDA 测试](../tests/test_gap12_metrics.py)、[过滤一致性测试](../tests/test_scored_list_parity.py)、[组件权重测试](../tests/test_theme_component_weights.py)。

202 项离线测试全部通过，但 C01 测试固化了重复调整，过滤一致性测试不涵盖原始事实到特征的一致性，部分组件测试主要验证配置／重写公式，而非完整业务路径。

建议：增加有独立正确答案的财务／回撤案例，扫描与回测字段对照、配置变更与缓存隔离、失败依赖、拆股结算和账户约束测试。对错误修复先建立失败用例；不为单纯文档调整添加镜像实现的测试。建立 stdlib unittest 的最小 CI，再按需要引入静态检查。

验收：新增测试在修复前暴露问题、修复后通过；重要输出不依赖输入数组顺序；测试不访问生产缓存、网络或真实资金。

### E04：缺失值、软门槛和 triage 的语义

位置：[scanner.py](../src/ai_value_scanner/scanner.py)，`robust_normalize_score`、`apply_scored_or_hard_filters`、`assign_triage_label`、`apply_low_value_research_gate`；[实盘协议](live_pilot_protocol.md)，已知死层记录。

缺失评分维度默认中性 0.5，scored 模式将多数质量／估值门槛变为软项，因此入选不意味着所有质量阈值通过。项目仍有硬门和 low_value research gate，不能反过来声称没有质量保护。

drop 在文档所述历史幸存者样本中未触发，这是已有研究记录，本次未重跑证实所有未来情形都不会触发。名单之间分数尺度不同，当前计划已使用名单内 percentile 改善选择，应保留这项改进。

建议：输出覆盖率、缺失原因、数据质量及实际通过的硬门；区分 drop 的研究含义和交易资格，评估缺失中性处理的敏感性。分层阈值须在正确特征与样本外数据上重新校准，不能靠改变阈值强行制造 drop。

验收：用户能看到“低分”与“数据缺失”的区别；相同绝对情况因小样本归一化产生的排名变化可解释；分层语义在 README、报告和计划中一致。

### E05：流动性刻度不能混用

位置：[AGENTS.md](../AGENTS.md)，IEX 约束；[生产配置](../configs/config.risk_off.json)，`assumed_position_usd`；[scanner.py](../src/ai_value_scanner/scanner.py)，流动性指标与门槛。

按现有项目约定，IEX 成交额与配置门槛同刻度，不能只因数值较小就判为计算错；但这些数值不能直接解释为全市场真实流动性或账户真实参与率。扫描中的固定假设头寸与最终实际计划头寸也不是同一对象。

建议：报告明确 feed 与成交额刻度；分开记录研究门槛的假设头寸和账户实际头寸。更换 feed 必须绑定重新校准和版本记录，不能单独改数据源沿用旧流动性阈值。

验收：输出可追溯 feed／门槛版本；账户执行指标不将 IEX 数字误标为 consolidated；切换 feed 后旧结果不会与新结果无标记混合。

### E06：文档与运行承诺漂移

位置：[AGENTS.md](../AGENTS.md)、[README.md](../README.md)、[实盘协议](live_pilot_protocol.md)、[generate_trade_plan.py](../scripts/generate_trade_plan.py)、[daily_run.py](../scripts/daily_run.py)。

本次确认的差异：

- AGENTS.md 的测试数量为 105，当前实际为 202；union 被写为计划实现，当前已经默认实现。
- AGENTS.md 的 submissions 默认 TTL 描述为 0／每次刷新，当前代码及两风格生产配置为 86,400 秒。
- 未知顶层配置 key 实际会警告后忽略，文档的“静默忽略”描述需要更新。
- 交易计划文件头仍描述 60／40 分袖资金模型，当前实现是单一置信池，60／40 仅为观察镜头。
- 实盘协议已将财报临近改为提示，但禁止事项仍保留“财报窗口内不抢跑入场”；需统一现行语义，不在本文擅自改变规则。
- 协议“一个季度”与“完整 120 交易日 cohort”不是相同时间长度，需要以实际成熟条件为准写清楚。
- daily runner 声称将日志写入 `.debug_logs/daily_YYYYMMDD.log`，但脚本只定义路径并打印，没有实现文件日志。外部重定向若存在需要明确说明，本次未核查外部调度。
- daily runner 的 trade plan／`--capital` 在说明中呈现为可选，实际默认资本 100,000 且每次流程都会调用计划生成；需要澄清纸面、计划与真实执行边界。
- 报告内历史基线、IC 与分层证据含硬编码数字；修复计算后不能自动视为仍有效。应绑定数据、配置、代码版本和评价口径，避免持续展示过期证据。

建议：代码修复后同步权威 README、协议和 AGENTS.md；运行摘要使用结构化产物来源，避免从 Markdown 文本反向提取业务状态。历史数字保留出处与旧版标签，更新需要可重跑的产物。

验收：当前默认行为与文档一致；日志文件实际生成或文档明确依赖外部重定向；旧基线不会被贴为新版本验证结果。

## 9. 应保留的设计与优化顺序

应保留：watchlist 限定研究范围、动态通道、多风格独立观察、核心硬门与软评分、公共过滤函数、TTM 重建和总体不变量验证、raw 行情缓存与按用途拆股修正、QQQ 新鲜度检查、跨风格去重／封顶、主题 P0 及 AI 快照隔离、离线快速测试。

建议分阶段实施，阶段间保留旧产物和配置版本：

1. **基础正确性**：C01–C06、D01–D02，先添加独立正确答案／口径一致性测试，再修公式、事实选择和缓存。
2. **评价可信度**：R01、R03–R05，明确近似研究边界、训练标签隔离和账户回撤口径；再重建数据集、重跑权重／调参／验证。R02 的残余偏差须持续记录。
3. **执行闭环**：L01–L05、D03、T05，建立结构化运行 manifest、账户与 cohort 台账、验证／阶段状态及依赖门槛。
4. **观察评价**：T01–T03，统一拆股、基准、成本、缺价状态和 cohort 频率；T04 通过真实前向数据验证主题假设。
5. **维护与语义**：E01–E06，渐进模块拆分、配置校验、最小 CI、文档和产物证据更新。与前几阶段直接相关的测试和文档同步应提前执行。

重算影响评估至少包含：变动字段及覆盖公司数、入选／排序变化、分层权重变化、历史事件与账户评价变化、近似／strict 分组结果。本文不提供“修复后收益会提高”的承诺，公式修正可能使历史表现变好或变差。

## 10. 离线复现附录

以下命令从仓库根目录运行，使用当前项目函数、现有测试 fixture 与模拟数据。它复现错误现状，不是修复后的回归测试；未来修复后预期输出应相应更新。所有缓存模拟均在 mock 上运行，不访问真实 API 或生产缓存。

```bash
.venv/bin/python - <<'PY'
import importlib.util
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from ai_value_scanner.scanner import (
    ScanConfig, SecClient, load_one_fundamental,
    pick_latest_and_prev_ttm, REVENUE_TAGS, QUARTERLY_FORMS, safe_yoy,
)
from ai_value_scanner.backtest import (
    extract_metric_points, build_flow_ttm_or_annual_series,
    latest_and_prev_asof, build_level_series,
)

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

fixture = load_module('review_fixture', 'tests/test_gap12_metrics.py')
sec = fixture._FakeSecClient(
    {'sic': '3571', 'sicDescription': 'Electronic Computers'},
    fixture._build_companyfacts_ttm_full(),
)
with tempfile.TemporaryDirectory(prefix='scanner-review-') as cache_dir:
    result = load_one_fundamental(
        sec, 'REVIEW', '9999999999', ScanConfig(cache_dir=cache_dir),
    )
print('C01:', result['adjusted_ebitda'],
      'adjustment once:', result['adjusted_ebit'] + result['depreciation_and_amortization'])

entries = []
for year, value in [(2024, 25.0), (2025, 30.0)]:
    for quarter in range(1, 5):
        start = pd.Timestamp(year=year, month=3 * quarter - 2, day=1)
        end = start + pd.offsets.QuarterEnd()
        entries.append({
            'start': str(start.date()), 'end': str(end.date()),
            'filed': str((end + pd.Timedelta(days=35)).date()),
            'val': value, 'form': '10-Q',
        })
facts = {'facts': {'us-gaap': {REVENUE_TAGS[0]: {'units': {'USD': entries}}}}}
scan_pair = pick_latest_and_prev_ttm(facts, REVENUE_TAGS, 'USD')
replay_pair = latest_and_prev_asof(
    build_flow_ttm_or_annual_series(
        extract_metric_points(facts, REVENUE_TAGS, 'USD', QUARTERLY_FORMS)
    ), pd.Timestamp('2026-03-01', tz='UTC'),
)
print('C02: scan=', safe_yoy(*scan_pair), 'replay=', safe_yoy(*replay_pair))

tuner = load_module('review_tuner', 'scripts/tune_parameters.py')
print('C03:', [(r, tuner.max_drawdown_for_series(pd.Series(r)))
               for r in [[-0.20], [-0.20, -0.10]]])

points = [
    {'visible': pd.Timestamp('2025-02-01', tz='UTC'),
     'end': pd.Timestamp('2023-12-31', tz='UTC'), 'value': 80.0},
    {'visible': pd.Timestamp('2025-02-01', tz='UTC'),
     'end': pd.Timestamp('2024-12-31', tz='UTC'), 'value': 100.0},
]
print('C04:', build_level_series(points))

config = ScanConfig(
    cache_dir='/tmp/scanner-review-virtual-cache', use_ttm_metrics=False,
    sec_cache_ttl_submissions_sec=86400, nonrecurring_addback_revenue_cap=0.0,
)
cached = {'symbol': 'OLD', 'revenue': 120, 'revenue_form': 'ttm',
          'nonrecurring_expense_addback': 25}
with patch.object(Path, 'exists', return_value=True), \
     patch.object(Path, 'stat', return_value=SimpleNamespace(st_mtime=time.time())), \
     patch.object(Path, 'read_text', return_value=json.dumps(cached)):
    print('D01:', load_one_fundamental(object(), 'REVIEW', '0000000000', config))

sec = object.__new__(SecClient)
sec.cache_dir = Path('/tmp/scanner-review-virtual-cache')
sec.monitor = None
mtime = pd.Timestamp('2026-10-02T01:00:00Z').timestamp()
def read_cached(path, *args, **kwargs):
    if path.name.startswith('submissions_'):
        return json.dumps({'filings': {'recent': {'filingDate': ['2026-10-02']}}})
    return json.dumps({'version': 'previous_facts'})
with patch.object(Path, 'exists', return_value=True), \
     patch.object(Path, 'stat', return_value=SimpleNamespace(st_mtime=mtime)), \
     patch.object(Path, 'read_text', read_cached):
    print('D02:', sec.get_companyfacts('0000000000'))
PY
```

基线预期关键输出：C01 为 320／314；C02 为约 0.20／0.043478；C03 为 0／−0.10；C04 选中 80；D01 返回不符合新配置的旧 TTM／加回值；D02 返回 `previous_facts`。

## 11. 处理记录

2026-10-03：完成审查记录与 README 入口，尚未修复实现。后续每个 ID 建议记录负责人、修复提交、验证结果和受影响历史产物的重算状态；未完成重算前，不把旧证据标为新实现的验证结果。

文档验证：已执行附录的六个离线复现案例，输出与基线记录一致；已检查文档中的相对文件链接，目标均存在。202 项测试通过为本次会话前序审查结果，文档编辑后未重复运行整个测试集。

2026-10-05：A 组（数据正确性）修复完成，提交见 git log。

- 已修复并验证（新增 `tests/test_review_p0_fixes.py` 17 项测试，先失败后通过）：
  - **C01** `adjusted_ebitda = adjusted_ebit + raw D&A`（调整只计一次；`test_gap12_metrics` 的错误预期 320 已更正为 314）。
  - **C02** 回测新增 `latest_and_year_ago_flow`（320–410 天窗口期匹配，与扫描 `pick_latest_and_prev_ttm` 同口径）与 `latest_and_year_ago_level`（≥300 天报告期 + 次新回退，与扫描 `pick_latest_and_year_ago_with_forms` 同口径）；真实缓存验证 GOOG 收入/净利的 YoY 基数扫描↔回测一致。遗留：最新 TTM 值两路径存在 ~1e-9 级重建差异（pre-existing，属 C05 共享实现范畴）。
  - **C04** `build_level_series` 同披露日取最新报告期（原取首遇值）；流/存量序列现携带报告期 end（3 元组），2 元组旧序列自动降级为相邻回退（兼容既有测试数据）。
  - **C05** 回测接入扫描的非经常性调整：`FundamentalPointInTime` 新增 9 个逐标签 TTM 序列，`compute_adjusted_metrics` 复刻扫描语义（逐期 cap、调整只计一次），cross-section 输出新增 `nonrecurring_expense_addback`/`nonrecurring_gain_subtraction` 两列。
  - **C06** 回测 AI 关联度改用 `scan_config.ai_link_weight_*`（`compute_ai_link_score`），主题 disclosure=0 等配置不再被硬编码覆盖。
  - **D01** `parsed_fund` 缓存写入 `_cache_meta`（计算版本 v2 + 财务计算相关配置指纹 + 最新申报日期），读取时三者任一不匹配即视为失效。**注意：现有 v1 缓存全部失效，下次运行将一次性重新解析（一次性成本），之后恢复命中。**
  - **D02** `get_companyfacts` 改用 accession number 变更检测 + `facts_meta_<CIK>.json` 记录已覆盖/待更新状态；facts 滞后于申报时保持 pending 重试。旧缓存无 meta 时保留原 mtime 启发式，首次升级运行不会批量重拉。
- 附录复现现状：C01=314、C04=100、D01=慢路径触发，与修复后预期一致（附录基线数值为修复前记录，保留作历史对照）。
- 重算状态：**受影响产物尚未重算**。C02/C04/C05/C06 改变 weight dataset 的特征列，`outputs/weight_dataset_*`、sweep/IC/调参产物需在修复后重建；未重建前旧产物不代表当前实现。
- B 组（C03、R03–R05）与 C 组尚未处理。

2026-10-05（续）：B 组四个 P0 修复完成，提交 `9a3b235`，4 项新测试（评审套件共 20 项，全库 228）。

- **C03** `max_drawdown_for_series` 峰值纳入初始净值 1.0（`[-0.20]`→-20%、`[-0.20,-0.10]`→-28%，验收案例通过；峰值高于初始净值后按运行峰值计）。
- **T01** 主题/venture 结算（`evaluate_matured`）先用权威拆股事件调整价格帧再计 open→close；拆股事件获取失败时记录并按未调整价格结算。已成熟 cohort 的历史收益需重评。
- **R04** 抽取器记录精确标签终点（逐符号 `label_end_{h}`、逐日期 `qqq_label_end_{h}`）；sweep 按 (signal_date, horizon) 清除标签终点越过验证边界的训练样本，旧数据集无该列时回退保守日历间隔（horizon×7/5+2 天，与非重叠选择同一界限）。
- **R05** 调参回撤改用 `non_overlapping_event_returns`（不重叠事件选择）；这是抽样诊断口径，不等同于滚动账户净值——完整账户回撤需 L01/L02 的账户模拟，暂未实现。
- **R01 决策**（经确认）：按"固定底单"原则保留 union 元数据作为池静态属性，meta 已如实标注 `union_superset_approx`；不中性化、不重抽。如需 strict-PIT 主张，另做中性化敏感性变体。
- R03 未处理（留到下一轮真正调参前）；C 组其余与 D03/E0* 未处理。
- 重算进行中：修复后全量抽取（risk_off、risk_on，含 label_end 列）→ R04-aware sweep + IC。

2026-10-05（续2）：重算完成。

- 新数据集：`outputs/weight_dataset_risk_{off,on}_p0fix.csv`（42 日期；risk_off 42,573 行 / risk_on 32,371 行；含 `label_end_{h}`、`qqq_label_end_{h}` 列，覆盖约 89.8%，缺失=退市假设/未到期）。
- R04 边界清除生效：sweep 日志显示按期阻止泄漏训练日期 {20d:1, 60d:3, 120d:6}。
- 基线（当前配置）验证分：risk_off 0.1489→**0.1749**（+0.026，C02 修正后泛化明显改善）；risk_on 0.1841→0.1677（-0.016，略降；train/valid 差距收窄，泄漏虚高被剔除）。
- 维度级 IC（H=60）：risk_off `pe_discount` +0.0336（t=2.68，保持显著）；risk_on `ps_discount` +0.0749（t=2.49，改善）；`fcf_yield` 在 risk_off 仍为负（-0.104，价值陷阱结论不变）。
- 权重决策：**不更换**。1000 候选中 37%/28% 超过基线验证分，但 top5-by-train 与 top5-by-valid 零重合——单次运行选权重不可靠，与既往多种子共识流程一致；基线稳定处于中位之上。若需新权重，应跑多种子共识后再评估。
- 旧数据集与旧 sweep 报告保留为历史产物（`*_rebuilt_20261001*`、`*_haircut_rebuild*`）。
