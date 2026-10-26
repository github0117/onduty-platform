#!/usr/bin/env python3
"""Calculate comparable baseline/platform metrics for the independent pilot."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

MODES = {"baseline", "platform"}
INTEGER_FIELDS = {
    "completed",
    "handoff",
    "grounded",
    "citation_applicable",
    "rework",
    "wrong_action",
}
NUMBER_FIELDS = {"first_response_seconds", "total_seconds", "cost"}
REQUIRED_FIELDS = {
    "case_id",
    "category",
    "mode",
    *INTEGER_FIELDS,
    *NUMBER_FIELDS,
}


class MetricsError(ValueError):
    """Raised when the pilot result file cannot be compared safely."""


def _parse_int(row: dict[str, str], field: str, line: int) -> int:
    value = row[field].strip()
    if value not in {"0", "1"}:
        raise MetricsError(f"line {line}: {field} must be 0 or 1")
    return int(value)


def _parse_number(
    row: dict[str, str],
    field: str,
    line: int,
) -> float | None:
    value = row[field].strip()
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise MetricsError(f"line {line}: {field} must be numeric") from exc
    if parsed < 0:
        raise MetricsError(f"line {line}: {field} must not be negative")
    return parsed


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = REQUIRED_FIELDS - set(reader.fieldnames or [])
        if missing:
            raise MetricsError(
                "missing columns: " + ", ".join(sorted(missing))
            )
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for line, raw in enumerate(reader, start=2):
            case_id = raw["case_id"].strip()
            category = raw["category"].strip()
            mode = raw["mode"].strip()
            if not case_id or not category or mode not in MODES:
                raise MetricsError(
                    f"line {line}: case_id/category/mode is invalid"
                )
            key = (case_id, mode)
            if key in seen:
                raise MetricsError(
                    f"line {line}: duplicate {case_id}/{mode}"
                )
            seen.add(key)
            row: dict[str, Any] = {
                "case_id": case_id,
                "category": category,
                "mode": mode,
            }
            for field in INTEGER_FIELDS:
                row[field] = _parse_int(raw, field, line)
            for field in NUMBER_FIELDS:
                row[field] = _parse_number(raw, field, line)
            rows.append(row)
    _validate_pairs(rows)
    return rows


def _validate_pairs(rows: list[dict[str, Any]]) -> None:
    modes_by_case: dict[str, set[str]] = defaultdict(set)
    categories_by_case: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        modes_by_case[row["case_id"]].add(row["mode"])
        categories_by_case[row["case_id"]].add(row["category"])
    incomplete = [
        case_id
        for case_id, modes in modes_by_case.items()
        if modes != MODES
    ]
    if incomplete:
        raise MetricsError(
            "each case needs baseline and platform rows: "
            + ", ".join(sorted(incomplete))
        )
    inconsistent = [
        case_id
        for case_id, categories in categories_by_case.items()
        if len(categories) != 1
    ]
    if inconsistent:
        raise MetricsError(
            "category changed between modes: "
            + ", ".join(sorted(inconsistent))
        )


def _rate(rows: list[dict[str, Any]], predicate: Any) -> float | None:
    if not rows:
        return None
    return sum(1 for row in rows if predicate(row)) / len(rows)


def _percentile(values: list[float], ratio: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(ratio * len(ordered)) - 1)
    return ordered[index]


def _number_values(rows: list[dict[str, Any]], field: str) -> list[float]:
    return [
        float(row[field])
        for row in rows
        if row[field] is not None
    ]


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "case_count": len(rows),
        "task_completion_rate": _rate(
            rows,
            lambda row: row["completed"] == 1,
        ),
        "first_response_p50_seconds": _percentile(
            _number_values(rows, "first_response_seconds"),
            0.5,
        ),
        "first_response_p90_seconds": _percentile(
            _number_values(rows, "first_response_seconds"),
            0.9,
        ),
        "average_total_seconds": _average(
            _number_values(rows, "total_seconds")
        ),
        "handoff_rate": _rate(rows, lambda row: row["handoff"] == 1),
        "auto_resolution_rate": _rate(
            rows,
            lambda row: row["completed"] == 1 and row["handoff"] == 0,
        ),
        "citation_support_rate": _fraction(
            sum(
                row["grounded"]
                for row in rows
                if row["citation_applicable"] == 1
            ),
            sum(row["citation_applicable"] for row in rows),
        ),
        "rework_rate": _rate(rows, lambda row: row["rework"] == 1),
        "wrong_action_count": sum(row["wrong_action"] for row in rows),
        "total_cost": sum(_number_values(rows, "cost")),
        "cost_per_completed": _fraction(
            sum(_number_values(rows, "cost")),
            sum(row["completed"] for row in rows),
        ),
    }


def _fraction(numerator: float, denominator: int | float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_mode = {
        mode: summarize([row for row in rows if row["mode"] == mode])
        for mode in sorted(MODES)
    }
    categories = sorted({str(row["category"]) for row in rows})
    by_category = {
        category: {
            mode: summarize(
                [
                    row
                    for row in rows
                    if row["category"] == category
                    and row["mode"] == mode
                ]
            )
            for mode in sorted(MODES)
        }
        for category in categories
    }
    return {
        "classification": "controlled_simulation",
        "case_count": len({str(row["case_id"]) for row in rows}),
        "by_mode": by_mode,
        "by_category": by_category,
    }


def render_markdown(report: dict[str, Any]) -> str:
    baseline = report["by_mode"]["baseline"]
    platform = report["by_mode"]["platform"]
    lines = [
        "# 独立试点结果",
        "",
        "分类：受控模拟试点，不代表真实生产收益。",
        "",
        "| 指标 | 基线组 | 平台组 |",
        "|---|---:|---:|",
    ]
    labels = {
        "case_count": "样本数",
        "task_completion_rate": "任务完成率",
        "first_response_p50_seconds": "首响 P50（秒）",
        "first_response_p90_seconds": "首响 P90（秒）",
        "average_total_seconds": "平均处理耗时（秒）",
        "handoff_rate": "人工接管率",
        "auto_resolution_rate": "自动解决率",
        "citation_support_rate": "引用支持率",
        "rework_rate": "人工返工率",
        "wrong_action_count": "错误动作数",
        "total_cost": "总成本",
        "cost_per_completed": "单个完成任务成本",
    }
    for key, label in labels.items():
        lines.append(
            f"| {label} | {_format_value(baseline[key])} | "
            f"{_format_value(platform[key])} |"
        )
    lines.extend(["", "## 分类结果", ""])
    lines.append("| 分类 | 模式 | 完成率 | 接管率 | 引用支持率 | 错误动作 |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for category, modes in report["by_category"].items():
        for mode, summary in modes.items():
            lines.append(
                f"| {category} | {mode} | "
                f"{_format_value(summary['task_completion_rate'])} | "
                f"{_format_value(summary['handoff_rate'])} | "
                f"{_format_value(summary['citation_support_rate'])} | "
                f"{summary['wrong_action_count']} |"
            )
    return "\n".join(lines) + "\n"


def _format_value(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    report = build_report(load_rows(args.results))
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
