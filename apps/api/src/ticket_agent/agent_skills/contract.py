"""Skill 执行契约：结构化定义、完成条件求值与内置默认值。

``agent_skills.instructions`` 仍然是给模型看的人读文本；``definition_json``
是运行时契约，决定“这一轮有没有走完该岗位的步骤”。两者分开，是因为
提示词无法被机器判定，而完成条件必须可判定。

这里只做纯函数：不读库、不改状态。Skill 服务负责存取，Turn 运行时负责把
求值结果写进 ``conversation_turns.completion_json``。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

CompletionCriterion = Literal[
    "all_required_steps_done",
    "no_unsupported_claim",
]

COMPLETION_CRITERIA: tuple[CompletionCriterion, ...] = (
    "all_required_steps_done",
    "no_unsupported_claim",
)

# 步骤证据前缀。只支持这几种，未知前缀一律视为“未满足”，宁可拦住也不放行。
EVIDENCE_SLOT = "slot:"
EVIDENCE_KNOWLEDGE = "knowledge:"
EVIDENCE_TOOL = "tool:"
EVIDENCE_PREFIXES = (EVIDENCE_SLOT, EVIDENCE_KNOWLEDGE, EVIDENCE_TOOL)

_EXPRESSION = re.compile(
    r"^\s*([a-z_][a-z0-9_]*)\s*(!=|==|>=|<=|>|<)\s*"
    r"(null|true|false|-?\d+(?:\.\d+)?)\s*$"
)
_SLOT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
STEP_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


class SkillStep(BaseModel):
    """一个可判定的步骤。``required=True`` 未完成时本轮不得 COMPLETED。"""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    required: bool = True
    evidence: list[str] = Field(default_factory=list, max_length=20)
    # 形如 ``order_id != null`` / ``citation_count > 0``。
    # 留空表示“证据满足即可”。
    completion: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_step(self) -> SkillStep:
        if not STEP_ID.match(self.id):
            raise ValueError(
                "step id must match ^[a-z][a-z0-9_-]{1,63}$"
            )
        for item in self.evidence:
            if not item.startswith(EVIDENCE_PREFIXES):
                raise ValueError(
                    "evidence must start with slot:/knowledge:/tool/: "
                    f"{item!r}"
                )
        if (
            self.completion is not None
            and _EXPRESSION.match(self.completion) is None
        ):
            raise ValueError(
                "completion must be '<variable> <op> <value>': "
                f"{self.completion!r}"
            )
        return self


class SkillEscalation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: Literal["human", "supervisor"] = "human"
    when: list[str] = Field(default_factory=list, max_length=20)


class SkillDefinition(BaseModel):
    """``agent_skills.definition_json`` 的结构。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    triggers: list[str] = Field(default_factory=list, max_length=50)
    excludes: list[str] = Field(default_factory=list, max_length=50)
    required_tools: list[str] = Field(default_factory=list, max_length=50)
    steps: list[SkillStep] = Field(default_factory=list, max_length=30)
    forbidden_actions: list[str] = Field(default_factory=list, max_length=50)
    completion_criteria: list[CompletionCriterion] = Field(
        default_factory=lambda: cast(
            list[CompletionCriterion],
            ["all_required_steps_done", "no_unsupported_claim"],
        ),
        max_length=2,
    )
    escalation: SkillEscalation | None = None
    answer_format: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_definition(self) -> SkillDefinition:
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step ids must be unique")
        if len(set(self.completion_criteria)) != len(
            self.completion_criteria
        ):
            raise ValueError("completion_criteria must be unique")
        if not self.steps and not self.completion_criteria:
            raise ValueError(
                "a definition needs at least one step or criterion"
            )
        return self

    def to_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


@dataclass(frozen=True)
class CompletionContext:
    """求值时可用的、已经确定的事实。"""

    slots: dict[str, Any] = field(default_factory=dict)
    citation_count: int = 0
    tool_call_count: int = 0
    tool_ids: frozenset[str] = frozenset()
    claim_count: int = 0
    unsupported_claim_count: int = 0
    grounding_status: str = ""
    risk_level: str | None = None


def _variables(context: CompletionContext) -> dict[str, Any]:
    values: dict[str, Any] = {
        "citation_count": context.citation_count,
        "tool_call_count": context.tool_call_count,
        "claim_count": context.claim_count,
        "unsupported_claim_count": context.unsupported_claim_count,
        "grounding_status": context.grounding_status,
        "risk_level": context.risk_level,
    }
    for name, value in context.slots.items():
        if isinstance(name, str) and _SLOT_NAME.match(name):
            values[name] = value
    return values


def _coerce_literal(raw: str) -> Any:
    if raw == "null":
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    try:
        return int(raw)
    except ValueError:
        return float(raw)


def evaluate_expression(
    expression: str,
    context: CompletionContext,
) -> tuple[bool, str | None]:
    """求值一个完成条件。返回 ``(是否满足, 未满足原因)``。

    未知变量、未知算子都返回 ``(False, reason)``：契约写错时宁可拦住，
    也不能把“读不懂”当成“已完成”。
    """
    match = _EXPRESSION.match(expression)
    if match is None:
        return False, "unsupported_expression"
    variable, operator, raw = match.groups()
    values = _variables(context)
    if variable not in values:
        return False, f"unknown_variable:{variable}"
    left = values[variable]
    right = _coerce_literal(raw)
    if operator == "!=":
        result = left != right
    elif operator == "==":
        result = left == right
    elif operator == ">":
        result = _compare(left, right, lambda a, b: a > b)
    elif operator == ">=":
        result = _compare(left, right, lambda a, b: a >= b)
    elif operator == "<":
        result = _compare(left, right, lambda a, b: a < b)
    else:
        result = _compare(left, right, lambda a, b: a <= b)
    return result, None if result else f"{variable} {operator} {raw} unmet"


def _compare(left: Any, right: Any, operation: Any) -> bool:
    try:
        return bool(operation(left, right))
    except TypeError:
        return False


def _evidence_ok(
    evidence: str,
    context: CompletionContext,
) -> tuple[bool, str | None]:
    if evidence.startswith(EVIDENCE_SLOT):
        name = evidence[len(EVIDENCE_SLOT):]
        value = context.slots.get(name)
        return (
            value not in (None, "", [], {}),
            None if value not in (None, "", [], {}) else f"slot:{name} missing",
        )
    if evidence.startswith(EVIDENCE_KNOWLEDGE):
        return (
            context.citation_count > 0,
            None if context.citation_count > 0 else "no citation",
        )
    if evidence.startswith(EVIDENCE_TOOL):
        tool_id = evidence[len(EVIDENCE_TOOL):]
        present = tool_id in context.tool_ids
        return (
            present,
            None if present else f"tool:{tool_id} not executed",
        )
    return False, f"unknown_evidence:{evidence}"


def evaluate_definition(
    definition: dict[str, Any] | None,
    *,
    context: CompletionContext,
) -> dict[str, Any] | None:
    """按契约逐项求值。

    ``definition=None`` 表示旧 Skill 没有结构化契约（宽松模式）：返回
    ``None``，调用方不得把它当作“完成”或“未完成”。
    """
    if definition is None:
        return None
    parsed = SkillDefinition.model_validate(definition)
    steps: list[dict[str, Any]] = []
    incomplete_required: list[str] = []
    for step in parsed.steps:
        reasons: list[str] = []
        evidence_ok = True
        for evidence in step.evidence:
            ok, reason = _evidence_ok(evidence, context)
            if not ok:
                evidence_ok = False
                if reason is not None:
                    reasons.append(reason)
        completion_ok = True
        if step.completion is not None:
            completion_ok, reason = evaluate_expression(
                step.completion,
                context,
            )
            if not completion_ok and reason is not None:
                reasons.append(reason)
        done = evidence_ok and completion_ok
        if step.required and not done:
            incomplete_required.append(step.id)
        steps.append(
            {
                "id": step.id,
                "name": step.name,
                "required": step.required,
                "evidence": list(step.evidence),
                "evidence_ok": evidence_ok,
                "completion": step.completion,
                "completion_ok": completion_ok,
                "done": done,
                "reasons": reasons,
            }
        )

    criteria: dict[str, bool] = {}
    if "all_required_steps_done" in parsed.completion_criteria:
        criteria["all_required_steps_done"] = not incomplete_required
    if "no_unsupported_claim" in parsed.completion_criteria:
        criteria["no_unsupported_claim"] = (
            context.unsupported_claim_count == 0
        )
    return {
        "schema_version": parsed.schema_version,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "steps": steps,
        "criteria": criteria,
        "incomplete_required": incomplete_required,
        "all_required_steps_done": not incomplete_required,
        "complete": all(criteria.values()),
    }


# 内置客服 Skill 的结构化契约。只覆盖三条客服岗位；HR 与主管 Skill 保持
# 宽松模式（definition_json=NULL），避免一次改完所有历史配置。
DEFAULT_SKILL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "ecommerce-presales": {
        "schema_version": 1,
        "triggers": [
            "材质",
            "容量",
            "保温",
            "尺码",
            "颜色",
            "怎么用",
            "多少钱",
        ],
        "excludes": [],
        "required_tools": ["knowledge.search"],
        "steps": [
            {
                "id": "retrieve_product_knowledge",
                "name": "检索商品知识",
                "required": True,
                "evidence": ["knowledge:product"],
                "completion": "citation_count > 0",
            },
            {
                "id": "answer_static_parameters",
                "name": "回答静态参数",
                "required": True,
                "evidence": ["knowledge:product"],
                "completion": "citation_count > 0",
            },
            {
                "id": "handoff_realtime_checks",
                "name": "价格库存等实时信息转工具查询",
                "required": False,
                "evidence": [],
                "completion": "tool_call_count > 0",
            },
        ],
        "forbidden_actions": ["promise_unverified_spec"],
        "completion_criteria": [
            "all_required_steps_done",
            "no_unsupported_claim",
        ],
        "escalation": {"to": "human", "when": ["missing_evidence"]},
        "answer_format": "先结论，再依据，最后下一步",
    },
    "ecommerce-aftersales": {
        "schema_version": 1,
        "triggers": ["退款", "退货", "换货", "售后", "漏水", "损坏", "赔偿"],
        "excludes": ["仅查询物流"],
        "required_tools": ["knowledge.search"],
        "steps": [
            {
                "id": "identify_order",
                "name": "确认订单与商品",
                "required": True,
                "evidence": ["slot:order_id"],
                "completion": "order_id != null",
            },
            {
                "id": "check_policy",
                "name": "核对售后政策",
                "required": True,
                "evidence": ["knowledge:aftersales"],
                "completion": "citation_count > 0",
            },
            {
                "id": "no_unapproved_refund",
                "name": "不自行承诺退款资格",
                "required": True,
                "evidence": [],
                "completion": "unsupported_claim_count == 0",
            },
        ],
        "forbidden_actions": ["refund.execute_without_approval"],
        "completion_criteria": [
            "all_required_steps_done",
            "no_unsupported_claim",
        ],
        "escalation": {
            "to": "human",
            "when": ["amount > 500", "risk in [R2,R3]", "missing_evidence"],
        },
        "answer_format": "先结论，再依据，最后下一步",
    },
    "logistics-inquiry": {
        "schema_version": 1,
        "triggers": ["物流", "快递", "运单", "到哪", "签收", "派送", "发货"],
        "excludes": [],
        "required_tools": ["knowledge.search", "logistics.query"],
        "steps": [
            {
                "id": "identify_shipment",
                "name": "确认订单或运单号",
                "required": True,
                "evidence": ["slot:order_id"],
                "completion": "order_id != null",
            },
            {
                "id": "query_tracking",
                "name": "查询真实物流轨迹",
                "required": True,
                "evidence": ["tool:logistics.query"],
                "completion": "tool_call_count > 0",
            },
        ],
        "forbidden_actions": ["guess_tracking_status"],
        "completion_criteria": ["all_required_steps_done"],
        "escalation": {"to": "human", "when": ["missing_evidence"]},
        "answer_format": "先结论，再依据，最后下一步",
    },
}
