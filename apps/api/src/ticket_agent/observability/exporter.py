from collections.abc import Mapping, Sequence

from ticket_agent.shared.errors import ApiProblem
from ticket_agent.shared.rate_limit import rate_limit_rejection_total
from ticket_agent.shared.settings import Settings


def authorize_metrics(
    authorization: str | None,
    settings: Settings,
) -> None:
    if settings.app_env == "production" and not settings.metrics_scrape_token:
        raise ApiProblem(
            status_code=503,
            code="METRICS_NOT_CONFIGURED",
            title="Metrics authentication is not configured",
            detail="METRICS_SCRAPE_TOKEN is required in production.",
        )
    if not settings.metrics_scrape_token:
        return
    scheme, separator, token = (authorization or "").partition(" ")
    if (
        separator != " "
        or scheme.lower() != "bearer"
        or token != settings.metrics_scrape_token
    ):
        raise ApiProblem(
            status_code=401,
            code="UNAUTHENTICATED",
            title="Metrics authentication failed",
            detail="A valid Bearer token is required to scrape metrics.",
        )


def render_prometheus_metrics(
    *,
    sync: Mapping[str, object],
    rag: Mapping[str, object],
    tools: Mapping[str, object] | None = None,
    models: Mapping[str, object] | None = None,
    labels: Mapping[str, str] | None = None,
) -> str:
    return render_labeled_prometheus_metrics(
        [
            (
                labels or {},
                sync,
                rag,
                tools or _empty_tool_metrics(),
                models or _empty_model_metrics(),
            )
        ]
    )


def render_labeled_prometheus_metrics(
    series: Sequence[
        tuple[
            Mapping[str, str],
            Mapping[str, object],
            Mapping[str, object],
            Mapping[str, object],
            Mapping[str, object],
        ]
    ],
) -> str:
    if not series:
        raise ValueError("At least one metrics series is required")
    metric_specs = [
        (
            "ticket_worker_sync_attempted",
            "Tickets with external synchronization attempted.",
            "attempted",
            "sync",
        ),
        (
            "ticket_worker_sync_pending",
            "Tickets waiting for external synchronization.",
            "pending",
            "sync",
        ),
        (
            "ticket_worker_sync_syncing",
            "Tickets currently synchronizing externally.",
            "syncing",
            "sync",
        ),
        (
            "ticket_worker_sync_retrying",
            "Tickets waiting for a sync retry.",
            "retrying",
            "sync",
        ),
        (
            "ticket_worker_sync_succeeded",
            "Successfully synchronized tickets.",
            "succeeded",
            "sync",
        ),
        (
            "ticket_worker_sync_failed",
            "Permanently failed external synchronizations.",
            "failed",
            "sync",
        ),
        (
            "ticket_worker_sync_success_rate",
            "Success rate among terminal sync attempts.",
            "success_rate",
            "sync",
        ),
        (
            "ticket_worker_sync_failure_rate",
            "Failure rate among terminal sync attempts.",
            "failure_rate",
            "sync",
        ),
        (
            "ticket_worker_sync_average_attempts",
            "Average sync attempts per attempted ticket.",
            "average_attempts",
            "sync",
        ),
        (
            "ticket_worker_rag_drafts",
            "Generated answer drafts.",
            "draft_count",
            "rag",
        ),
        (
            "ticket_worker_rag_grounded_drafts",
            "Drafts with at least one knowledge citation.",
            "grounded_count",
            "rag",
        ),
        (
            "ticket_worker_rag_grounding_rate",
            "Fraction of drafts with knowledge citations.",
            "grounding_rate",
            "rag",
        ),
        (
            "ticket_worker_rag_policy_citation_coverage",
            "Fraction of policy claims with citations.",
            "policy_citation_coverage",
            "rag",
        ),
        (
            "ticket_worker_rag_semantic_verified_claims",
            "Claims verified as semantically supported.",
            "semantic_verified_claim_count",
            "rag",
        ),
        (
            "ticket_worker_rag_semantic_unsupported_claims",
            "Claims judged semantically unsupported.",
            "semantic_unsupported_claim_count",
            "rag",
        ),
        (
            "ticket_worker_tool_calls",
            "Digital employee tool calls.",
            "calls",
            "tools",
        ),
        (
            "ticket_worker_tool_succeeded",
            "Successful tool calls.",
            "succeeded",
            "tools",
        ),
        (
            "ticket_worker_tool_failed",
            "Failed tool calls.",
            "failed",
            "tools",
        ),
        (
            "ticket_worker_tool_denied",
            "Permission-denied tool calls.",
            "denied",
            "tools",
        ),
        (
            "ticket_worker_tool_success_rate",
            "Tool call success rate.",
            "success_rate",
            "tools",
        ),
        (
            "ticket_worker_tool_failure_rate",
            "Tool call failure and denial rate.",
            "failure_rate",
            "tools",
        ),
        (
            "ticket_worker_tool_average_duration_ms",
            "Average tool call duration in milliseconds.",
            "average_duration_ms",
            "tools",
        ),
        (
            "ticket_worker_tool_p95_duration_ms",
            "P95 tool call duration in milliseconds.",
            "p95_duration_ms",
            "tools",
        ),
        (
            "ticket_worker_model_calls",
            "Model gateway calls.",
            "calls",
            "models",
        ),
        (
            "ticket_worker_model_succeeded",
            "Successful model gateway calls.",
            "succeeded",
            "models",
        ),
        (
            "ticket_worker_model_failed",
            "Failed model gateway calls.",
            "failed",
            "models",
        ),
        (
            "ticket_worker_model_denied",
            "Model gateway calls denied by employee budget.",
            "denied",
            "models",
        ),
        (
            "ticket_worker_model_input_tokens",
            "Input tokens consumed by model gateway calls.",
            "input_tokens",
            "models",
        ),
        (
            "ticket_worker_model_output_tokens",
            "Output tokens consumed by model gateway calls.",
            "output_tokens",
            "models",
        ),
        (
            "ticket_worker_model_total_tokens",
            "Total tokens consumed by model gateway calls.",
            "total_tokens",
            "models",
        ),
        (
            "ticket_worker_model_estimated_cost",
            "Estimated model gateway cost in configured currency.",
            "estimated_cost",
            "models",
        ),
        (
            "ticket_worker_model_budget_exceeded",
            "Employees whose current model usage exceeds a configured budget.",
            "budget_exceeded",
            "models",
        ),
        (
            "ticket_worker_model_budget_forecast_alerts",
            "Employees projected to exceed a configured model budget.",
            "budget_forecast_alerts",
            "models",
        ),
    ]
    lines: list[str] = []
    for name, help_text, key, source_name in metric_specs:
        lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        for labels, sync, rag, tools, models in series:
            source = {
                "sync": sync,
                "rag": rag,
                "tools": tools,
                "models": models,
            }[source_name]
            rendered_labels = _render_labels(labels)
            lines.append(f"{name}{rendered_labels} {_number(source[key])}")
    # Process-local counter: each API replica reports its own rejected requests.
    lines.append(
        "# HELP ticket_worker_rate_limit_rejections_total "
        "Requests rejected by the shared rate limiter."
    )
    lines.append(
        "# TYPE ticket_worker_rate_limit_rejections_total counter"
    )
    lines.append(
        "ticket_worker_rate_limit_rejections_total "
        f"{rate_limit_rejection_total()}"
    )
    return "\n".join(lines) + "\n"


def _number(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "0"


def _empty_tool_metrics() -> dict[str, object]:
    return {
        "calls": 0,
        "succeeded": 0,
        "failed": 0,
        "denied": 0,
        "success_rate": 0.0,
        "failure_rate": 0.0,
        "average_duration_ms": 0.0,
        "p95_duration_ms": 0.0,
    }


def _empty_model_metrics() -> dict[str, object]:
    return {
        "calls": 0,
        "succeeded": 0,
        "failed": 0,
        "denied": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "estimated_cost": 0.0,
        "budget_exceeded": 0,
        "budget_forecast_alerts": 0,
    }


def _render_labels(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    parts = [
        f'{key}="{_escape_label(value)}"'
        for key, value in sorted(labels.items())
    ]
    return "{" + ",".join(parts) + "}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

