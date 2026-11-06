# 执行与复现命令

这是回溯研究。方案v4及P0后的C联合得分修订均经用户批准；不写生产决策、配置或正式快照。运行身份为`value_pullback_20261106_v2`，infi前台，smoke先行，最多2个计算容器。

```bash
.venv/bin/python -m unittest discover -s tests -p test_value_pullback_directions.py

MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_value_pullback.py --stage smoke --run-id value_pullback_20261106_v2 --names D0,A,B,C
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_value_pullback.py --stage prepare --run-id value_pullback_20261106_v2 --names D0,A,B,C
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_value_pullback.py --stage evaluate --run-id value_pullback_20261106_v2 --names D0,A,B,C
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_value_pullback.py --stage robustness --run-id value_pullback_20261106_v2 --names D0,A,B,C
MODAL_PROFILE=infi .venv/bin/modal run scripts/modal_value_pullback.py --stage download --run-id value_pullback_20261106_v2 --names D0,A,B,C

.venv/bin/python scripts/finalize_value_pullback_review.py \
  --raw outputs/value_pullback_20261106/value_pullback_20261106_v2 \
  --output docs/value_pullback_optimization_20261106

.venv/bin/python -m unittest discover -s tests
```

`robustness`只为通过初筛的因素执行较重验证；无通过因素时输出有明确跳过原因的manifest。下载只取紧凑结果，不取决策pickle/检查点。首次下载要求目标目录不存在，防止混合旧产物。

Modal读取已有`ai-scanner-research` Volume中的`review_followup_20261106_v1`冻结数据与旧评估。CLI的本地等价入口是`evaluate_value_pullback_directions.py`，其参数见`--help`；长任务仍应使用Modal。

续跑检查源码、配置、协议、输入及结果文件哈希；任一身份不匹配即停止。新代码不能用旧run-id强行续跑。本次v1只用于初始smoke和未完成的准备计算；用户批准C修订后明确停止旧App，改用v2完整重跑，没有混合协议。

初始smoke出现的容器导入路径错误已修复，失败App已显式停止。该错误发生在长回测启动前。原始命令日志、完整成员表和检查点留在gitignored outputs与Modal Volume，不加入Git。

正式快照影子对照读取不可变决策，并从身份一致的本地解析缓存和SIP收盘缓存恢复必要字段，不发起行情/SEC请求。执行器同时检查SIP来源、实际出版时间、缓存版本、财务身份、市值一致性和阈值舍入歧义。

本目录manifest与SHA256SUMS记录可审查文件身份；本次不执行Git写操作。环境必须具备对应冻结输入及本地快照/缓存，不能将缺失输入自动换成更新数据。
