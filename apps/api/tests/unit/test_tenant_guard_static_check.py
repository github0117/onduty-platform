"""Static ratchet for tenant isolation on HTTP routes.

Every route handler must enforce tenant ownership either by calling
``ensure_business_unit_access`` / ``resolve_business_unit`` (directly or via a
function in the same package it calls), or by being listed in
``ALLOWED_UNGUARDED`` with an explicit reason.

The check walks the call graph inside ``ticket_agent`` only. Service methods
and other classes are not traced, so handlers that rely on service-layer
checks are expected in the allowlist.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = API_ROOT / "src" / "ticket_agent"
PACKAGE_PREFIX = "ticket_agent."

GUARD_NAMES = frozenset({"ensure_business_unit_access", "resolve_business_unit"})
ROUTE_METHODS = frozenset(
    {"get", "post", "put", "patch", "delete", "route", "api_route", "websocket"}
)
DEPENDENCY_CALLS = frozenset({"Depends", "Security"})
MAX_DEPTH = 4

# Handlers that intentionally do not call the guard primitives.
# Keep this list small; remove entries when a handler starts guarding itself.
ALLOWED_UNGUARDED: dict[str, str] = {
    "main:health_live": "基础设施探针，全局可用，不读取租户资源",
    "main:health_ready": "基础设施探针，全局可用，不读取租户资源",
    "main:prometheus_metrics": "受 token 保护的全局指标端点，按设计不区分租户",
    "connectors.router:receive_connector_webhook": "外部系统签名回调，无用户身份上下文",
    "ecommerce.router:test_pinduoduo_connection": "全局渠道凭据检测，仅校验运营角色",
    "ecommerce.router:download_product_import_template": "返回静态 CSV 模板，无租户数据",
    "customer_service.router:reclaim_customer_conversation_turns": (
        "按操作员所属业务单元回收；Celery beat 保留全租户维护"
    ),
    "agent_runs.router:get_agent_run_trace": "AgentRunService.trace 内校验归属",
    "model_gateway.router:get_runtime_config": "全局运行配置，仅返回是否配置，不含租户数据",
    "api.router:create_ticket": "TicketService.create 内校验幂等键归属",
    "api.router:archive_test_ticket": "TicketService.archive_test_ticket 内校验归属",
    "api.router:take_over_ticket": "TicketService._locked_ticket 内校验归属",
    "api.router:review_draft": "TicketService._locked_ticket 内校验归属",
    "api.router:retry_external_sync": "TicketService._locked_ticket 内校验归属",
    "api.router:retry_external_sync_batch": "TicketService.batch_request_sync_retry 内逐条校验",
    "api.router:override_classification": "TicketService._locked_ticket 内校验归属",
    "logistics.router:query_logistics": "仅调用外部物流查询，不访问租户存储",
}


@dataclass(frozen=True)
class ModuleInfo:
    module: str
    is_package: bool
    path: Path
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
    imported_functions: dict[str, tuple[str, str]]
    imported_modules: dict[str, str]


def _module_name(path: Path) -> tuple[str, bool]:
    relative = path.relative_to(SOURCE_ROOT).with_suffix("")
    parts = list(relative.parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ".".join(parts), is_package


def _resolve_relative(
    *, module: str, is_package: bool, level: int, target: str | None
) -> str:
    package_parts = module.split(".") if is_package else module.split(".")[:-1]
    if level > 1:
        package_parts = package_parts[: len(package_parts) - (level - 1)]
    tail = [target] if target else []
    return ".".join([*package_parts, *tail])


def _load_modules() -> dict[str, ModuleInfo]:
    modules: dict[str, ModuleInfo] = {}
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        module, is_package = _module_name(path)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        imported_functions: dict[str, tuple[str, str]] = {}
        imported_modules: dict[str, str] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions[node.name] = node
                continue
            if isinstance(node, ast.ImportFrom):
                source = node.module or ""
                if node.level:
                    source = _resolve_relative(
                        module=module,
                        is_package=is_package,
                        level=node.level,
                        target=node.module,
                    )
                elif source.startswith(PACKAGE_PREFIX):
                    source = source[len(PACKAGE_PREFIX) :]
                for alias in node.names:
                    key = alias.asname or alias.name
                    imported_functions[key] = (source, alias.name)
                    imported_modules[key] = f"{source}.{alias.name}"
                continue
            if isinstance(node, ast.Import):
                for alias in node.names:
                    key = alias.asname or alias.name
                    if alias.name.startswith(PACKAGE_PREFIX):
                        imported_modules[key] = alias.name[len(PACKAGE_PREFIX) :]
        modules[module] = ModuleInfo(
            module=module,
            is_package=is_package,
            path=path,
            functions=functions,
            imported_functions=imported_functions,
            imported_modules=imported_modules,
        )
    # Drop imported names that do not point at a traceable module function.
    for module, info in list(modules.items()):
        modules[module] = replace(
            info,
            imported_functions={
                alias: target
                for alias, target in info.imported_functions.items()
                if target[0] in modules and target[1] in modules[target[0]].functions
            },
        )
    return modules


def _is_route_handler(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if isinstance(decorator.func, ast.Attribute) and decorator.func.attr in ROUTE_METHODS:
            return True
    return False


def _calls_guard(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name) and func.id in GUARD_NAMES:
            return True
        if isinstance(func, ast.Attribute) and func.attr in GUARD_NAMES:
            return True
    return False


def _resolve_callees(
    node: ast.AST, info: ModuleInfo, modules: dict[str, ModuleInfo]
) -> set[tuple[str, str]]:
    callees: set[tuple[str, str]] = set()

    def add_from_name(name: str) -> None:
        if name in info.functions:
            callees.add((info.module, name))
            return
        target = info.imported_functions.get(name)
        if target is not None:
            callees.add(target)

    def add_from_expression(expression: ast.expr) -> None:
        if isinstance(expression, ast.Name):
            add_from_name(expression.id)
            return
        if isinstance(expression, ast.Attribute) and isinstance(expression.value, ast.Name):
            module = info.imported_modules.get(expression.value.id)
            if module is None or module not in modules:
                return
            if expression.attr in modules[module].functions:
                callees.add((module, expression.attr))

    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        func = sub.func
        if isinstance(func, ast.Name):
            add_from_name(func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            module = info.imported_modules.get(func.value.id)
            if (
                module is not None
                and module in modules
                and func.attr in modules[module].functions
            ):
                callees.add((module, func.attr))
        if isinstance(func, ast.Name) and func.id in DEPENDENCY_CALLS:
            for argument in [*sub.args, *(keyword.value for keyword in sub.keywords)]:
                add_from_expression(argument)
    return callees


def _is_guarded(
    target: tuple[str, str],
    modules: dict[str, ModuleInfo],
    seen: frozenset[tuple[str, str]],
) -> bool:
    info = modules.get(target[0])
    if info is None:
        return False
    node = info.functions.get(target[1])
    if node is None:
        return False
    if _calls_guard(node):
        return True
    if len(seen) >= MAX_DEPTH:
        return False
    return any(
        _is_guarded(callee, modules, seen | {target})
        for callee in _resolve_callees(node, info, modules)
    )


@lru_cache(maxsize=1)
def _analyse() -> tuple[list[str], set[str]]:
    modules = _load_modules()
    handlers: list[str] = []
    guarded: set[str] = set()
    for info in modules.values():
        for name, node in info.functions.items():
            if not _is_route_handler(node):
                continue
            key = f"{info.module}:{name}"
            handlers.append(key)
            if _is_guarded((info.module, name), modules, frozenset()):
                guarded.add(key)
    return sorted(handlers), guarded


def test_every_route_has_tenant_guard_or_documented_exemption() -> None:
    handlers, guarded = _analyse()
    offenders = [key for key in handlers if key not in guarded and key not in ALLOWED_UNGUARDED]
    assert not offenders, (
        "以下路由既未调用 ensure_business_unit_access / resolve_business_unit，"
        "也不在 ALLOWED_UNGUARDED 中。请在处理函数内校验租户归属，"
        "或在允许清单中登记原因：\n  " + "\n  ".join(offenders)
    )


def test_allowlist_entries_are_live_and_still_needed() -> None:
    handlers, guarded = _analyse()
    unknown = sorted(set(ALLOWED_UNGUARDED) - set(handlers))
    stale = sorted(set(ALLOWED_UNGUARDED) & guarded)
    assert not unknown, "允许清单中的路由不存在：" + ", ".join(unknown)
    assert not stale, "以下路由已具备守卫，请从 ALLOWED_UNGUARDED 删除：" + ", ".join(stale)


def test_allowlist_entries_explain_the_exemption() -> None:
    missing = sorted(key for key, reason in ALLOWED_UNGUARDED.items() if not reason.strip())
    assert not missing, "允许清单缺少豁免原因：" + ", ".join(missing)
