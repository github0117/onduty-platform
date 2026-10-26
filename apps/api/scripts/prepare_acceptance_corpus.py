#!/usr/bin/env python3
import json
import sys
from pathlib import Path

ENTERPRISE_CATEGORIES = [
    ("product_howto", "R0", "制度与流程咨询"),
    ("access_identity", "R0", "账号与权限问题"),
    ("service_incident", "R1", "IT 故障与报障"),
    ("billing_invoice", "R1", "财务与发票问题"),
]

ECOMMERCE_CATEGORIES = [
    ("ecommerce_presales", "R0", "商品咨询"),
    ("ecommerce_aftersales", "R2", "退款与售后"),
    ("transaction_dispute", "R2", "交易争议"),
    ("complaint_escalation", "R2", "投诉升级"),
]


def main() -> None:
    output_dir = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "../../outputs/acceptance/corpus"
    ).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    tickets = [_ticket(index) for index in range(1, 121)]
    knowledge = [_knowledge(index) for index in range(1, 31)]
    evaluations = [_evaluation(index) for index in range(1, 61)]

    _write_jsonl(output_dir / "tickets.jsonl", tickets)
    _write_jsonl(output_dir / "knowledge.jsonl", knowledge)
    _write_jsonl(output_dir / "evaluations.jsonl", evaluations)

    summary = {
        "tickets": len(tickets),
        "knowledge_documents": len(knowledge),
        "evaluation_questions": len(evaluations),
        "enterprise_cases": sum(
            item["scenario"] == "enterprise" for item in tickets
        ),
        "ecommerce_cases": sum(
            item["scenario"] == "ecommerce" for item in tickets
        ),
        "risks": {
            risk: sum(item["risk_level"] == risk for item in tickets)
            for risk in ("R0", "R1", "R2", "R3")
        },
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def _ticket(index: int) -> dict[str, object]:
    enterprise = index % 2 == 1
    categories = ENTERPRISE_CATEGORIES if enterprise else ECOMMERCE_CATEGORIES
    category, risk, label = categories[(index // 2) % len(categories)]
    if index % 15 == 0:
        category, risk, label = "data_privacy_security", "R3", "隐私安全事件"
    return {
        "id": f"ACCEPT-TICKET-{index:03d}",
        "scenario": "enterprise" if enterprise else "ecommerce",
        "business_unit_id": "bu_acceptance",
        "category_primary": category,
        "risk_level": risk,
        "subject": f"{label}示例 {index:03d}",
        "body": (
            f"这是用于最终验收的模拟问题 {index:03d}。"
            "请根据企业知识或模拟业务系统判断处理方式。"
        ),
        "expected": {
            "human_review": risk in {"R2", "R3"},
            "must_cite": category in {"product_howto", "ecommerce_presales"},
        },
    }


def _knowledge(index: int) -> dict[str, object]:
    category = (
        ENTERPRISE_CATEGORIES
        if index % 2 == 1
        else ECOMMERCE_CATEGORIES
    )[index % 4]
    return {
        "id": f"ACCEPT-DOC-{index:03d}",
        "business_unit_id": "bu_acceptance",
        "title": f"{category[2]}验收资料 {index:03d}",
        "doc_type": "SOP" if index % 2 else "POLICY",
        "category": category[0],
        "version": "1.0",
        "scope": {"audiences": ["support_agent"]},
        "content": (
            f"{category[2]}的标准处理流程：确认请求、核对权限、检索依据、"
            "记录结论；涉及资金、隐私或外部写操作时必须转人工审批。"
        ),
    }


def _evaluation(index: int) -> dict[str, object]:
    document_index = ((index - 1) % 30) + 1
    document = _knowledge(document_index)
    no_answer = index % 10 == 0
    return {
        "id": f"ACCEPT-EVAL-{index:03d}",
        "business_unit_id": "bu_acceptance",
        "query": (
            f"公司是否报销火星基地差旅补贴 {index:03d}"
            if no_answer
            else f"请查找《{document['title']}》并说明处理流程"
        ),
        "expected_space": "模拟验收知识空间",
        "expected_document_id": (
            None if no_answer else document["id"]
        ),
        "should_refuse": no_answer,
    }


def _write_jsonl(path: Path, items: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(item, ensure_ascii=False) + "\n"
            for item in items
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
