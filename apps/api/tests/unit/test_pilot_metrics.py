from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_script() -> ModuleType:
    path = Path(__file__).parents[2] / "scripts" / "calculate_pilot_metrics.py"
    spec = importlib.util.spec_from_file_location("pilot_metrics", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_results(path: Path, rows: list[str]) -> None:
    header = (
        "case_id,category,mode,completed,first_response_seconds,"
        "total_seconds,handoff,grounded,citation_applicable,rework,"
        "wrong_action,cost\n"
    )
    path.write_text(header + "\n".join(rows) + "\n", encoding="utf-8")


def test_calculate_pilot_metrics(tmp_path: Path) -> None:
    script = _load_script()
    results = tmp_path / "results.csv"
    _write_results(
        results,
        [
            "C1,商品,baseline,1,20,40,0,0,0,0,0,1",
            "C1,商品,platform,1,5,10,0,1,1,0,0,0.2",
            "C2,退款,baseline,0,30,80,1,0,0,1,1,1",
            "C2,退款,platform,1,8,20,1,1,1,0,0,0.3",
        ],
    )

    report = script.build_report(script.load_rows(results))

    assert report["classification"] == "controlled_simulation"
    assert report["case_count"] == 2
    assert report["by_mode"]["baseline"]["task_completion_rate"] == 0.5
    assert report["by_mode"]["platform"]["task_completion_rate"] == 1.0
    assert report["by_mode"]["platform"]["auto_resolution_rate"] == 0.5
    assert report["by_mode"]["platform"]["citation_support_rate"] == 1.0
    assert report["by_mode"]["platform"]["cost_per_completed"] == 0.25


def test_reject_unpaired_case(tmp_path: Path) -> None:
    script = _load_script()
    results = tmp_path / "results.csv"
    _write_results(
        results,
        ["C1,商品,baseline,1,20,40,0,0,0,0,0,1"],
    )

    with pytest.raises(script.MetricsError, match="baseline and platform"):
        script.load_rows(results)


def test_reject_duplicate_row(tmp_path: Path) -> None:
    script = _load_script()
    results = tmp_path / "results.csv"
    _write_results(
        results,
        [
            "C1,商品,baseline,1,20,40,0,0,0,0,0,1",
            "C1,商品,baseline,1,20,40,0,0,0,0,0,1",
        ],
    )

    with pytest.raises(script.MetricsError, match="duplicate"):
        script.load_rows(results)
