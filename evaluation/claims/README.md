# 主张验证评测

数据集使用 JSONL，每一行是一条人工标注主张：

```json
{"case_id":"claim-001","claim_text":"退款申请需要人工审核。","claim_type":"policy","sources":["退款申请需要人工审核。"],"expected_verdict":"supported"}
```

标注规则：

- `supported`：所有关键事实都能由引用来源直接推出。
- `unsupported`：存在来源未支持的新事实、数字、条件或承诺。
- `uncertain`：来源只提供部分信息，无法在不增加假设的情况下判断。

运行本地 Judge：

```bash
make claim-eval
```

使用环境变量中配置的外部 Judge：

```bash
make claim-eval CLAIM_PROVIDER=configured
```

报告包含 Macro-F1、三态混淆矩阵、覆盖率、选择性准确率和推荐的弃权阈值。
需要查看所有候选阈值时增加 `--include-sweep`。
真实数据集必须脱敏，并由至少一名业务人员和一名质量人员复核。

