"""Domain packs: which workflows a business domain offers.

A domain pack is configuration, not code. Each pack owns one or more
workflow keys and names the handler class that executes them. Built-in packs
cover the shipped domains; extra packs are loaded from TOML files in
``DOMAIN_PACKS_DIR`` (one file per domain) so a new direction does not have to
edit the employee service.

The handler is a ``module:Class`` string and is imported lazily. Importing
this module therefore does not pull in the workflow implementations, which
keeps ``digital_employees`` → ``domains`` free of import cycles.
"""

from __future__ import annotations

import importlib
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path
from typing import Any, cast

from ticket_agent.shared.settings import get_settings
from ticket_agent.workflow.base import DigitalEmployeeWorkflow


class DomainPackError(ValueError):
    """A domain pack is malformed or conflicts with another pack."""


@dataclass(frozen=True)
class WorkflowSpec:
    key: str
    handler: str
    label: str = ""


@dataclass(frozen=True)
class DomainPack:
    key: str
    name: str
    default_workflow_key: str
    workflows: tuple[WorkflowSpec, ...]
    source: str = "builtin"

    @property
    def workflow_keys(self) -> tuple[str, ...]:
        return tuple(spec.key for spec in self.workflows)


class DomainRegistry:
    """Immutable index over the loaded packs."""

    def __init__(self, packs: Iterable[DomainPack]) -> None:
        self._packs: dict[str, DomainPack] = {}
        self._specs: dict[str, WorkflowSpec] = {}
        self._domain_by_workflow: dict[str, str] = {}
        for pack in packs:
            if pack.key in self._packs:
                raise DomainPackError(f"重复的领域包：{pack.key}")
            self._packs[pack.key] = pack
            for spec in pack.workflows:
                if spec.key in self._specs:
                    raise DomainPackError(
                        f"重复的工作流 key：{spec.key}"
                        f"（{self._domain_by_workflow[spec.key]} 与 {pack.key}）"
                    )
                self._specs[spec.key] = spec
                self._domain_by_workflow[spec.key] = pack.key

    @property
    def packs(self) -> tuple[DomainPack, ...]:
        return tuple(self._packs.values())

    def pack(self, domain_key: str) -> DomainPack | None:
        return self._packs.get(domain_key)

    def workflow_spec(self, workflow_key: str) -> WorkflowSpec | None:
        return self._specs.get(workflow_key)

    def domain_for_workflow(self, workflow_key: str) -> str | None:
        return self._domain_by_workflow.get(workflow_key)

    def workflow_keys(self) -> frozenset[str]:
        return frozenset(self._specs)

    def resolve_workflow(
        self,
        workflow_key: str,
    ) -> type[DigitalEmployeeWorkflow]:
        spec = self._specs.get(workflow_key)
        if spec is None:
            raise DomainPackError(f"未注册的工作流：{workflow_key}")
        return _resolve_handler(spec.handler)


@cache
def _resolve_handler(
    path: str,
) -> type[DigitalEmployeeWorkflow]:
    module_name, separator, attribute = path.partition(":")
    if not separator or not module_name or not attribute:
        raise DomainPackError(
            f"工作流 handler 必须写成 'module:Class'：{path!r}"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise DomainPackError(
            f"无法导入工作流模块 {module_name}：{exc}"
        ) from exc
    handler = getattr(module, attribute, None)
    if handler is None:
        raise DomainPackError(
            f"模块 {module_name} 中没有 {attribute}"
        )
    return cast(type[DigitalEmployeeWorkflow], handler)


def _builtin_packs() -> tuple[DomainPack, ...]:
    return (
        DomainPack(
            key="customer_service",
            name="客户服务",
            default_workflow_key="customer_service_ticket_v1",
            workflows=(
                WorkflowSpec(
                    key="customer_service_ticket_v1",
                    handler=(
                        "ticket_agent.workflow.customer_service:"
                        "CustomerServiceTicketWorkflow"
                    ),
                    label="客户服务工单流程",
                ),
            ),
        ),
        DomainPack(
            key="human_resources",
            name="人力资源",
            default_workflow_key="hr_onboarding_document_collection_v1",
            workflows=(
                WorkflowSpec(
                    key="hr_onboarding_document_collection_v1",
                    handler=(
                        "ticket_agent.workflow.hr_onboarding:"
                        "HROnboardingWorkflow"
                    ),
                    label="入职资料收集流程",
                ),
            ),
        ),
    )


_PACK_KEYS = frozenset({"key", "name", "default_workflow", "workflows"})
_SPEC_KEYS = frozenset({"key", "handler", "label"})


def _required_text(
    data: dict[str, Any],
    field: str,
    *,
    source: str,
) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        raise DomainPackError(f"{source}：{field} 必须是非空字符串")
    return value.strip()


def _load_pack_file(path: Path) -> DomainPack:
    source = path.name
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise DomainPackError(f"{source}：TOML 解析失败：{exc}") from exc
    unknown = set(data) - _PACK_KEYS
    if unknown:
        raise DomainPackError(
            f"{source}：未知字段 {'、'.join(sorted(unknown))}"
        )
    key = _required_text(data, "key", source=source)
    name = _required_text(data, "name", source=source)
    default_workflow = _required_text(
        data,
        "default_workflow",
        source=source,
    )
    raw_workflows = data.get("workflows")
    if not isinstance(raw_workflows, list) or not raw_workflows:
        raise DomainPackError(f"{source}：workflows 必须是非空数组")
    specs: list[WorkflowSpec] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_workflows, start=1):
        if not isinstance(raw, dict):
            raise DomainPackError(
                f"{source}：workflows[{index}] 必须是表"
            )
        unknown_spec = set(raw) - _SPEC_KEYS
        if unknown_spec:
            raise DomainPackError(
                f"{source}：workflows[{index}] 存在未知字段 "
                + "、".join(sorted(unknown_spec))
            )
        workflow_key = _required_text(raw, "key", source=f"{source}#{index}")
        if workflow_key in seen:
            raise DomainPackError(
                f"{source}：工作流 key 重复：{workflow_key}"
            )
        seen.add(workflow_key)
        handler = _required_text(
            raw,
            "handler",
            source=f"{source}#{index}",
        )
        label = raw.get("label", "")
        if not isinstance(label, str):
            raise DomainPackError(
                f"{source}：workflows[{index}].label 必须是字符串"
            )
        specs.append(
            WorkflowSpec(
                key=workflow_key,
                handler=handler,
                label=label.strip(),
            )
        )
    if default_workflow not in seen:
        raise DomainPackError(
            f"{source}：default_workflow '{default_workflow}' "
            "不在本包的工作流中"
        )
    return DomainPack(
        key=key,
        name=name,
        default_workflow_key=default_workflow,
        workflows=tuple(specs),
        source=str(path),
    )


def _load_pack_directory(directory: Path) -> list[DomainPack]:
    if not directory.is_dir():
        raise DomainPackError(
            f"DOMAIN_PACKS_DIR 不是有效目录：{directory}"
        )
    return [
        _load_pack_file(path)
        for path in sorted(directory.glob("*.toml"))
    ]


@lru_cache(maxsize=1)
def get_domain_registry() -> DomainRegistry:
    packs: list[DomainPack] = list(_builtin_packs())
    directory = get_settings().domain_packs_dir.strip()
    if directory:
        packs.extend(_load_pack_directory(Path(directory)))
    return DomainRegistry(packs)


def clear_domain_registry_cache() -> None:
    get_domain_registry.cache_clear()
    _resolve_handler.cache_clear()


def is_workflow_registered(workflow_key: str) -> bool:
    return get_domain_registry().workflow_spec(workflow_key) is not None


def domain_for_workflow(workflow_key: str) -> str | None:
    return get_domain_registry().domain_for_workflow(workflow_key)


def resolve_workflow_class(
    workflow_key: str,
) -> type[DigitalEmployeeWorkflow]:
    return get_domain_registry().resolve_workflow(workflow_key)


def validate_domain_packs() -> DomainRegistry:
    """Load every pack and import every handler.

    Called at startup so a broken TOML file or a bad handler path fails the
    process instead of surfacing on the first ticket that needs it.
    """
    registry = get_domain_registry()
    for spec in registry.packs:
        for workflow in spec.workflows:
            registry.resolve_workflow(workflow.key)
    return registry
