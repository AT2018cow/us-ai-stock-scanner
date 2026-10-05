# 模块拆分与渐进重构方案（2026-10-03）

## 1. 目标与现状

状态：**pre-E01 correctness 已基本收口，准备进入实施。** 对应的问题与复现证据见[设计、逻辑与计算审查记录](design_and_calculation_review_20261003.md)。截至 2026-10-05，C01–C06、D01–D03、R03/R04、T01/T02/T03/T05、E02 已修复或显式收口；R01/R02/R05、T04、E04/E05 保留为已知研究近似/语义边界，不阻塞结构迁移。

建议采用“公共计算核心＋独立流程编排”的模块化单体，继续使用现有 CLI、单进程与本地存储。重构目标是明确职责、降低依赖并消除重复计算；文件行数下降是结果，不是唯一验收标准。

当前实施基线为 PR #3 合并后的 `6b21299ea62aa5e9c75f40b88d3af5bf1e9a3fcf`，再叠加 pre-E01 closure PR。主要结构问题仍然成立，而且 monolith 继续增长：

- [scanner.py](../src/ai_value_scanner/scanner.py) 约 7.8k 行，`run_scan` 仍混合数据加载、特征计算、选股、诊断和输出。
- [backtest.py](../src/ai_value_scanner/backtest.py) 约 4.2k 行，仍重复实现扫描中的大量财务/特征逻辑。
- `backtest.py` 仍从 `scanner.py` 导入数十个常量、客户端、计算及策略函数；工具脚本也通过业务入口借用底层能力。
- PR #4 当前 CI 共 258 项离线测试通过，其中 pre-E01 closure 新增独立收益/日历/cohort 边界测试。E03 仍作为重构验收原则：测试通过不能替代独立正确答案和跨流程一致性。

## 2. 建议职责边界

| 模块 | 职责 | 主要迁入内容 |
|---|---|---|
| `config.py` | 配置结构、默认值、加载、通道解析与校验 | `ScanConfig`、`BacktestConfig`、默认 profile、`resolve_channel_profile` |
| `data/` | 网络、限流、缓存、数据客户端、股票池与快照 | session／monitor／limiter、`AlpacaClient`、`SecClient`、watchlist |
| `fundamentals/` | SEC 事实解析、期间重建、PIT 选择和财务指标 | tag 映射、季度／TTM 重建、同比、非经常性调整、存量比率 |
| `features/` | 价格、估值、横截面和主题特征 | 拆股、价格维度、历史估值、行业相对估值、关联度 |
| `strategy/` | 过滤、评分、研究标签、候选选择和名单限额 | 三清单 steps、scored 分层、排名、triage、去重和 group caps |
| `evaluation/` | 历史回放、前向收益、基准与统计评价 | replay、事件回测、成熟窗口、汇总和重叠校正 |
| `portfolio/`（可选） | 从候选到人工参考 allocation | 分层参考权重、跨风格合并、单名封顶；不维护真实账户/订单状态 |
| `reporting/` | 输出格式、报告渲染和产物写入 | CSV／JSON／Markdown、诊断报告、路径和原子输出 |
| `workflows/` | 组织业务步骤和处理运行依赖 | 扫描、回测、观察、交易计划和日常运行编排 |

以下为逐步演进的目录示意，不要求首批创建所有文件。先按职责迁移，再根据复杂度细分，避免大量只包装一个函数的模块。

```text
src/ai_value_scanner/
├── config.py
├── data/
│   ├── http.py                # session、限流和网络监控
│   ├── cache.py               # 缓存读写、版本和新鲜度
│   ├── alpaca.py
│   ├── sec.py
│   └── universe.py            # watchlist、快照及候选池来源
├── fundamentals/
│   ├── facts.py               # 事实结构、tag、单位和期间
│   ├── reconstruction.py      # 季度／TTM 重建
│   ├── point_in_time.py       # 可见性和事实版本选择
│   └── metrics.py             # 同比、利润调整和财务比率
├── features/
│   ├── prices.py              # 价格特征与按用途拆股处理
│   ├── valuation.py           # 倍数、历史分位和行业比较
│   └── theme.py               # 组件和可配置关联度
├── strategy/
│   ├── filters.py
│   ├── scoring.py
│   ├── assessment.py          # research assessment 和 triage
│   └── selection.py           # 三清单构建、去重和名单限额
├── evaluation/
│   ├── replay.py
│   ├── returns.py
│   └── metrics.py
├── portfolio/
│   └── planning.py            # 可选：现有人工 reference allocation 的纯构造实现
├── reporting/
│   ├── exports.py
│   └── markdown.py
├── workflows/
│   ├── scan.py
│   └── backtest.py
├── scanner.py                 # 迁移期薄兼容入口
└── backtest.py                # 迁移期薄兼容入口
```

本项目边界是选股/研究/报告，不是自动交易。真实券商账户台账、订单状态和自动执行不属于本轮 E01；若未来新增 portfolio simulator，应作为独立功能。当前 theme/venture paper cohort 仅为研究数据，已在 pre-E01 closure 中明确 weekly identity/provenance。

## 3. 依赖方向

CLI 和工具脚本调用 workflow；workflow 组织数据加载、纯计算与产物输出。建议依赖约束：

- `data/` 可以依赖配置和自身基础设施，不依赖策略、评价或 workflow。
- `fundamentals/` 处理传入事实，不依赖客户端或 workflow。
- `features/` 可以使用财务事实和公共计算，不依赖网络或输出模块。
- `strategy/` 消费已构建的特征，不重新拉取财报／行情。
- `portfolio/` 若保留，仅消费候选并生成**人工参考 allocation**；不得暗示真实账户/订单状态。`evaluation/` 复用特征和策略能力。
- `reporting/` 消费结果与元数据，不重新计算选股结论。
- `workflows/` 注入客户端、组织调用、处理依赖状态和错误，并调用 reporting。
- 底层新模块不再导入 `scanner.py` 或 `backtest.py`；两者仅依赖新模块用于兼容。

```text
CLI / scripts
      │
      ▼
  workflows ───────────────────────► reporting
      │                                  ▲
      ├── data                           │
      ├── fundamentals → features → strategy
      └── evaluation / portfolio ────────┘
```

图中的箭头表达使用／数据流；真正的 Python import 应遵守以上模块约束。例如纯财务计算不得为读取事实而反向导入 SEC 客户端。

跨模块数据结构就近归属：SEC 事实结构放在 `fundamentals/facts.py`，计划结构放在 `portfolio/`，运行结构放在 workflow／reporting 的适当位置。不要把所有类型、常量和函数堆入新的通用 `utils.py` 或 `models.py`。

## 4. 三个必须统一的计算契约

### 4.1 扫描与回测共享财务计算

建议接口示意，尚未实现：

```python
build_financial_features(observations, *, asof, config)
```

事实至少保留报告期起止、披露时间、值、单位、taxonomy／tag 和申报版本。财务年度／季度信息在重建需要时保留；symbol／CIK 映射来源也应可追溯。

处理顺序为：先选 `asof` 时可见的事实版本，再按报告期重建季度／TTM，寻找同比基数，最后计算调整利润和比率。不能仅以披露日期相邻的值计算同比，也不能过早降为只有 `(visible, value)` 的序列。

扫描使用当前可见事实，回测使用历史可见事实，公式共享。两条路径的可见性、snapshot 价格与历史收盘价可以不同，但差异应出现在明确的输入适配层。

统一过程中分别处理审查记录的 C01、C02、C04、C05，不能为了“输出一致”保留已确认的错误答案。

### 4.2 数据获取与特征计算分离

客户端负责获取原始数据；计算模块接收数据并返回结果。纯计算不读取 `.env`、访问网络、读取生产缓存或写报告。

Pandas DataFrame 可以继续作为批量特征载体，不必将全部行改成复杂对象。需要明确必需列、单位、缺失值、时间与数据来源；类型化结构优先用于 SEC 事实、配置和运行元数据等需要强语义的边界。

时间契约必须说明 UTC／市场交易日、信号生成时点、已完成交易日及进入／退出窗口。数据来源适配层负责截取可用数据，计算层不自行使用系统当前时间替代调用方 `asof`。

raw bars 继续作为原始数据；价格变化和前向收益按用途修正拆股，历史估值保持与 raw filed shares 一致的价格单位。公共化不能把不同用途的价格单位混在一起。

### 4.3 候选选择与人工参考输出分离

`strategy/selection.py` 构建各清单候选；如保留 `portfolio/planning.py`，其职责只应是把候选转换成供人工阅读的参考 allocation，而不是维护真实账户状态。扫描、trade-plan reference 和需要组合口径的研究评价可复用纯构造函数。

事件回测继续承担排名/选股诊断；R05 的 non-overlapping drawdown 明确保持 sampling diagnostic，不扩张为账户 NAV 模拟。若未来确有账户模拟需求，作为独立项目新增，不能在机械重构中偷偷引入。

保留现有 trade-plan reference 按名单内 percentile 选择的改进，明确原始 composite 在跨列表平局和展示时的作用；不恢复跨权重尺度的直接分数竞争。

## 5. 五批迁移步骤

### 第一批：建立可核对的基线

PR #5A 提供固定实验协议和机器可比 manifest，见 [E01 重构前基线实验协议](refactor_baseline_protocol.md)。基线必须冻结当前 watchlist 与 watchlist-history，使用固定成熟窗口、固定输出前缀和不可 promote 的小型 walk-forward smoke。

PR #5A 当前 CI 为 **269 项离线测试通过**，这是 E01 正式迁移的测试基线；其中新增 baseline-tool、冻结 universe 输入和 calculation characterization 用例。为审查确认的错误继续保留独立正确答案。行为保持基线用于纯搬迁，正确性用例用于修复，两者目的不同。

交付：固定输入副本、risk_off/risk_on deterministic artifacts、tuner smoke、baseline manifest，以及后续 `compare` 零漂移门。动态 network/report timestamp 不做 byte-level gate，但 provenance 必须保存。

交付：依赖清单、离线样本与输出契约，明确“已知旧错误”和“重构引入差异”的区分。

### 第二批：抽取配置与数据基础设施

先迁移配置、默认 profile、HTTP／限流／网络监控，再迁移客户端、缓存和股票池。修正脚本从回测入口导入客户端的依赖。

首批配置搬迁必须**原样保持 PR #3 已落地的契约**：`config_schema_version=1`、显式 `strategy_style`、unknown/type/range fail-fast、null 禁用语义、`channel_profiles` 整体替换以及 CLI 覆盖。这里不再新增配置行为，只做机械迁移与兼容 re-export。

交付：底层不依赖 scanner／backtest；导入不会构造客户端或要求环境变量；CLI 及脚本入口可用。

### 第三批：统一事实和特征计算

引入保留期间与披露版本的事实结构，提取季度／TTM 和 PIT 选择，统一同比、利润调整、财务比率、估值与主题权重。将 `build_cross_section_asof` 收缩为输入适配和公共特征调用。

结构调整和公式修正分成不同提交；已知错误应先有正确答案用例，再修复。共享后的结果用于新策略验证以前，必须完成相关正确性修复，不能以“先搬迁”为由继续把错误指标当成可信证据。

交付：相同可见输入与配置下，扫描／回测公共字段一致；缓存绑定相关配置及数据／计算版本；记录修复导致的预期结果变化。

### 第四批：抽取策略与输出，缩短 workflow

迁移三清单 steps、显式硬门／软项、排名、研究标签、去重和名单限额。提取报告渲染、输出路径与写入。

将 `run_scan` 分为数据加载、特征构建、候选选择、诊断及输出几个步骤。workflow 负责组织调用，具体实现不再写成千行主函数或大量闭包。

交付：三清单共用明确的选择接口；报告不重新选股；同一批次配置和数据来源随产物保存。

### 第五批：迁移回放与工具链，保持研究运行契约

迁移历史回放、收益和评价函数；权重数据提取、主题观察、缓存刷新和交易计划通过公共模块使用能力。逐步将 `scripts/` 中的可复用逻辑移入包内，保留参数解析入口。

theme/venture weekly paper-cohort、评价状态、business-date 与运行失败传播已经在 correctness 阶段收口；迁移时只保持这些契约。结构化 run manifest 可作为后续工程增强，但真实账户/cohort ledger、订单闭环和自动执行明确不在当前产品范围。

交付：工具链不再从业务入口借底层函数；事件评价、paper cohort 评价与人工 reference 输出边界清楚；依赖失败状态准确传递。

## 6. 兼容迁移与变更隔离

迁移期间保留 `scanner.py`、`backtest.py` 的旧入口和明确的兼容导出，允许调用方逐批迁移。新实现只放在职责模块中，兼容入口不承担新业务。

兼容导出采用显式 import，避免星号导出和循环依赖。历史私有函数导入在测试／工具中逐步替换为稳定接口，不将整个内部函数集合变为永久公共 API。

移动函数后，mock 应 patch 使用该依赖的新模块；仅在旧 facade 上替换同名函数通常不会改变已搬迁函数的全局依赖。动态加载源文件及读取源代码文本的测试也需要同步调整，优先改为验证实际业务输出。

首轮保留命令、配置路径、主要产物命名和 CSV 字段；必要的新 schema／manifest 显式版本化。配置行为、公式修正、账户能力和产物格式改变分别记录，避免在一个机械迁移提交中同时变化。

文档中的历史 IC、分层收益、调参结果及基线不能自动继承为修复后实现的验证证据；根据审查记录完成重算并绑定代码／配置／数据版本。

## 7. 验收标准与文件规模

每批至少检查：

- stdlib unittest 相关测试和完整必要检查通过；继续采用 `python -m unittest discover -s tests`，不转换成 pytest 才能完成重构。
- 纯结构迁移的确定性输出一致，计算修正有独立正确答案与可说明的差异。
- 同数据、同配置、同可见时点，扫描／回测公共财务与特征字段一致。
- 核心公式与候选选择可完全离线运行，测试隔离于生产缓存。
- 模块导入不触发网络、环境变量检查或文件写入；客户端在明确的运行入口构造。
- 没有循环依赖，底层模块不反向导入 scanner／backtest／workflow。
- CLI、脚本、配置、报告和输出格式在迁移约定内保持可用。

对 NaN、排序平局和浮点结果约定比较规则，不能只比较最终前十股票就忽略中间特征差异。重要边界用真实接口测试，避免通过在测试里重复实现公式来证明实现正确。

单文件约 300–700 行、workflow 约 100–200 行可作为人工审查提示，不设硬性限制。文件应包含紧密相关的能力；存在复杂但独立的会计重建算法时，完整性与可测试性优先于行数。

## 8. 与问题修复的关系和实施记录

第一批实际抽离优先考虑配置与数据客户端；整次重构最重要的产出是统一事实、财务及特征计算。基础错误与评价口径的修复优先级仍以[审查记录第 9 节](design_and_calculation_review_20261003.md#9-应保留的设计与优化顺序)为准。

轻量机械拆分可以为纠错准备边界，不能代替错误修复、真实前向观察和历史影响重算。性能优化也需要单独测量，模块拆分本身不保证扫描更快或收益更好。

2026-10-03：记录初版方案，尚未创建上述业务模块。

2026-10-05：correctness 阶段完成三批合并（PR #1–#3）并进入 pre-E01 closure。E01 正式实施顺序更新为：
1. 冻结当前离线基线与跨 scanner/backtest characterization；
2. 抽取 `config.py`，保持 PR #3 契约零行为漂移；
3. 抽取 data/http/cache/Alpaca/SEC；
4. 统一 fundamentals/features；
5. 再迁 strategy/reporting/evaluation/workflows。

每批记录迁移提交、兼容 re-export、验收结果及预期零差异；不要在机械移动 PR 中顺手修改 E04/T04 等模型语义。
