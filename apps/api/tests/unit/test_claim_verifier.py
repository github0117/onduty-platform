import json
from typing import Any

import httpx

from ticket_agent.knowledge.claim_evaluation import (
    ClaimEvaluationCase,
    ClaimPrediction,
    calibrate_abstention_threshold,
    evaluate_claim_predictions,
)
from ticket_agent.knowledge.claim_verifier import (
    ClaimToVerify,
    ExternalClaimVerifier,
    HeuristicClaimVerifier,
)
from ticket_agent.shared.settings import Settings


def test_heuristic_claim_verifier_scores_lexical_support() -> None:
    verifier = HeuristicClaimVerifier()
    results = verifier.verify(
        [
            ClaimToVerify(
                claim_index=0,
                text="管理员进入设置中心配置团队通知。",
                claim_type="instruction",
                sources=["管理员进入设置中心配置团队消息通知。"],
            ),
            ClaimToVerify(
                claim_index=1,
                text="退款将在三个工作日内原路返回。",
                claim_type="policy",
                sources=["退款申请需要人工审核。"],
            ),
        ]
    )

    assert results[0].verdict == "supported"
    assert results[1].verdict == "unsupported"


def test_external_claim_verifier_uses_structured_response() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "verifications": [
                                        {
                                            "claim_index": 0,
                                            "verdict": "supported",
                                            "confidence": 0.93,
                                            "reason": "来源明确包含该配置步骤",
                                        }
                                    ]
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    settings = Settings(
        claim_verifier_provider="external",
        claim_verifier_base_url="https://judge.example/v1",
        claim_verifier_api_key="judge-secret",
        claim_verifier_model_name="claim-judge",
        claim_verifier_fallback_to_local=False,
    )
    verifier = ExternalClaimVerifier(
        settings,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    results = verifier.verify(
        [
            ClaimToVerify(
                claim_index=0,
                text="管理员在设置中心配置通知。",
                claim_type="instruction",
                sources=["管理员进入设置中心，打开通知配置。联系我们 test@example.com。"],
            )
        ]
    )

    assert results[0].verdict == "supported"
    assert results[0].provider == "external"
    assert results[0].confidence == 0.93
    assert "<EMAIL>" in captured["payload"]["messages"][1]["content"]


def test_claim_evaluation_calibrates_abstention_threshold() -> None:
    cases = [
        ClaimEvaluationCase(
            case_id="a",
            claim_text="supported",
            claim_type="policy",
            sources=["source"],
            expected_verdict="supported",
        ),
        ClaimEvaluationCase(
            case_id="b",
            claim_text="wrong low confidence",
            claim_type="policy",
            sources=["source"],
            expected_verdict="unsupported",
        ),
        ClaimEvaluationCase(
            case_id="c",
            claim_text="explicit uncertain",
            claim_type="policy",
            sources=["source"],
            expected_verdict="uncertain",
        ),
        ClaimEvaluationCase(
            case_id="d",
            claim_text="unsupported",
            claim_type="policy",
            sources=["source"],
            expected_verdict="unsupported",
        ),
    ]
    predictions = [
        ClaimPrediction(verdict="supported", confidence=0.9),
        ClaimPrediction(verdict="supported", confidence=0.4),
        ClaimPrediction(verdict="uncertain", confidence=0.7),
        ClaimPrediction(verdict="unsupported", confidence=0.8),
    ]

    metrics = evaluate_claim_predictions(cases, predictions)
    calibration = calibrate_abstention_threshold(
        cases,
        predictions,
        minimum_coverage=0.5,
    )

    assert metrics["case_count"] == 4
    assert metrics["accuracy"] == 0.75
    assert metrics["confusion_matrix"]["supported"]["supported"] == 1
    assert calibration["recommended_threshold"] >= 0.45
    assert calibration["best"]["selective_accuracy"] == 1.0

