# RAG 检索评测

数据集使用 JSONL，每行一个案例：

```json
{"query":"如何配置团队通知","business_unit_id":"bu_demo","expected_titles":["企业通知配置指南"],"expect_no_grounding":false}
{"query":"完全不存在的业务问题","business_unit_id":"bu_demo","expected_titles":[],"expect_no_grounding":true}
```

在已经完成知识入库的环境中运行：

```bash
cd apps/api
uv run --offline python scripts/evaluate_rag.py ../../evaluation/rag/sample_queries.jsonl --top-k 5
```

输出包括：

- Recall@K。
- MRR。
- 无依据查询准确率。
- 每个查询实际返回的文档标题。

数据集需要使用脱敏内容，不能把生产原文或敏感信息提交到仓库。

