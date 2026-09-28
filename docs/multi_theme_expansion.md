# 多主题扩张设计（医药 / 量子 / 核能 / 关键金属）

> 状态更新（2026-09-28）：**阶段 1 与阶段 2（路径 1）已完成**，五主题扫描端到端运行。
> 阶段 3（试点接入）待启动。路径 1 = theme_link 三组件版（披露权重 0）。

## 阶段 2 完成状态

| 组件 | 状态 |
|---|---|
| 组件权重参数化（`ai_link_weight_*` 四字段，默认=历史值，AI 配置零漂移） | ✅ 已上线 |
| 主题配置生成器（`generate_theme_configs.py` → `configs/config.theme.*.json` ×5） | ✅ |
| theme_link = 0.40×主题ETF共识 + 0.15×主题基准联动 + 0.10×backlog（披露归零，组合上限 0.65 保持阈值刻度） | ✅ CEG 逐项验证 0.331 |
| 主题ETF共识饱和度=篮子大小（核能 3、生物 3、稀土 1、量子 1、关键矿产 5） | ✅ |
| 快照隔离（`archive_watchlist_snapshots=false`，主题扫描不污染 AI PIT 序列） | ✅ 修复并测试 |
| 研究闸门主题化（weak_ai_link 不再排除；theme_only 可入 low_value，研究分下限 3.0） | ✅ |
| 五主题首扫结果 | 核能 lv=1/mo=7；量子 lv=1/mo=8；生物 lv=0/mo=2；稀土 lv=0/mo=1；关键矿产 lv=0/mo=10 |

## 已识别的校准积压（阶段 3 之前处理，按实证数据逐项）

1. **行业集中度上限**：`max_per_sector_per_list=3` 对单行业主题过严（生物 53 只过门只出 2-3 只——SIC 全在制药）→ 主题配置应放宽到 8-10 或按主题规模自适应
2. **研究池分数刻度 AI 化**：`research_pool_min_score=2.6` 下生物/稀土/关键矿产池为空 → 需主题分位数校准
3. **单 ETF 主题的共识退化**：稀土/量子 saturation=1 → 全员共识 1.0，区分度只剩 market_link/backlog/价值质量维度——已知且接受（ETF 成员资格=主题定义本身）
4. **量子篮子纯度**：QTUM 持有 NVDA 等超大盘 → 量子主题 low_value 选出 NVDA（watch）。观察期判断是否需要"纯净度"过滤（如剔除同时属 core_ai 的名字）或接受双主题成员
5. **研究评估器的主题语义**：ai_infrastructure_exposure 等标签仍按 AI 语汇打分 → 阶段 3+ 做每主题研究标签（nuclear_pure_play 等）

## 一、AI 纠缠触点的精确审计（哪里是障碍，哪里不是）

| # | 触点 | 位置 | 扩展时是障碍吗 | 精确结论 |
|---|---|---|---|---|
| 1 | **底单（ETF 持仓宇宙）** | 47 个 AI/工业 ETF 的持仓并集 | **是——最深的障碍** | 一只只被医药 ETF 持有的股票根本不在 680 只底单里，后续一切无从谈起 |
| 2 | **通道桶（core/enabler/peripheral/smallcap）** | `channel_bucket_match` 硬门 | **是** | 桶按 AI ETF 分组定义；纯医药股没有桶 → 被硬门排除 |
| 3 | `min_ai_link_score` | **软维度**（scored 架构下非硬门——已实测验证） | 半 | 只压 soft_pass_count 和评分，不直接淘汰 |
| 4 | `ai_link_score` 评分权重 | low_value 0.12~0.15、momentum 0.25 | **是** | 非主题股 ai_link≈0 → 系统性排名压制 |
| 5 | `weak_ai_link` 研究风险 | `low_value_excluded_research_risks` | **是（真·硬排除）** | 医药股必然带上 weak_ai_link 标签 → 直接被排除出 low_value 主清单 |
| 6 | `min_watchlist_etf_count` | 软维度 | 半 | 同 3 |
| 7 | QQQ 熔断/基准 | `benchmark_trend_filter` | **需按主题替换** | 医药主题用 QQQ 做主熔断语义不对（需 XBI/IBB 类基准 + QQQ 保留为全市场层） |

**实测的"泄漏"现状**：当前底单 680 只中已有 **133 只非 AI 主题股**（靠 XLU/XLB/COPX/URA/ITA 等工业 ETF 混入），其中 EME/FCX/PYPL/NUE/STLD 已成为 low_value keep、VST/GE/PWR 进入 momentum、CEG/BWXT/CCJ 挂在 research pool——**系统已经在通过"AI 基建外设"视角部分捕捉核能/金属/电力主题**。它们的 ai_link 之所以不低（0.36~0.55），是因为 ai_link 实际测的是"与 AI 叙事的关联度"，而核电/铜/电力恰好是 AI 副主题。**这证明 ai_link 不是"AI 教条过滤器"，而是"主题中心度度量器"——前提是主题叙事覆盖该股票。**

## 二、核心架构洞察：什么可以复用，什么必须按主题重建

**完全可复用（已验证的资产，零改动）**：
- 全部 SEC/TTM 数据管道（7 家族不变量验证 PASS）
- 价值/质量/动量软评分体系、两层 scored 架构
- 价格特征、可交易性、triage 分层、momentum 五层
- 回测/IC/试点协议的 cohort 机制

**必须按主题重建（每个主题一套）**：
- 底单：主题 ETF 篮子（量子：QTUM/ARKQ 子集；核能：NLR/URA/URNM；医药：XBI/IBB/PPH；关键金属：COPX/REM/LIT/URA——多数篮子已存在成熟 ETF）
- 主题分引擎：`theme_link_score(theme)` = 主题 ETF 共识（0.40）+ 主题披露关键词组（0.35）+ 主题基准联动（0.15）+ backlog（0.10）——**四组件结构照搬 ai_link_score，只换输入**
- 主题基准熔断：QQQ 保留为全市场主熔断 + 主题基准（如 QTUM 路径）作第二层
- 关键词组：quantum（qubit/quantum computing/annealing）、nuclear（SMR/enriched uranium/reactor）、metals（rare earth/heavy rare earth/copper）、pharma（clinical trial/Phase III/NDA/BLA——注意医药的质量维度需要行业专用重定义，见下）

**主题间的本质差异（不能一刀切的地方）**：
- **医药是特例**：价值/质量维度需要行业专化——pipeline 期权不在报表里，`fundamental_quality_score`/`min_net_margin` 对临床前公司天然排斥。医药主题需要替换质量维度（如 pipeline 阶段替代部分财务质量）或明确定位为"盈利型医药（辉瑞/礼来类）"而非"临床前 Biotech"
- **量子/核能/金属与现有架构同构度高**：都是"叙事-资本开支-商品价格"驱动，价值/动量/主题中心度四组件可直接复用

## 三、AI Score 会不会是障碍——精确回答

**是障碍，但解法不是删除它，而是 per-theme 化它。** 依据：

1. **IC 实证（2021-2026）**：ai_link_score IC +0.080（t=5.7）、watchlist_etf_count +0.087（t=6.0）——**主题中心度是全系统最强的排名信号**，比任何估值维度都强；且组件级分析确认 etf_consensus 是主要贡献者（120d IC +0.13~0.15，t=11~13，下跌市同样强正 +0.12~0.15）
2. **泄漏证据**：核电/铜/电力股在底单里活得好好的（CEG research_score 6.1、FCX keep、VST momentum），因为它们有真实的 AI 副叙事——说明该分数测的是"与当代最强主题的关联度"而非"是不是 AI 公司"
3. **因此**：扩展到医药主题时，医药股的排名信号应该是**"医药中心度"**（XBI/IBB 共识 + 临床管线披露关键词 + 与医药基准联动）——同构的引擎、不同的输入。删除主题分会让新主题失去系统里最强的一类排名信号
4. **诚实边界**：该信号的 IC 是在 AI 牛市单一状态下测得的——"主题中心度泛化到其他主题也有预测力"是**假设**，必须按观察协议验证（新主题从 P0 纸面起步，不继承 AI 主题的证据等级）

**market_link 的对称跟随语义在主题引擎中保留**（2026-09-28 审计结论，README §5.3）：
设计意图是"相关性"（联动强度），方向归动量维度管、深熊归熔断管；分 regime 实证显示
"奖励跟随下跌"未造成伤害（下跌市 IC +0.01~+0.04，不显著为负）。各主题引擎的联动组件
沿用 `1 − |偏离|/容忍度` 结构，仅替换基准篮子。

## 四、迁移路径（三阶段，每阶段可独立停）

**阶段 1（最小验证，无代码改动）**：用现有系统 + 主题 ETF 篮子跑"影子扫描"——把核能（NLR/URA 持仓）、量子（QTUM 持仓）等主题股手工并入底单试验文件，观察它们在哪一层死掉（预期：channel_bucket_match 硬门全灭）。产出：各主题底单规模/质量清单。**这一步只需要 watchlist 刷新脚本加主题 ETF 列表，1-2 天。**

**阶段 2（主题引擎参数化）**：scanner 的四处 AI 硬编码常量参数化：
- `AI_DISCLOSURE_KEYWORD_GROUPS` → `THEME_KEYWORD_GROUPS[theme]`
- `ai_link_benchmark_etfs` → 按通道桶配置主题基准
- 通道桶语义放宽：`channel_bucket_match` 允许主题桶（`nuclear_core`、`quantum_core`...）
- score_weights 的 `ai_link_score` 键重命名为 `theme_link_score`（配置兼容：旧键读作 AI 主题）
预计 3-5 天。每主题一个配置文件：`config.theme.nuclear.json`（复用两风格结构：主题内再分 defensive/offensive）。

**阶段 3（试点接入）**：新主题按试点协议 P0 纸面起步（**不继承 AI 主题的 P2/P3 阶位**），每月独立 cohort 结算，两个季度后再决定是否并入主组合。**主题间相关性是新风险**：AI 与其副主题（核能/铜）相关性高，医药/量子与 AI 相关性低——后者才是真正的分散化收益来源。

## 五、对当前体系的两条即时建议

1. **不要为了扩展而削弱 AI 主题**——它的证据等级（IC t=5.7 + 试点运行中）是全系统最高的；扩展按独立 sleeve 走
2. **泄漏的 133 只已经给了免费样本**：CEG（核电+AI 数据中心）、FCX（铜+电网）这类"双叙事"股是主题引擎价值的天然验证集——阶段 2 落地后，对比它们的 theme_link_score(own) vs ai_link_score，可直接检验"主题中心度"假设
