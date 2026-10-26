# Ticket Agent API

```bash
uv sync --all-groups
uv run uvicorn ticket_agent.main:app --reload
uv run pytest -q
```

默认使用本地 SQLite，便于在外部身份、模型和工单系统未就绪时开发业务闭环。

