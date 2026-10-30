from collections.abc import Iterator
from pathlib import Path

import pytest

from ticket_agent.domains.registry import (
    DomainPackError,
    clear_domain_registry_cache,
    domain_for_workflow,
    get_domain_registry,
    is_workflow_registered,
    resolve_workflow_class,
    validate_domain_packs,
)
from ticket_agent.shared.settings import get_settings
from ticket_agent.workflow.customer_service import CustomerServiceTicketWorkflow
from ticket_agent.workflow.hr_onboarding import HROnboardingWorkflow
from ticket_agent.workflow.registry import get_workflow

MANUFACTURING_PACK = """
key = "manufacturing"
name = "工业制造"
default_workflow = "manufacturing_equipment_ticket_v1"

[[workflows]]
key = "manufacturing_equipment_ticket_v1"
handler = "ticket_agent.workflow.customer_service:CustomerServiceTicketWorkflow"
label = "设备报修流程"
"""


@pytest.fixture(autouse=True)
def _fresh_registry(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # The registry is cached per process; every test starts from an empty
    # environment so one test's pack cannot leak into the next.
    monkeypatch.delenv("DOMAIN_PACKS_DIR", raising=False)
    get_settings.cache_clear()
    clear_domain_registry_cache()
    yield
    get_settings.cache_clear()
    clear_domain_registry_cache()


def _write_pack(directory: Path, name: str, content: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(content, encoding="utf-8")


def _use_directory(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    monkeypatch.setenv("DOMAIN_PACKS_DIR", str(directory))
    get_settings.cache_clear()
    clear_domain_registry_cache()


def test_builtin_packs_register_the_shipped_workflows() -> None:
    registry = get_domain_registry()

    assert {pack.key for pack in registry.packs} == {
        "customer_service",
        "human_resources",
    }
    assert registry.workflow_keys() == {
        "customer_service_ticket_v1",
        "hr_onboarding_document_collection_v1",
    }
    assert domain_for_workflow("customer_service_ticket_v1") == "customer_service"
    assert (
        domain_for_workflow("hr_onboarding_document_collection_v1")
        == "human_resources"
    )
    assert resolve_workflow_class("customer_service_ticket_v1") is (
        CustomerServiceTicketWorkflow
    )
    assert resolve_workflow_class("hr_onboarding_document_collection_v1") is (
        HROnboardingWorkflow
    )


def test_unknown_workflow_is_not_silently_mapped() -> None:
    assert not is_workflow_registered("manufacturing_equipment_ticket_v1")
    assert domain_for_workflow("manufacturing_equipment_ticket_v1") is None
    with pytest.raises(DomainPackError):
        resolve_workflow_class("manufacturing_equipment_ticket_v1")


def test_workflow_registry_keeps_its_error_shape() -> None:
    # get_workflow is the worker entry point; an unknown key must still raise
    # ValueError, not leak the registry exception type into the worker.
    with pytest.raises(ValueError, match="Unsupported workflow"):
        get_workflow(None, "manufacturing_equipment_ticket_v1")  # type: ignore[arg-type]


def test_toml_pack_adds_a_domain_without_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_pack(tmp_path, "manufacturing.toml", MANUFACTURING_PACK)
    _use_directory(monkeypatch, tmp_path)

    registry = validate_domain_packs()

    assert registry.pack("manufacturing") is not None
    assert is_workflow_registered("manufacturing_equipment_ticket_v1")
    assert domain_for_workflow("manufacturing_equipment_ticket_v1") == (
        "manufacturing"
    )
    assert resolve_workflow_class("manufacturing_equipment_ticket_v1") is (
        CustomerServiceTicketWorkflow
    )


def test_duplicate_workflow_key_across_packs_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_pack(
        tmp_path,
        "manufacturing.toml",
        MANUFACTURING_PACK.replace(
            "manufacturing_equipment_ticket_v1",
            "customer_service_ticket_v1",
        ),
    )
    _use_directory(monkeypatch, tmp_path)

    with pytest.raises(DomainPackError, match="重复的工作流 key"):
        get_domain_registry()


def test_duplicate_domain_key_across_files_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_pack(tmp_path, "a.toml", MANUFACTURING_PACK)
    _write_pack(
        tmp_path,
        "b.toml",
        MANUFACTURING_PACK.replace(
            "manufacturing_equipment_ticket_v1",
            "manufacturing_second_ticket_v1",
        ),
    )
    # Both files declare key = "manufacturing"; the second one must lose.
    _use_directory(monkeypatch, tmp_path)

    with pytest.raises(DomainPackError, match="重复的领域包"):
        get_domain_registry()


def test_default_workflow_must_belong_to_the_pack(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_pack(
        tmp_path,
        "manufacturing.toml",
        MANUFACTURING_PACK.replace(
            'default_workflow = "manufacturing_equipment_ticket_v1"',
            'default_workflow = "customer_service_ticket_v1"',
        ),
    )
    _use_directory(monkeypatch, tmp_path)

    with pytest.raises(DomainPackError, match="default_workflow"):
        get_domain_registry()


def test_handler_must_be_a_module_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_pack(
        tmp_path,
        "manufacturing.toml",
        MANUFACTURING_PACK.replace(
            "ticket_agent.workflow.customer_service:"
            "CustomerServiceTicketWorkflow",
            "ticket_agent.workflow.customer_service",
        ),
    )
    _use_directory(monkeypatch, tmp_path)

    with pytest.raises(DomainPackError, match="module:Class"):
        validate_domain_packs()


def test_unknown_pack_field_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _write_pack(
        tmp_path,
        "manufacturing.toml",
        MANUFACTURING_PACK.replace(
            'name = "工业制造"',
            'name = "工业制造"\nemployes = []',
        ),
    )
    _use_directory(monkeypatch, tmp_path)

    with pytest.raises(DomainPackError, match="未知字段"):
        get_domain_registry()


def test_missing_pack_directory_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_directory(monkeypatch, tmp_path / "does-not-exist")

    with pytest.raises(DomainPackError, match="DOMAIN_PACKS_DIR"):
        get_domain_registry()


def test_empty_pack_directory_keeps_builtins(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _use_directory(monkeypatch, tmp_path)

    registry = validate_domain_packs()

    assert registry.workflow_keys() == {
        "customer_service_ticket_v1",
        "hr_onboarding_document_collection_v1",
    }
