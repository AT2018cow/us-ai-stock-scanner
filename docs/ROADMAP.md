# 三风格体系完善与调参 Roadmap

> 状态：Phase 0 已完成（决策门 D0 通过），下一步 Phase 1
> 最后更新：2026-09-22
> 本文档是 risk_on / risk_off / balanced 三风格体系改造与调参的权威计划。

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
