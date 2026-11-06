# 执行与复现

本次结果身份：`ai-scanner-research:/review_followup_20261106_v1/`。源数据仍为`/sip_migration_20261106_v1/datasets/`，修复计划固定本目录repair_plan.json。不得删除、改写旧研究或正式快照。

以下为实际前台运行入口，每个阶段先smoke，已完成且规格相同的检查点会验证输入、源码与配置后复用；不匹配立即停止。修改代码/配置后应使用新的run-id，不能绕过检查继续沿用旧身份。

```sh
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_review_fixes.py --stage repair
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_review_fixes.py --stage evaluate
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_review_fixes.py --stage attribute
```

已下载至gitignored `outputs/review_followup_20261106/`，独立检查可在仓库根目录复现：

```sh
.venv/bin/python docs/review_followup_20261106/verify_label_repair.py
.venv/bin/python docs/review_followup_20261106/verify_evaluation.py
.venv/bin/python -m unittest discover -s tests -p test_review_followup_20261106.py
.venv/bin/python -m unittest discover -s tests
```

离线评估支持仓库外CSV；metadata与CSV同名不同后缀，存在时一起登记和校验。输出必须是新目录，写入失败不会发布半成品目录：

```sh
.venv/bin/python scripts/evaluate_current_top15.py \
  --dataset outputs/review_followup_20261106/datasets/sip_2016_2020_v1/dataset.csv \
  --dataset outputs/review_followup_20261106/datasets/sip_2021_2026_v1/dataset.csv \
  --output outputs/review_followup_20261106/reproduced_monthly
```

本目录SHA256SUMS固定本次可审查证据。重新生成证据应先选择新的证据目录/身份，避免将未来的源码或数据混入本次验收记录。
