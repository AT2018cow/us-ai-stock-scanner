# 三风格体系完善与调参 Roadmap

> 状态：Phase 3 完成（144 候选全部成功 + 准确性双重验证通过），待用户确认最小 promote，下一步 Phase 4
> 最后更新：2026-09-24
> 本文档是 risk_on / risk_off / balanced 三风格体系改造与调参的权威计划。

## Phase 3 完成记录（2026-09-24）

**运行概况**（Modal 云端，`--no-promote` 审阅制）：balanced 24 候选（$1.79 实测）+ risk_on 80 候选（momentum 空间）+ risk_off 40 候选（QQQ breaker），144/144 全部成功，总成本 ~$11（$20 预算内）。

**核心结论**：
1. **三风格假设获数据支持**：balanced 全候选全周期负超额（风格层弱势，参数不可救）；risk_on 全部 80 候选 up 段评分**全正**（+0.36~+0.44）；risk_off 全部 40 候选 down 段评分**全正**（+0.096~+0.110）——三风格各自在主场 regime 赚取超额，互为镜像。
2. **risk_on 唯一档位级发现**：Top 8 全部满足 `momentum_min_return_60d ≥ 0.10`（现产线 0.015，差近 7 倍）+ `min_price_to_sma200 ≥ 1.0`——与 Phase 0 的 risk_off momentum 观察、D1 专家预判三重收敛。建议 promote。
3. balanced / risk_off 参数区分度不足（std < 噪声），按防过拟合纪律不做微调 promote，仅记录方向。

## Phase 3 准确性审查（2026-09-24，用户质量关卡触发）

针对"cand_016 本地 0.442772 vs 云端 0.441612"的 0.00116 差异做了三路验证：

| 验证 | 方法 | 结果 |
|---|---|---|
| **云端确定性** | 同一候选（cand_016）云端独立重跑，对照 80 候选 batch 原值 | **逐位一致（差 0.0）**——云端计算确定、batch 内数据快照稳定、候选间排序公平 |
| **本地确定性** | 本地两次独立重跑 | 均 0.44277199439298315，完全一致 |
| **计算逻辑两端一致** | 冒烟 A（同数据时刻的本地 vs 云端） | 逐位一致——regime 评分/非重叠序列/评分公式实现正确 |

**差异根因定性**：两次运行间隔 1 天，本地 bars 在 9/24 重拉（mtime 证据），多出的 9/23-24 行情只影响 2026YTD 窗口 2-3 个事件的前瞻收益——量级与 0.00116 吻合。**结论：差异为数据版本口径差，非计算错误**。判定纪律：1e-3 的差异对确定性计算而言必须溯源，不能用"小"豁免（若为 off-by-one 类 regime 标记错误，同量级差异也会出现）。

**审计性发现与修复项**：(a) `--prune-backtest-artifacts` 默认 True 使 events 中间产物不保留，事后无法手工重算——深度审查需 `--no-prune` 重跑；(b) 审查中一个 verify 脚本补丁因 `str.replace` 静默未命中而误报成功（已识别）。教训：深度验证前显式加 `--no-prune`；脚本补丁必须 assert 命中。


## Phase 2 完成记录（2026-09-23）

**1. Regime 条件评分（`9a62c57`）**：backtest 每个 replay 时点打 PIT 基准动量标签（QQQ 60 日 trailing，无未来函数），写入 signals/events；`risk_on_rank_score` 只按上涨段事件评分（超额 0.45 + 胜率 0.25 + 参与度 0.15 − 波动 0.15），`risk_off_rank_score` 只按下跌段（超额 0.45 + 胜率 0.35 − 回撤超 15% 罚 0.20）；无 regime 标签时回退旧公式。Smoke 验证三 rank score 首次真正分离（risk_on +0.48 / risk_off +0.07 / balanced −3.22）。

**2. 窗口重叠修复**：风险统计（series_std / worst_dd）改用贪心非重叠事件子序列（gap = horizon×1.5 日历日），月度采样 + 60 天持有不再三连计同一行情；单元验证通过。

**3. 引擎复用优化**：fundamentals + bar_db 跨 base/loose/strict 场景共享——实测 loose/strict 场景加载时间从 ~2.5 分钟降到 +0s，每候选（4 窗口）省约 10 分钟。

**4. 动量参数空间**：`configs/tuner.param_space.momentum.json`（11 轴：per-channel momentum 门槛/SMA 距离/回撤/波动 + 全局结构参数），risk_on 的 Phase 3 调参空间就绪。

**5. Modal 执行器（`3135fe9`，代码就绪、联调受阻）**：
- 就绪项：`scripts/modal_executor.py`（候选级并行：每候选一个容器内完整 4 窗口 × 3 场景重放，镜像 pin 本地同版 pandas/numpy/requests，Volume `ai-scanner-cache` 已上传核对 680+680+83 文件，`.env` 密钥经 Modal Secret 注入）；`tune_parameters --executor modal` 已接线，评分/promote 全留本地，`run_candidate` 远端零改动复用。
- Bring-up 修复：`Volume.from_name(create_if_missing=False)` 是阻塞性存在检查（改用 True）；modal 1.5.5 无 `max_retries`；stdin 入口不可被 mount（真实脚本无此问题）。
- **阻塞项**：当晚本地到 Modal 的 Python API 通道（gRPC 长连接）整体不稳定——plain probe（无镜像/卷/密钥）曾 2 秒成功、随后挂起 >35 分钟，而 CLI 通道（volume create/put/ls）始终正常。与我们的代码复杂度无关。
- **处置**：按风险表预案，本地串行为默认路径；Modal 在网络环境正常时以 `--executor modal` 一键接入（对 Phase 3 是加速器而非阻塞项）。重试清单：白昼网络环境、代理设置（MODAL_* 相关环境变量）、或锁定 modal 客户端更早版本对照。


## Phase 1 复查记录（2026-09-23，进入 Phase 2 前的质量关卡）

| 复查项 | 结果 |
|---|---|
| 新参数 channel 解析链路（min_price_to_sma200 / min_range_position_52w） | ✓ risk_on 通道取到 1.02/0.70，balanced 保持 None 不受影响 |
| bars helpers 数学（scanner 端 close/SMA200） | ✓ 与手工逐位一致 |
| backtest 端 `benchmark_trend_ok_asof` 的 PIT asof 截断 | ✓ 与 QQQ 真实日线状态逐点一致（2025-03/04、2026-03 破线均正确识别） |
| `price_dimension_from_bars` 底层语义 | ✓（52w 区间用日内 high/low；days_below 为 trailing 连续天数；price_to_sma200 = 当前价/近 200 收盘均） |
| **breaker 挂载覆盖** | ✗ **发现真 bug**：QQQ 熔断只挂在 low_value 步骤，momentum 清单（risk_on 的 primary）与 trend 清单裸奔——2025-04-30 ED 信号在 QQQ 破线下发出 |

**bug 修复（81fe378）**：提取 `build_benchmark_trend_step` 公共步骤，挂载到 low_value / industry_trend / momentum 三个清单构建器；回归测试断言三清单的挂载/缺席。修复后重放验证：2025-04-30 momentum 信号被正确熔断（该笔为负超额交易，2025 年 momentum 超额 +4.1% → **+8.1%**）；2025-03、2026-03 破线月末亦无信号。

**教训**：D1-B 首次汇报中"QQQ breaker 正确休眠"的说法当时无法成立——primary 清单根本没挂载 breaker，无从触发。用户要求复查的决定再次避免了把缺陷带入 Phase 2/3。


## Phase 1 数据复核结论（2026-09-22，决策前验证）

对"momentum 清单 2025 年 +11.4% 超额"这一 B 路线关键证据做了原始事件级复核：

- **数字与计算准确**：segments 聚合与原始事件手工重算逐位一致（+0.1136），15bp 交易成本已计入。
- **但统计构成不支持强结论**：8 个信号中，正超额几乎全部由 **AMAT 单一股票 9-11 月的三个重叠信号**贡献（+22.7%/+45.3%/+50.6%，60 天持有 + 月度采样导致同一波行情被计入 3 次）；剔除后其余 5 个事件均值约 **−5.6%**。2023-2025 有效独立标的仅约 5 只。
- **撤回的引用**：risk_off momentum 2025 +11.7%（n=3）、2026YTD +26%（n=2）——样本量不具备任何统计意义。
- **系统性口径缺陷（记入 Phase 2）**：60 天持有期 + 月度采样存在**窗口重叠**，`avg_excess_vs_QQQ` 的"事件均值"会重复计数同一行情；Phase 2 评分函数需引入非重叠口径或按资金占用周期加权。

**修正后的 B 路线依据**：
1. **主要依据（不依赖回测数值）**：架构理由——momentum 清单（`build_momentum_steps`）原生趋势语义（过滤/评分/回测/调参基础设施全部现成），优于在 low_value 价值框架内连续打补丁的 A'。
2. 2025 年 momentum(±) vs low_value(−9.4%) 的相对方向仅作"方向性参考"，置信度受限；风格有效性的最终验证依赖 Phase 3 大候选调参 + watchlist 快照积累后的无前视回测。
3. **教训记录**：数字准确 ≠ 证据充分——决策级引用必须先做事件级复核（本次追问触发，避免了基于单票噪音的路线选择）。

## Phase 1 完成记录（B 路线最终形态）

**引擎（已提交 d7bfb40）**：`min_price_to_sma200`、`min_range_position_52w` 过滤步骤；`benchmark_trend_filter_symbol`（QQQ 绝对动量开关，scanner + PIT backtest 双端，fail-open）。

**配置与约定**：
- **risk_on = 双动量结构**（Antonacci Dual Momentum 映射）：QQQ 绝对动量做开关（QQQ < 自身 200 日线时不出任何信号）+ momentum 清单做相对选择。**risk_on 的 primary 清单 = momentum 清单**（`..._ranked_momentum.csv`）；其 low_value 清单保留 A 路线的趋势镜像参数作为辅助观察（退居次要）。momentum 清单参数调优（向 risk_off 的更严门槛方向探索）留给 Phase 3 动量轴调参。
- **risk_off = 低吸 + QQQ 熔断**：保留防守基本面，QQQ 破线时整体熄火。
- **balanced = 低吸回调 + 质量（不变）**。
- README 的风格权威说明在 Phase 4 promote 时统一更新（避免迭代期文档漂移）。

**测试**：风格镜像 4 项 + 双动量开关归属断言（balanced 无开关，risk_on/risk_off 均挂 QQQ breaker）。

**D1 判定（B 路线）**：以架构依据 + 方向性证据通过；D1-B 数值验证回测（risk_on 启用 breaker 后 momentum 清单 2023-2026 重放）结果记录见下。

**D1-B 验证结果（2026-09-22，monthly × 4 窗口，base 场景，60 天超额 vs QQQ）**：

| 年度 | risk_on momentum（B 路线 primary） | risk_on low_value（A 路线，退居辅助） | 判读 |
|---|---|---|---|
| 2023 | −3.1% | −2.8% | 均微负 |
| 2024 | +1.2% | −3.1% | B 略优 |
| **2025** | **+4.1%**（9 信号） | **−11.8%**（2 信号） | B 显著优 |
| **2026YTD** | **+3.9%**（3 信号） | **−9.3%**（2 信号） | B 显著优 |

- momentum primary 在 2025/2026 动量段正超额且信号密度健康（8-9 事件/年 vs A 路线 low_value 的 2-6）；
- QQQ breaker 在 2023-2026 窗口内未触发（QQQ 基本处于 200 日线上方），属正确行为——其对 2022 型熊市的保护作用需等窗口扩展或快照积累后验证；
- risk_on momentum（+4.1%）弱于 balanced momentum（+11.4%，含 AMAT 噪音）——确认 risk_on 的基本面宽容度稀释了动量池质量，**Phase 3 动量轴调参应向更严门槛探索**（借鉴 risk_off momentum 的门槛模式）；
- 同样适用小样本/重叠窗口的统计限制——本表作为路线对比依据（B vs A 同口径），不作为收益预期。


**已完成**：
- 引擎新增 `min_price_to_sma200`、`min_range_position_52w` 过滤步骤（趋势确认对称参数）与 `benchmark_trend_filter_symbol`（QQQ 绝对动量熔断，scanner + backtest PIT 双端）。
- risk_on 配置镜像化（A 路线）：低吸结构参数全部反转为趋势确认（price≥1.02×SMA200、52w 位置≥70%、r20≥3%、r60≥5%、放开追涨上限与新高中上限）。
- risk_off 启用 QQQ trend filter。
- 特征镜像测试 4 项全过（balanced 拒趋势股留低吸股；risk_on 拒低吸股留趋势股；trend filter 熔断/fail-open 语义）。全套 74 测试通过。

**A 路线（已实施并保留为辅助）D1 首验数据（monthly × 4 窗口，60 天超额 vs QQQ）**：

| 年度 | risk_on 基线 | risk_on A 路线改造后 | 判读 |
|---|---|---|---|
| 2023 | −5.1% | −2.8% | 略改善 |
| 2024 | +0.8% | −3.1% | 恶化 |
| 2025 | −10.2% | **−11.8%** | 未达预期（更差） |
| 2026YTD | +5.0% | **−9.3%** | 大幅恶化 |

根因：估值-动量冲突（镜像了结构参数但保留 balanced 估值硬门槛，44 期仅 15 个信号）、空仓机会成本（29/44 空仓期在 QQQ 上涨年累积负超额）、风格方向正确但表达能力不足（选出确为趋势股：KLAC/TXN/AMAT/MU/ACN）。**结论：A 路线效果不足，按预设升级 B。**


## 0. Phase 0 诊断结论（2026-09-22 完成）

三配置各跑 monthly × 2023-2026YTD × 3 场景 historical_replay（latest-fallback），产出 `outputs/_diag_*_{summary,segments,events,events_signals}.csv`：

**Regime 适配性矩阵（low_value 主清单, base 场景, 60 天持有期, vs QQQ 超额）**：

| 年度 | balanced | risk_on | risk_off |
|---|---|---|---|
| 2023 | −5.1% | −5.1% | −5.9% |
| 2024 | +0.4% | +0.8% | +0.1% |
| 2025（动量年） | **−9.4%** | **−10.2%** | **−9.9%** |
| 2026YTD | +8.1% | +5.0% | +8.1% |

**信号重叠度（base 场景 low_value 清单，(日期,标的) Jaccard）**：
- balanced vs risk_on：**93.5%**
- balanced vs risk_off：87.6%；三配置完全一致的信号占并集 **84.8%**

**结论（D0 通过）**：三风格同质化被完全证实——risk_on 在 2025 动量年不仅没有跑赢 balanced，反而更差（−10.2% vs −9.4%）；三配置 85-94% 的信号选的是同一批股票。所谓三配置实为同一"低吸回调"风格的三档基本面容忍度，**Phase 1 框架差异化改造必要性成立**。

诊断注意：样本量小（每配置 89 个信号组合）、latest-fallback 前视偏差仍在（快照积累中）、monthly 采样 44 点。结论方向可信，绝对数字仅作量级参考。

## 1. 全局视角：目标态 vs 当前态

### 目标态（风格化三支柱）

| 配置 | 风格定位 | 盈利来源 | 调参目标 |
|---|---|---|---|
| **balanced** | 低吸回调 + 质量 | 价值回归 | 全周期稳定性 + 正超额 |
| **risk_on** | 趋势 / 动量跟随 | 趋势延续 | 上涨 regime 超额 QQQ |
| **risk_off** | 防守 + 绝对动量过滤 | 崩坏市少亏 | 下跌 regime 回撤控制 |

体系超额 = 三风格低相关分散（价值/质量因子与动量因子长期负相关，Fama-French 五因子 + Carhart）。

### 当前态（2026-09 诊断）

- 引擎数据层已修复（7 个数据/逻辑 bug，70 单测全绿）：dei 命名空间、跨 tag 最新期、千股单位检测、stale 股本置空、abs(accrual) 符号、left_side_watch、backtest PIT 同步。
- PIT watchlist 快照机制已上线（每次扫描自动归档 `data/watchlist_history/`），从 2026-09-22 起积累。
- **结构性问题（已证实）**：risk_on 的动量/价格参数与 balanced 逐项相同（`min_days_below_sma200=5`、`max_20d_return=0.12`、momentum 清单参数一致），差异仅在基本面容忍度——三配置是"同一低吸风格的三档宽容度"，不是三种风格。
- **回测证据（monthly × 3 候选粗搜，2026-09-22）**：balanced 风格 2023-2026 全周期 vs QQQ 超额约 −2.7%；2025 窗口 primary_score −16.7%（普涨动量年低吸风格系统性跑输）。
- `tuner.param_space.json` 13 轴全部是质量/估值轴，无动量/价格结构轴——risk_on 无参可调。
- tune 目标函数为全周期统一，会把三配置拉向趋同。

### 核心原则

调参是最后一步。结构工程（风格差异化、目标函数 regime 化）未完成前，调参只是在三个孪生配置间做无意义的微调。

## 2. 计算基础设施：Modal 云执行

本地基准机仅 2 vCPU / 3.8GB（单进程串行），weekly×36 候选约 33 小时。tune 的任务结构为天然可分片（候选 × 窗口 = 独立 backtest 任务，纯 CPU + 读缓存，无 API 依赖），采用 Modal 云并行：

| 规模 | 本地（2核串行） | Modal（~144 vCPU 并行） | Modal 成本 |
|---|---|---|---|
| monthly × 12 候选 | ~11.6h | ~15 分钟 | ~$3-5 |
| weekly × 36 候选 | ~33h | ~45-90 分钟 | ~$10-15 |
| weekly × 200+ 候选 | 不可行 | ~2-4 小时 | ~$20-50 |

Modal 化的前提与一次性成本：
1. Modal 账号 + API token；Alpaca/SEC 密钥经 Modal Secrets 托管（cache 齐全时几乎无 API 调用）；
2. `cache/`（~2.6GB）首次上传 Modal Volume；之后每次 tune 前增量同步（脚本化，分钟级）；
3. 改造：候选×窗口评估循环提取为可序列化独立函数 + Modal App 包装 + 结果回传合并（约 1-2 天开发调试，列入 Phase 2.4）。

风险提示：按秒计费模式匹配"间歇性批量调参"；不为该规模计算租常驻服务器。

## 3. 分阶段计划

### Phase 0 —— 诊断基线（0.5-1 天，本地）

| 任务 | 产出 | 成本 |
|---|---|---|
| 三配置 regime 适配性矩阵（balanced/risk_on/risk_off 各跑 monthly × 2023-2026YTD） | 配置 × 年度收益/超额矩阵 | ~2h（本地串行） |
| 风格相关性基线（三配置信号标的重叠度） | 重叠度报告 | <0.5h |

**决策门 D0**：证实 risk_on 在 2025 类动量年同样跑输（风格同质化证据）→ 进入 Phase 1。

### Phase 1 —— 框架差异化（2-3 天，代码+配置）

1. **risk_on 改造为趋势/动量风格**（核心工程）：
   - 结构参数镜像：`min_days_below_sma200: 5→0`、`max_20d_return` 放宽、回撤要求反向（接近新高而非深回调）、价格位于 200 日线上方为必要条件；
   - 实现路线（Phase 1 内定夺）：A. low_value 主清单 per-regime 结构覆盖（配置层表达，改动小）；B. momentum 清单升级为 risk_on primary（更彻底）。倾向 A 起步。
   - 风格特征验证测试：risk_on 选股必须"站上 200 日线、距新高近、r20 正"（与 balanced 特征镜像）。
2. **risk_off 加绝对动量过滤**：基准（QQQ）低于自身 200 日线时不出信号——体系熔断器，对冲 risk_on 的动量崩塌尾部风险。
3. 产出：三个差异化配置 + 特征镜像测试 + README 更新。

**决策门 D1**：重跑 Phase 0 矩阵，risk_on 在动量年显著优于 balanced。

### Phase 2 —— 参数空间、目标函数与云化（2-3 天，代码）

1. **param_space 扩展**：加入动量/价格结构轴（per-channel `momentum_min_return_20d/60d`、`max_price_to_sma200`、`min_days_below_sma200`、`max_20d_return`），仅对 risk_on 评分激活。
2. **tune 目标函数 regime 条件化**（关键改动）：
   - regime 标记：QQQ 60 日动量分段；
   - risk_on 只在上涨段计分（超额 QQQ）；risk_off 只在下跌/高波动段计分（回撤控制）；balanced 全周期（stability + 正超额）；
   - 新增风格相关性惩罚：三清单信号重叠度 >70% 时扣分。
3. **引擎性能优化**：fundamentals 跨场景/窗口复用（实测约 38% 纯浪费）。
4. **Modal 云执行化**：评估循环提取 + App 包装 + Volume/Secrets + 结果合并。

**决策门 D2**：3 候选 × monthly 冒烟验证新评分与云执行（~30 分钟）。

### Phase 3 —— 三风格分层调参（1-2 天，Modal 计算）

| 顺序 | 风格 | 规模（Modal 后） | 墙钟 |
|---|---|---|---|
| 3.1 | balanced | weekly × 200+ 候选 | ~1h |
| 3.2 | risk_on（动量轴） | 同上 | ~1h |
| 3.3 | risk_off（含 trend filter） | 同上 | ~1h |

**防过拟合纪律**：
- `--no-promote`，全量人工审阅后推进；
- 参数结论必须跨 4 窗口方向一致（window_stability 权重把关）；
- 只信档位级差异，不微调小数位；
- 风格相关性 <70% 硬门槛。

**决策门 D3**：三组参数通过一致性 + 相关性检验 → Phase 4。

### Phase 4 —— 体系级验证与 promote（1-2 天）

- 组合级回测：三风格并行（等权或风险预算加权）的体系收益/回撤 vs 纯 QQQ；
- walk-forward 样本外确认；
- promote 三配置 + 文档（风格说明、适配 regime、参数依据）。

**决策门 D4（最终门）**：体系组合 2023-2026 全周期跑赢 QQQ 且最大回撤更浅 → 上线。

### Phase 5 —— 持续运营机制

| 机制 | 内容 | 频率 |
|---|---|---|
| PIT 快照积累 | 已自动化；6-12 个月后 strict-mode historical_replay 可用，摆脱 latest-fallback 前视偏差 | 自动 |
| 重调参 | 基于 Modal + 新快照（无前视）三风格重 tune | 季度 |
| calibrate | 日常产出量维护（tune 之后使用） | 随扫描 |
| 风格漂移监控 | 三清单信号重叠度与特征镜像性回归测试 | 每月 |
| 引擎回归 | 70+ 单测全绿为 promote 前置条件 | 每次改动 |

## 4. 时间线概览（Modal 版）

```
第 1 周：Phase 0（0.5-1天）→ Phase 1（2-3天）─────── 决策门 D1
第 2 周：Phase 2（2-3天，含 Modal 化）────────────── 决策门 D2
第 3 周：Phase 3（3 × ~1h 云计算 + 审阅）─────────── 决策门 D3
第 4 周：Phase 4（1-2天）────────────────────────── 决策门 D4 上线
之后：Phase 5 机制化运营
全程约 2-3 周（人工介入 ~6-9 天，云计算 ~$20-50 量级）
```

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 过拟合（每窗口仅 10-12 个信号事件） | regime 条件评分减少自由度；档位级差异；跨窗口一致性硬门槛；大候选空间广采样（Modal 使之可行） |
| 动量风格尾部风险（risk_on 遇动量崩塌） | risk_off 绝对动量过滤为体系熔断器；组合层面等权分散 |
| 前视偏差（backtest watchlist fallback） | 唯一解是快照积累（已自动化），不阻塞其他 Phase，但每日不积累即永久损失 |
| Modal 依赖（账号/额度/网络） | 本地串行路径保留为 fallback；Volume 同步脚本化 |

## 6. 关键文档与产物索引

- 引擎修复历史：git log（`5a20871` → `5e23206` 等 8 个提交）
- 粗搜基线：`outputs/tuning_20260922T021434Z_*`（monthly × 3 候选，2026-09-22）
- Phase 0 诊断产物：`outputs/backtest__diag_*`（见 Phase 0 报告）
- 快照目录：`data/watchlist_history/`
