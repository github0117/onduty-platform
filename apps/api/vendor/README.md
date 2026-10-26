# Vendored runtime overlay

`langgraph/` and `langgraph-runtime.pth` are copied into the Docker image by
`Dockerfile`:

- `langgraph/` is a LangGraph 1.0.9 runtime tree;
- `langgraph-runtime.pth` adds it to `sys.path` inside the container.

`uv.lock` resolves LangGraph 1.2.17 for local development and CI, so container and
local runs currently use different LangGraph versions. Before changing either side,
update the overlay and the lockfile together, or remove the overlay and pin the
runtime version in `pyproject.toml` / `uv.lock`.
