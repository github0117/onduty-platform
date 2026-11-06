FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

# 默认走国际源，保证 GitHub Actions 等海外 runner 可构建；国内本地构建可传
# --build-arg PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
# --build-arg APT_MIRROR=https://mirrors.aliyun.com（compose 里从同名环境变量读取）。
ARG APT_MIRROR=
ARG PYPI_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_DEFAULT_INDEX=${PYPI_INDEX_URL}

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

RUN if [ -n "${APT_MIRROR}" ]; then \
        sed -i "s|http://deb.debian.org|${APT_MIRROR}|g" \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY assets ./assets
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# The image and CI both resolve LangGraph from uv.lock; fail the build if the
# graph API used by the reply-suggestion flow cannot be imported.
RUN python -c "import importlib.metadata as m; from langgraph.graph import END, START, StateGraph; print('langgraph', m.version('langgraph'), StateGraph.__module__)"

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /var/lib/ticket-agent/objects \
    && chown -R app:app /var/lib/ticket-agent

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "ticket_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

