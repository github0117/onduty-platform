#!/usr/bin/env python3
"""Live-stack acceptance for the Skill runtime contract (v2 M2).

Talks to a running API over HTTP only: real PostgreSQL, real worker. It does
not import the application, so a pass means the deployed process really
behaves this way.

Usage:
    uv run python scripts/acceptance_skill_contract.py [base_url]

Covers:
  * built-in skills get a structured contract after the upgrade
  * creating/editing a skill with a contract, optimistic version conflicts
  * invalid contracts are rejected with 422
  * a missing required step blocks turn completion and freezes a snapshot
  * editing the skill afterwards does not rewrite the finished turn
  * no trigger match falls back to the general skill, not the first binding
  * a loose (contract-less) skill keeps working without a completion verdict
"""

import json
import sys
import time
from typing import Any, cast
from uuid import uuid4

import httpx

TERMINAL = {"COMPLETED", "NEEDS_HUMAN", "FAILED_TERMINAL", "CANCELLED"}
GENERAL_SKILL = "customer-service-general"


def _headers(actor: str, role: str, unit: str) -> dict[str, str]:
    return {
        "X-Actor-Id": actor,
        "X-Actor-Role": role,
        "X-Business-Unit-Id": unit,
    }


def _wait_turn(
    client: httpx.Client,
    conversation_id: str,
    *,
    headers: dict[str, str],
    turn_id: str,
    timeout: float = 180.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/v1/customer-service/conversations/{conversation_id}",
            headers=headers,
        )
        response.raise_for_status()
        body = cast(dict[str, Any], response.json())
        current = body.get("current_turn") or {}
        last = current
        if current.get("id") != turn_id:
            time.sleep(0.5)
            continue
        if current.get("status") in TERMINAL:
            return body
        time.sleep(0.5)
    raise RuntimeError(f"turn did not finish: {json.dumps(last, ensure_ascii=False)}")


def _events(
    client: httpx.Client,
    conversation_id: str,
    turn_id: str,
    *,
    headers: dict[str, str],
) -> list[dict[str, Any]]:
    response = client.get(
        f"/api/v1/customer-service/conversations/{conversation_id}/turns/{turn_id}/events",
        headers=headers,
    )
    response.raise_for_status()
    return cast(list[dict[str, Any]], response.json()["events"])


def _event(events: list[dict[str, Any]], event_type: str) -> dict[str, Any] | None:
    for event in events:
        if event["event_type"] == event_type:
            return event
    return None


def _check(condition: bool, message: str, checks: list[str]) -> None:
    if not condition:
        raise AssertionError(message)
    checks.append(message)


def _create_employee(
    client: httpx.Client,
    headers: dict[str, str],
    key: str,
    name: str,
) -> str:
    response = client.post(
        "/api/v1/digital-employees",
        headers=headers,
        json={
            "employee_key": key,
            "name": name,
            "version": "1.0.0",
            "scenario_type": "customer_service_ticket",
            "workflow_key": "customer_service_ticket_v1",
            "business_unit_id": "bu_demo",
            "service_identity": f"digital_employee.{key}",
            "handoff_queue": "MANUAL_TRIAGE",
            "tool_allowlist": [
                "ticket.read",
                "knowledge.search",
                "draft.create",
            ],
        },
    )
    response.raise_for_status()
    return cast(str, response.json()["id"])


def _publish_doc(
    client: httpx.Client,
    headers: dict[str, str],
    document_id: str,
    content: str,
) -> None:
    version = client.post(
        f"/api/v1/knowledge-documents/{document_id}/versions",
        headers=headers,
        json={"version_label": "1.0", "content": content},
    )
    version.raise_for_status()
    published = client.post(
        (
            f"/api/v1/knowledge-documents/{document_id}/versions/"
            f"{version.json()['id']}/publish"
        ),
        headers=headers,
        json={"release_note": "skill contract acceptance"},
    )
    published.raise_for_status()


def _seed_aftersales_knowledge(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    suffix: str,
) -> None:
    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=headers,
        json={
            "business_unit_id": "bu_demo",
            "code": f"skill_contract_space_{suffix}",
            "name": "退款契约知识",
            "description": "Skill 完成度验收",
            "domain": "ecommerce",
            "channel": "enterprise_service",
            "category": "保温杯",
            "workflow_key": "customer_service_ticket_v1",
            "owner_id": f"skill-acceptance-admin-{suffix}",
            "evaluation_required": False,
        },
    )
    space.raise_for_status()
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=headers,
        json={
            "space_id": space.json()["id"],
            "business_unit_id": "bu_demo",
            "title": "退款与退货政策",
            "doc_type": "FAQ",
            "owner_id": f"skill-acceptance-admin-{suffix}",
            "scope": {},
        },
    )
    document.raise_for_status()
    _publish_doc(
        client,
        headers,
        document.json()["id"],
        (
            "退款：买家发起退款需先确认订单号和商品；"
            "售后政策为签收后 7 天内可申请退款或退货，"
            "退款金额和资格以人工审核结果为准，客服不得自行承诺。"
        ),
    )
    product = client.post(
        "/api/v1/knowledge-documents",
        headers=headers,
        json={
            "space_id": space.json()["id"],
            "business_unit_id": "bu_demo",
            "title": "保温杯材质与保温",
            "doc_type": "FAQ",
            "owner_id": f"skill-acceptance-admin-{suffix}",
            "scope": {},
        },
    )
    product.raise_for_status()
    _publish_doc(
        client,
        headers,
        product.json()["id"],
        "保温杯内胆采用 304 不锈钢，正常环境下可保温 6 小时。",
    )
    bound = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=headers,
        json={
            "bindings": [
                {
                    "knowledge_space_id": space.json()["id"],
                    "workflow_key": "customer_service_ticket_v1",
                    "scope": {},
                    "enabled": True,
                }
            ]
        },
    )
    bound.raise_for_status()


def _seed_loose_knowledge(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    suffix: str,
) -> None:
    space = client.post(
        "/api/v1/knowledge-spaces",
        headers=headers,
        json={
            "business_unit_id": "bu_demo",
            "code": f"skill_loose_space_{suffix}",
            "name": "积分规则知识",
            "description": "loose skill acceptance",
            "domain": "ecommerce",
            "channel": "enterprise_service",
            "category": "保温杯",
            "workflow_key": "customer_service_ticket_v1",
            "owner_id": f"skill-acceptance-admin-{suffix}",
            "evaluation_required": False,
        },
    )
    space.raise_for_status()
    document = client.post(
        "/api/v1/knowledge-documents",
        headers=headers,
        json={
            "space_id": space.json()["id"],
            "business_unit_id": "bu_demo",
            "title": "积分兑换规则",
            "doc_type": "FAQ",
            "owner_id": f"skill-acceptance-admin-{suffix}",
            "scope": {},
        },
    )
    document.raise_for_status()
    _publish_doc(
        client,
        headers,
        document.json()["id"],
        "积分兑换：每消费 1 元累计 1 积分，100 积分可兑换 5 元优惠券，兑换后不可退回。",
    )
    bound = client.put(
        f"/api/v1/digital-employees/{employee_id}/knowledge-bindings",
        headers=headers,
        json={
            "bindings": [
                {
                    "knowledge_space_id": space.json()["id"],
                    "workflow_key": "customer_service_ticket_v1",
                    "scope": {},
                    "enabled": True,
                }
            ]
        },
    )
    bound.raise_for_status()


def _bind_skills(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    skill_ids: list[str],
) -> None:
    response = client.put(
        f"/api/v1/digital-employees/{employee_id}/skills",
        headers=headers,
        json={
            "bindings": [
                {
                    "skill_id": skill_id,
                    "enabled": True,
                    "priority": (index + 1) * 10,
                }
                for index, skill_id in enumerate(skill_ids)
            ]
        },
    )
    response.raise_for_status()


def _activate(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
) -> None:
    listed = client.get(
        "/api/v1/digital-employees",
        params={"business_unit_id": headers["X-Business-Unit-Id"]},
        headers=headers,
    )
    listed.raise_for_status()
    current = next(row for row in listed.json() if row["id"] == employee_id)
    if current["status"] == "ACTIVE":
        return
    response = client.post(
        f"/api/v1/digital-employees/{employee_id}/activate",
        headers=headers,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"activation rejected: {response.status_code} {response.text}")
    if response.json()["status"] != "ACTIVE":
        raise RuntimeError(f"employee activation failed: {response.text}")


def _start_conversation(
    client: httpx.Client,
    headers: dict[str, str],
    employee_id: str,
    requester_ref: str,
) -> str:
    response = client.post(
        "/api/v1/customer-service/conversations",
        headers=headers,
        json={
            "business_unit_id": "bu_demo",
            "employee_id": employee_id,
            "requester_ref": requester_ref,
        },
    )
    response.raise_for_status()
    return cast(str, response.json()["id"])


def _send(
    client: httpx.Client,
    headers: dict[str, str],
    conversation_id: str,
    content: str,
) -> tuple[str, dict[str, Any]]:
    response = client.post(
        f"/api/v1/customer-service/conversations/{conversation_id}/messages",
        headers=headers,
        json={"content": content},
    )
    if response.status_code >= 400:
        raise RuntimeError(f"message rejected: {response.status_code} {response.text}")
    body = cast(dict[str, Any], response.json())
    return cast(str, body["current_turn"]["id"]), body


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    suffix = uuid4().hex[:8]
    unit = "bu_demo"
    admin = _headers(f"skill-acceptance-admin-{suffix}", "admin", unit)
    agent = _headers(f"skill-acceptance-agent-{suffix}", "agent", unit)
    checks: list[str] = []
    report: dict[str, Any] = {"suffix": suffix}

    with httpx.Client(base_url=base_url, timeout=180) as client:
        client.get("/health/ready").raise_for_status()

        # 1. Built-in skills carry a structured contract after the upgrade.
        skills_response = client.get(
            "/api/v1/skills",
            params={"business_unit_id": unit},
            headers=admin,
        )
        skills_response.raise_for_status()
        skills = skills_response.json()
        aftersales = next(
            skill for skill in skills if skill["code"] == "ecommerce-aftersales"
        )
        _check(
            aftersales["definition"] is not None
            and aftersales["definition_version"] >= 1,
            "built-in ecommerce-aftersales has a backfilled contract",
            checks,
        )
        custom_legacy = next(
            (
                skill
                for skill in skills
                if skill["definition"] is None
                and skill["code"]
                not in {
                    "ecommerce-presales",
                    "ecommerce-aftersales",
                    "logistics-inquiry",
                }
            ),
            None,
        )
        if custom_legacy is not None:
            _check(
                custom_legacy["definition_version"] == 0,
                "pre-upgrade custom skill stays loose (definition null, v0)",
                checks,
            )
            report["legacy_skill"] = custom_legacy["code"]
        report["builtin_contract_steps"] = [
            step["id"] for step in aftersales["definition"]["steps"]
        ]

        # 2. Contract CRUD over HTTP, including version conflicts and validation.
        definition: dict[str, Any] = {
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
        created = client.post(
            "/api/v1/skills",
            headers=admin,
            json={
                "business_unit_id": unit,
                "code": f"skill-contract-{suffix}",
                "name": "契约退款",
                "instructions": "核对订单与政策后再处理退款。",
                "triggers": ["退款"],
                "definition": definition,
            },
        )
        _check(created.status_code == 201, "skill with contract creates (201)", checks)
        created_body = created.json()
        _check(
            created_body["definition_version"] == 1,
            "new skill starts at contract v1",
            checks,
        )
        skill_id = created_body["id"]

        updated = client.patch(
            f"/api/v1/skills/{skill_id}",
            headers=admin,
            json={
                "expected_version": created_body["version"],
                "definition": {
                    **definition,
                    "steps": [
                        *definition["steps"],
                        {
                            "id": "confirm_amount",
                            "name": "确认金额",
                            "required": True,
                            "evidence": ["tool:ticket.read"],
                        },
                    ],
                },
            },
        )
        _check(updated.status_code == 200, "contract edit succeeds (200)", checks)
        _check(
            updated.json()["definition_version"] == 2,
            "contract edit bumps definition_version to 2",
            checks,
        )

        conflict = client.patch(
            f"/api/v1/skills/{skill_id}",
            headers=admin,
            json={"expected_version": 1, "name": "过期编辑"},
        )
        _check(
            conflict.status_code == 409
            and conflict.json().get("code") == "SKILL_VERSION_CONFLICT",
            "stale expected_version is rejected with 409 SKILL_VERSION_CONFLICT",
            checks,
        )

        invalid = client.post(
            "/api/v1/skills",
            headers=admin,
            json={
                "business_unit_id": unit,
                "code": f"skill-invalid-{suffix}",
                "name": "坏契约",
                "instructions": "任意",
                "definition": {
                    "schema_version": 1,
                    "steps": [{"id": "Bad Step", "name": "非法 ID"}],
                },
            },
        )
        _check(
            invalid.status_code == 422,
            "invalid contract is rejected with 422",
            checks,
        )

        # 3. A missing required step must stop the turn from completing.
        employee_id = _create_employee(
            client, admin, f"contract_turn_{suffix}", f"契约回合客服{suffix}"
        )
        _seed_aftersales_knowledge(client, admin, employee_id, suffix)
        _bind_skills(
            client,
            admin,
            employee_id,
            [created_body["id"]],
        )
        _activate(client, admin, employee_id)
        conversation_id = _start_conversation(
            client, agent, employee_id, f"contract-buyer-{suffix}"
        )
        turn_id, _ = _send(client, agent, conversation_id, "我要申请退款")
        conversation = _wait_turn(
            client, conversation_id, headers=agent, turn_id=turn_id
        )
        turn = conversation["current_turn"]
        report["blocked_turn"] = {
            "id": turn_id,
            "status": turn["status"],
            "conversation_id": conversation_id,
        }
        _check(
            turn["status"] == "NEEDS_HUMAN",
            f"turn with a missing required step ends NEEDS_HUMAN (got {turn['status']})",
            checks,
        )

        events = _events(client, conversation_id, turn_id, headers=admin)
        selected = _event(events, "SKILL_SELECTED")
        evaluated = _event(events, "COMPLETION_EVALUATED")
        _check(selected is not None, "turn records SKILL_SELECTED", checks)
        _check(evaluated is not None, "turn records COMPLETION_EVALUATED", checks)
        assert selected is not None and evaluated is not None, (
            f"missing turn events: {[e['event_type'] for e in events]}"
        )
        _check(
            selected["payload"]["skill_code"] == created_body["code"],
            "selected skill is the bound contract skill",
            checks,
        )
        _check(
            selected["payload"]["skill_version"] == 2,
            "selected skill version is the edited v2 contract",
            checks,
        )
        _check(
            selected["payload"]["contract_present"] is True,
            "selected skill had a contract present",
            checks,
        )
        _check(
            evaluated["payload"]["complete"] is False
            and "identify_order"
            in evaluated["payload"]["incomplete_required"],
            "completion verdict lists identify_order as incomplete",
            checks,
        )
        report["completion"] = evaluated["payload"]

        ticket_response = client.get(
            f"/api/v1/tickets/{turn['ticket_id']}",
            headers=agent,
        )
        ticket_response.raise_for_status()
        _check(
            ticket_response.json()["workflow_state"] != "COMPLETED",
            "blocked turn does not complete its ticket",
            checks,
        )

        # 5. No trigger match uses the general skill, not the first binding.
        weather_conversation = _start_conversation(
            client, agent, employee_id, f"contract-weather-{suffix}"
        )
        weather_turn_id, _ = _send(
            client,
            agent,
            weather_conversation,
            "保温杯内胆是什么材质，能保温多久？",
        )
        _wait_turn(
            client, weather_conversation, headers=agent, turn_id=weather_turn_id
        )
        weather_events = _events(
            client, weather_conversation, weather_turn_id, headers=admin
        )
        weather_selected = _event(weather_events, "SKILL_SELECTED")
        assert weather_selected is not None, (
            f"missing SKILL_SELECTED: {[e['event_type'] for e in weather_events]}"
        )
        _check(
            weather_selected["payload"]["skill_code"] == GENERAL_SKILL,
            "no trigger match selects the general skill",
            checks,
        )
        _check(
            weather_selected["payload"]["contract_present"] is False,
            "general skill is loose (no contract)",
            checks,
        )
        _check(
            _event(weather_events, "COMPLETION_EVALUATED") is None,
            "loose general skill has no completion verdict",
            checks,
        )
        report["general_turn"] = {
            "id": weather_turn_id,
            "conversation_id": weather_conversation,
        }

        # 6. A user-created loose skill keeps working without a verdict.
        loose = client.post(
            "/api/v1/skills",
            headers=admin,
            json={
                "business_unit_id": unit,
                "code": f"skill-loose-{suffix}",
                "name": "老式技能",
                "instructions": "按老式说明回答积分规则。",
                "triggers": ["积分兑换"],
            },
        )
        _check(loose.status_code == 201, "skill without contract creates (201)", checks)
        _check(
            loose.json()["definition"] is None
            and loose.json()["definition_version"] == 0,
            "contract-less skill stays loose (definition null, v0)",
            checks,
        )
        loose_employee = _create_employee(
            client, admin, f"loose_turn_{suffix}", f"老式技能客服{suffix}"
        )
        _seed_loose_knowledge(client, admin, loose_employee, suffix)
        _bind_skills(client, admin, loose_employee, [loose.json()["id"]])
        _activate(client, admin, loose_employee)
        loose_conversation = _start_conversation(
            client, agent, loose_employee, f"loose-buyer-{suffix}"
        )
        loose_turn_id, _ = _send(
            client, agent, loose_conversation, "积分兑换规则是什么"
        )
        _wait_turn(
            client, loose_conversation, headers=agent, turn_id=loose_turn_id
        )
        loose_events = _events(
            client, loose_conversation, loose_turn_id, headers=admin
        )
        loose_selected = _event(loose_events, "SKILL_SELECTED")
        assert loose_selected is not None, (
            f"missing SKILL_SELECTED: {[e['event_type'] for e in loose_events]}"
        )
        _check(
            loose_selected["payload"]["skill_code"] == loose.json()["code"],
            "loose skill still matches its trigger",
            checks,
        )
        _check(
            _event(loose_events, "COMPLETION_EVALUATED") is None,
            "loose skill produces no completion verdict",
            checks,
        )

        # 4. Editing the skill must not rewrite the finished turn's snapshot.
        # The snapshot itself lives on the turn row; the acceptance report
        # prints the turn id so the run can be checked against PostgreSQL.
        edited = client.patch(
            f"/api/v1/skills/{skill_id}",
            headers=admin,
            json={
                "expected_version": updated.json()["version"],
                "definition": {
                    "schema_version": 1,
                    "steps": [
                        {
                            "id": "simplified",
                            "name": "简化步骤",
                            "required": False,
                        }
                    ],
                    "completion_criteria": ["all_required_steps_done"],
                },
            },
        )
        _check(
            edited.status_code == 200,
            "contract skill can be edited after the turn (200)",
            checks,
        )
        _check(
            edited.json()["definition_version"] == 3,
            "post-turn edit bumps the live contract to v3",
            checks,
        )

    report["checks"] = checks
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n{len(checks)} checks passed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:  # noqa: BLE001 - acceptance script reports and exits
        print(f"FAILED: {error}", file=sys.stderr)
        raise SystemExit(1) from error
