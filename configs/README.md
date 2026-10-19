# `configs/` —— 配置地图与命名约定

## 1. 两个概念

- **生产策略（Production）** = `config.production.json`：**唯一生产入口**（每日 cron / 正式扫描 / 正式报告）。
- **档案（Profile）** = 一组参数 + 一个 `strategy_style` 身份。生产策略当前使用防守档 `risk_off` 的参数；`risk_on` 是进攻档（研究/观察，不在生产路径）。

> `strategy_style`（以及快照路径里的 `production` / `risk_off`）是**档案身份（provenance identity）**，用于快照目录、`latest_*.json` 指针、R08 版本门与回放元数据；**它不是市场状态判断**。

## 2. 配置清单

| 文件 | `strategy_style` | 状态 | 用途 |
|---|---|---|---|
| `config.production.json` | `production` | ✅ **唯一生产入口** | cron / 正式扫描 / 正式报告；有效参数与 `config.risk_off.json` 逐字段一致（漂移测试保证） |
| `config.risk_off.json` | `risk_off` | ✅ 生产档案（模板） | 防守档：低吸回调 + 质量硬门槛 + QQQ 深度熊市熔断；保留用于回放/研究/复现 |
| `config.risk_on.json` | `risk_on` | 🧪 研究/观察 | 进攻档：双动量结构（QQQ 绝对动量开关 + momentum 清单）；**不在生产路径** |
| `config.strict_candidate.json` | — | 候选 | 基于 strict-list 复核参数，不自动使用 |
| `config.theme.*.json` / `config.venture.*.json` | — | 研究 | 主题/风投扫描 |
| `theme_universe.json` | — | 数据 | 主题宇宙定义 |
| `archive/` | — | 历史 | 归档配置；**不要作为运行入口** |

历史背景：2026-09-24 起的两风格架构（`risk_off` + `risk_on`）为当时的观察协议服务；进攻需求现由报告内的 Offense Track 卫星栏承载，生产保持单一。观察协议与风格演化史见 `docs/archive/experiments/`。

`archive/` 中的 `config.production.legacy.json` 是两风格时代之前的旧 production 预设（106 键、无 `strategy_style`），`config.production.root.json` 更早；两者仅历史留存，不得作为运行入口。

## 3. 身份与路径

| `strategy_style` | 快照路径 | 指针 |
|---|---|---|
| `production` | `outputs/decisions/<日期>/production/` | `latest_production.json` |
| `risk_off` | `outputs/decisions/<日期>/risk_off/`（**2026-10-20 之前的历史档案**） | `latest_risk_off.json`（历史） |
| `risk_on` | `outputs/decisions/<日期>/risk_on/`（观察期） | `latest_risk_on.json`（观察） |

- 历史快照不回迁、不修改；新快照一律写入 `production/`。
- 回测/研究数据集的文件名（如 `company_quality_dataset_risk_off.v3.csv`）记录的是生成时的档案身份，属于冻结证据，不改名。

## 4. 变更纪律

1. `config.production.json` 的有效参数必须与 `config.risk_off.json` 保持一致；`tests/test_config_validation.py` 会强制。改一个必须同步另一个（生产身份 `production` 除外）。
2. 不要新增 `strategy_style` 之外的风格标签；新增风格需同时更新 `src/ai_value_scanner/config.py` 的校验与 `src/ai_value_scanner/strategy/filtering.py` 的 `STYLE_STRUCTURAL_STEP_NAMES`。
3. `configs/archive/` 只读，不修改、不运行。
4. 生产命令统一使用 `--config configs/config.production.json`；研究/回放命令可显式使用 `config.risk_off.json`（档案）。
