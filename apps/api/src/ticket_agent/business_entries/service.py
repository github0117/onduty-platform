from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ticket_agent.business_entries.models import (
    BusinessServiceEntry,
    BusinessServiceEntryEmployee,
)
from ticket_agent.business_entries.schemas import (
    BusinessServiceEntryCreate,
    BusinessServiceEntryEmployeeInput,
    BusinessServiceEntryEmployeeView,
    BusinessServiceEntryUpdate,
    BusinessServiceEntryView,
)
from ticket_agent.digital_employees.models import DigitalEmployee
from ticket_agent.shared.errors import ApiProblem


class BusinessServiceEntryService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, business_unit_id: str) -> list[BusinessServiceEntryView]:
        rows = list(
            self.session.scalars(
                select(BusinessServiceEntry)
                .where(
                    BusinessServiceEntry.business_unit_id == business_unit_id
                )
                .order_by(
                    BusinessServiceEntry.status,
                    BusinessServiceEntry.name,
                )
            ).all()
        )
        return [self.view(row) for row in rows]

    def get(self, entry_id: UUID) -> BusinessServiceEntry:
        entry = self.session.get(BusinessServiceEntry, entry_id)
        if entry is None:
            raise ApiProblem(
                status_code=404,
                code="BUSINESS_SERVICE_ENTRY_NOT_FOUND",
                title="业务入口不存在",
                detail="该业务服务入口不存在或已被删除。",
            )
        return entry

    def create(
        self,
        payload: BusinessServiceEntryCreate,
        *,
        actor_id: str,
    ) -> BusinessServiceEntry:
        existing = self.session.scalar(
            select(BusinessServiceEntry).where(
                BusinessServiceEntry.business_unit_id
                == payload.business_unit_id,
                BusinessServiceEntry.code == payload.code,
            )
        )
        if existing is not None:
            raise ApiProblem(
                status_code=409,
                code="BUSINESS_SERVICE_ENTRY_EXISTS",
                title="业务入口编码已存在",
                detail="同一业务单元内，业务入口编码必须唯一。",
            )
        entry = BusinessServiceEntry(
            business_unit_id=payload.business_unit_id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            domain=payload.domain,
            channel=payload.channel,
            status=payload.status,
            default_employee_id=payload.default_employee_id,
            fallback_employee_id=payload.fallback_employee_id,
            human_queue_id=payload.human_queue_id,
            knowledge_scope_json=payload.knowledge_scope,
            sla_policy_json=payload.sla_policy,
            created_by=actor_id,
        )
        self.session.add(entry)
        self.session.flush()
        self._replace_employees(entry, payload.employees)
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def update(
        self,
        entry_id: UUID,
        payload: BusinessServiceEntryUpdate,
    ) -> BusinessServiceEntry:
        entry = self.get(entry_id)
        if entry.version != payload.expected_version:
            raise ApiProblem(
                status_code=409,
                code="BUSINESS_SERVICE_ENTRY_VERSION_CONFLICT",
                title="业务入口已更新",
                detail="请刷新业务入口后重新提交。",
                retryable=True,
            )
        for field in ("name", "description", "domain", "channel", "status"):
            value = getattr(payload, field)
            if value is not None:
                setattr(entry, field, value)
        if payload.default_employee_id is not None:
            entry.default_employee_id = payload.default_employee_id
        if payload.fallback_employee_id is not None:
            entry.fallback_employee_id = payload.fallback_employee_id
        if payload.human_queue_id is not None:
            entry.human_queue_id = payload.human_queue_id
        if payload.knowledge_scope is not None:
            entry.knowledge_scope_json = payload.knowledge_scope
        if payload.sla_policy is not None:
            entry.sla_policy_json = payload.sla_policy
        entry.version += 1
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def replace_employees(
        self,
        entry_id: UUID,
        employees: Sequence[BusinessServiceEntryEmployeeInput],
    ) -> BusinessServiceEntry:
        entry = self.get(entry_id)
        self._replace_employees(entry, employees)
        entry.version += 1
        self.session.commit()
        self.session.refresh(entry)
        return entry

    def view(self, entry: BusinessServiceEntry) -> BusinessServiceEntryView:
        binding_rows = self.session.execute(
            select(BusinessServiceEntryEmployee, DigitalEmployee)
            .join(
                DigitalEmployee,
                DigitalEmployee.id
                == BusinessServiceEntryEmployee.employee_id,
            )
            .where(
                BusinessServiceEntryEmployee.service_entry_id == entry.id,
                BusinessServiceEntryEmployee.enabled.is_(True),
            )
            .order_by(
                BusinessServiceEntryEmployee.priority,
                DigitalEmployee.name,
            )
        ).all()
        return BusinessServiceEntryView(
            id=entry.id,
            business_unit_id=entry.business_unit_id,
            code=entry.code,
            name=entry.name,
            description=entry.description,
            domain=entry.domain,
            channel=entry.channel,
            status=entry.status,
            default_employee_id=entry.default_employee_id,
            fallback_employee_id=entry.fallback_employee_id,
            human_queue_id=entry.human_queue_id,
            knowledge_scope=entry.knowledge_scope_json,
            sla_policy=entry.sla_policy_json,
            employees=[
                BusinessServiceEntryEmployeeView(
                    employee_id=employee.id,
                    employee_key=employee.employee_key,
                    employee_name=employee.name,
                    role_type=binding.role_type,
                    priority=binding.priority,
                    enabled=binding.enabled,
                    employee_status=employee.status,
                )
                for binding, employee in binding_rows
            ],
            version=entry.version,
            created_at=entry.created_at,
            updated_at=entry.updated_at,
        )

    def _replace_employees(
        self,
        entry: BusinessServiceEntry,
        employees: Sequence[BusinessServiceEntryEmployeeInput],
    ) -> None:
        employee_ids = [item.employee_id for item in employees]
        if len(employee_ids) != len(set(employee_ids)):
            raise ApiProblem(
                status_code=422,
                code="BUSINESS_SERVICE_ENTRY_DUPLICATE_EMPLOYEE",
                title="员工重复绑定",
                detail="同一个员工不能重复绑定到同一业务入口。",
            )
        if employee_ids:
            valid = set(
                self.session.scalars(
                    select(DigitalEmployee.id).where(
                        DigitalEmployee.id.in_(employee_ids),
                        DigitalEmployee.business_unit_id
                        == entry.business_unit_id,
                    )
                ).all()
            )
            missing = set(employee_ids) - valid
            if missing:
                raise ApiProblem(
                    status_code=422,
                    code="BUSINESS_SERVICE_ENTRY_EMPLOYEE_MISMATCH",
                    title="员工无法绑定",
                    detail="业务入口只能绑定同一业务单元内的数字员工。",
                )
        self.session.execute(
            delete(BusinessServiceEntryEmployee).where(
                BusinessServiceEntryEmployee.service_entry_id == entry.id
            )
        )
        for item in employees:
            self.session.add(
                BusinessServiceEntryEmployee(
                    service_entry_id=entry.id,
                    employee_id=item.employee_id,
                    role_type=item.role_type,
                    priority=item.priority,
                    enabled=item.enabled,
                )
            )
