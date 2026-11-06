# 执行与断点恢复

下列Modal命令记录本次实际执行顺序，均为infi前台；目录是不可变身份，已有完整结果时不要盲目重跑同名生成阶段。长阶段在入口内先执行smoke。冻结卷根为`ai-scanner-research:/sip_migration_20261106_v1/`，原输入仍为`/selection_review_20261106/`，原始行情缓存仍在独立SIP研究缓存目录。

```sh
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_sip_migration.py --stage relabel
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_sip_migration.py --stage evaluate
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_sip_migration.py --stage attribute
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_sip_migration.py --stage official
```

本次official计算已完成，末尾校验缺包路径；使用下列**仅校验**入口从完整不可变快照恢复，成功后显式commit研究卷/缓存卷。入口要求快照非空、所有记录来源均为SIP/sip_eod，并独立校验，不重跑行情/SEC：

```sh
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_sip_migration.py --stage official_validate
```

每个数据集的success.json和dataset.meta.json保留原数据集SHA256、新标签合同、原始缓存哈希和拆股来源。大输出已下载至`outputs/sip_eod_migration/{relabelled,evaluations,attribution,official_decisions,official_outputs}/`；不要把缓存/数据树加入Git。哈希清单与紧凑证据保存在本目录。

日常正式运行命令不变：

```sh
.venv/bin/python run_scan.py --config configs/config.production.json
.venv/bin/python scripts/run_daily_cron.py --config configs/config.production.json
```

同日旧IEX快照继续保持不可变；当天查看迁移后名单与IEX监控：

```sh
.venv/bin/python scripts/validate_mvp_snapshot.py \
  outputs/sip_eod_migration/official_decisions/2026-11-05/production
.venv/bin/python scripts/intraday_watch.py \
  --snapshot-dir outputs/sip_eod_migration/official_decisions/2026-11-05/production
```

下载后的离线数值复现应写入新目录；标签CSV必须连同.meta.json使用。使用同一冻结输入、不重新拉财务和价格：

```sh
.venv/bin/python scripts/evaluate_current_top15.py \
  --dataset outputs/sip_eod_migration/relabelled/sip_2016_2020_v1/dataset.csv \
  --dataset outputs/sip_eod_migration/relabelled/sip_2021_2026_v1/dataset.csv \
  --output outputs/sip_eod_migration/reproduced_sip_monthly
.venv/bin/python -m unittest discover -s tests
```

旧IEX研究没有作为当前生产结果重新推广；需要新的研究身份时使用新输出目录，遇到输入/源码/合同不匹配停止，不能删除或覆盖旧证据来强行续跑。
