from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_script() -> ModuleType:
    path = (
        Path(__file__).parents[2]
        / "scripts"
        / "seed_acceptance_corpus.py"
    )
    spec = importlib.util.spec_from_file_location(
        "seed_acceptance_corpus", path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class _Client:
    def __init__(self, cases_by_dataset: dict[str, list[dict[str, Any]]]) -> None:
        self._cases_by_dataset = cases_by_dataset
        self.writes: list[str] = []

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> _Response:
        dataset = (params or {}).get("dataset", "TUNING")
        return _Response(self._cases_by_dataset.get(dataset, []))

    def post(self, url: str, **kwargs: Any) -> _Response:
        self.writes.append(f"POST {url}")
        raise AssertionError("frozen HOLDOUT cases must not be rewritten")

    def patch(self, url: str, **kwargs: Any) -> _Response:
        self.writes.append(f"PATCH {url}")
        raise AssertionError("frozen HOLDOUT cases must not be rewritten")


def _item(*, expect_passage: bool = True) -> dict[str, Any]:
    return {
        "id": "ACCEPT-EVAL-H-003",
        "dataset": "HOLDOUT",
        "query": "签收后多久可以退款",
        "should_refuse": False,
        "expected_document_id": "doc-1",
        "expect_passage": expect_passage,
        "expect_chunk": False,
    }


def _documents() -> dict[str, dict[str, Any]]:
    return {
        "doc-1": {
            "document_id": "11111111-1111-1111-1111-111111111111",
            "title": "退款政策",
            "content": "签收后七天内可以申请退款。",
            "chunk_ids": ["22222222-2222-2222-2222-222222222222"],
        }
    }


def test_reseed_warns_when_frozen_holdout_case_lacks_passage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    client = _Client(
        {
            "HOLDOUT": [
                {
                    "name": "验收问题 ACCEPT-EVAL-H-003",
                    "expected_passages": [],
                }
            ]
        }
    )

    count = module._seed_evaluations(
        client, [_item()], documents=_documents()
    )

    captured = capsys.readouterr()
    assert count == 1
    assert client.writes == []
    assert "frozen HOLDOUT case(s) have no passage" in captured.err
    assert "--reset" in captured.err


def test_reseed_is_silent_when_frozen_case_already_has_passage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    client = _Client(
        {
            "HOLDOUT": [
                {
                    "name": "验收问题 ACCEPT-EVAL-H-003",
                    "expected_passages": [
                        {
                            "document_id": (
                                "11111111-1111-1111-1111-111111111111"
                            ),
                            "text": "签收后七天内可以申请退款。",
                        }
                    ],
                }
            ]
        }
    )

    module._seed_evaluations(client, [_item()], documents=_documents())

    captured = capsys.readouterr()
    assert client.writes == []
    assert "frozen HOLDOUT case(s)" not in captured.err


def test_reseed_does_not_warn_for_cases_without_passage_expectation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script()
    client = _Client(
        {"HOLDOUT": [{"name": "验收问题 ACCEPT-EVAL-H-003"}]}
    )

    module._seed_evaluations(
        client, [_item(expect_passage=False)], documents=_documents()
    )

    captured = capsys.readouterr()
    assert "frozen HOLDOUT case(s)" not in captured.err
