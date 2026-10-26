FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.5 /uv /uvx /bin/

ARG APT_MIRROR=https://mirrors.aliyun.com
ARG PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_DEFAULT_INDEX=${PYPI_INDEX_URL}

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

RUN sed -i "s|http://deb.debian.org|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY alembic.ini ./
COPY migrations ./migrations
COPY scripts ./scripts
COPY assets ./assets
COPY src ./src
COPY vendor/langgraph /app/vendor/langgraph
COPY vendor/langgraph-runtime.pth /app/.venv/lib/python3.11/site-packages/langgraph-runtime.pth
RUN uv sync --frozen --no-dev
RUN uv pip install --python /app/.venv/bin/python --no-cache \
    "charset-normalizer==3.5.2" \
    "orjson==3.13.0" \
    "ormsgpack==1.13.0" \
    "uuid-utils==0.18.0" \
    "xxhash==4.0.2" \
    "zstandard==0.25.0" \
    "rpds-py==2026.6.3"

ENV PATH="/app/.venv/bin:$PATH"

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /var/lib/ticket-agent \
    && chown app:app /var/lib/ticket-agent

USER 10001:10001

EXPOSE 8000

CMD ["uvicorn", "ticket_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]

