import pytest
from pydantic import ValidationError

from ticket_agent.agent_skills.contract import (
    DEFAULT_SKILL_DEFINITIONS,
    CompletionContext,
    SkillDefinition,
    evaluate_definition,
    evaluate_expression,
)

ORDER_STEP = {
    "schema_version": 1,
    "steps": [
        {
            "id": "identify_order",
            "name": "确认订单",
            "required": True,
            "evidence": ["slot:order_id"],
            "completion": "order_id != null",
        },
        {
            "id": "check_policy",
            "name": "核对政策",
            "required": True,
            "evidence": ["knowledge:aftersales"],
            "completion": "citation_count > 0",
        },
    ],
    "completion_criteria": [
        "all_required_steps_done",
        "no_unsupported_claim",
    ],
}


def test_definition_roundtrip_keeps_steps() -> None:
    definition = SkillDefinition.model_validate(ORDER_STEP)
    payload = definition.to_json()
    assert payload["steps"][0]["id"] == "identify_order"
    assert payload["completion_criteria"] == [
        "all_required_steps_done",
        "no_unsupported_claim",
    ]


def test_duplicate_step_ids_are_rejected() -> None:
    with pytest.raises(ValidationError):
        SkillDefinition.model_validate(
            {
                "schema_version": 1,
                "steps": [
                    ORDER_STEP["steps"][0],
                    ORDER_STEP["steps"][0],
                ],
            }
        )


def test_evidence_prefix_is_restricted() -> None:
    with pytest.raises(ValidationError):
        SkillDefinition.model_validate(
            {
                "schema_version": 1,
                "steps": [
                    {
                        "id": "check",
                        "name": "检查",
                        "evidence": ["magic:something"],
                    }
                ],
            }
        )


def test_completion_expression_is_parsed() -> None:
    with pytest.raises(ValidationError):
        SkillDefinition.model_validate(
            {
                "schema_version": 1,
                "steps": [
                    {
                        "id": "check",
                        "name": "检查",
                        "completion": "order_id != null and more",
                    }
                ],
            }
        )


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        SkillDefinition.model_validate(
            {"schema_version": 1, "steps": [], "typo": True}
        )


def test_partial_context_incomplete_is_fail_closed() -> None:
    result = evaluate_definition(
        ORDER_STEP,
        context=CompletionContext(citation_count=2),
    )
    assert result is not None
    assert result["complete"] is False
    assert result["incomplete_required"] == ["identify_order"]
    assert result["steps"][0]["done"] is False
    assert "slot:order_id missing" in result["steps"][0]["reasons"]


def test_full_context_completes() -> None:
    result = evaluate_definition(
        ORDER_STEP,
        context=CompletionContext(
            slots={"order_id": "O-1001"},
            citation_count=2,
        ),
    )
    assert result is not None
    assert result["complete"] is True
    assert result["criteria"]["all_required_steps_done"] is True
    assert result["criteria"]["no_unsupported_claim"] is True


def test_unsupported_claim_blocks_completion() -> None:
    result = evaluate_definition(
        ORDER_STEP,
        context=CompletionContext(
            slots={"order_id": "O-1001"},
            citation_count=2,
            unsupported_claim_count=1,
        ),
    )
    assert result is not None
    assert result["complete"] is False
    assert result["criteria"]["no_unsupported_claim"] is False


def test_unknown_variable_fails_closed() -> None:
    ok, reason = evaluate_expression(
        "missing_slot != null",
        CompletionContext(),
    )
    assert ok is False
    assert reason == "unknown_variable:missing_slot"


def test_tool_evidence_requires_the_specific_tool() -> None:
    definition = {
        "schema_version": 1,
        "steps": [
            {
                "id": "query_tracking",
                "name": "查询物流",
                "required": True,
                "evidence": ["tool:logistics.query"],
            }
        ],
        "completion_criteria": ["all_required_steps_done"],
    }
    without = evaluate_definition(
        definition,
        context=CompletionContext(tool_call_count=1),
    )
    assert without is not None
    assert without["complete"] is False
    with_tool = evaluate_definition(
        definition,
        context=CompletionContext(
            tool_call_count=1,
            tool_ids=frozenset({"logistics.query"}),
        ),
    )
    assert with_tool is not None
    assert with_tool["complete"] is True


def test_loose_skill_has_no_verdict() -> None:
    assert evaluate_definition(None, context=CompletionContext()) is None


def test_builtin_definitions_are_valid() -> None:
    for code, definition in DEFAULT_SKILL_DEFINITIONS.items():
        parsed = SkillDefinition.model_validate(definition)
        assert parsed.steps, code
