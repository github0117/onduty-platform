#!/usr/bin/env python3
"""对运行中的 OnDuty 服务做只读并发冒烟压测。

默认目标是一组高频只读接口（工单列表、会话列表、员工列表、客服指标），
不写业务数据。指标只代表当前 Docker Compose / 单机环境，不代表生产容量。

用法（仓库根目录）：

    uv run --project apps/api python scripts/load_test.py \
        --concurrency 50 --duration 60 --json outputs/load-test.json

压测前请确认 API 已启动且演示数据已写入。脚本使用开发身份头登录，
仅在 APP_AUTH_MODE=dev 的本地或预发演示环境使用。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

DEFAULT_PATHS = (
    "/api/v1/tickets?limit=50",
    "/api/v1/customer-service/conversations",
    "/api/v1/digital-employees",
    "/api/v1/customer-service/metrics",
)


@dataclass
class Sample:
    latency_ms: float
    status: int | None
    error: str | None = None


@dataclass
class Result:
    samples: list[Sample] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float = 0.0


def _percentile(sorted_values: list[float], percent: float) -> float:
    if not sorted_values:
        return 0.0
    index = math.ceil(percent / 100 * len(sorted_values)) - 1
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]


def _url(base_url: str, path: str, business_unit_id: str) -> str:
    if "business_unit_id=" in path:
        url = f"{base_url.rstrip('/')}{path}"
    else:
        separator = "&" if "?" in path else "?"
        url = f"{base_url.rstrip('/')}{path}{separator}business_unit_id={business_unit_id}"
    return url


async def _request(
    client: httpx.AsyncClient,
    url: str,
    timeout: float,
) -> Sample:
    started = time.perf_counter()
    try:
        response = await client.get(url, timeout=timeout)
        latency_ms = (time.perf_counter() - started) * 1000
        return Sample(latency_ms=latency_ms, status=response.status_code)
    except Exception as exc:  # noqa: BLE001 - 压测需要按错误类型汇总
        latency_ms = (time.perf_counter() - started) * 1000
        return Sample(
            latency_ms=latency_ms,
            status=None,
            error=type(exc).__name__,
        )


async def _warmup(
    client: httpx.AsyncClient,
    urls: list[str],
    timeout: float,
) -> list[Sample]:
    samples = []
    for url in urls:
        samples.append(await _request(client, url, timeout))
    return samples


async def _worker(
    client: httpx.AsyncClient,
    urls: list[str],
    *,
    index: int,
    deadline: float,
    timeout: float,
    result: Result,
) -> None:
    position = index
    while time.monotonic() < deadline:
        sample = await _request(client, urls[position % len(urls)], timeout)
        result.samples.append(sample)
        position += 1


async def run(args: argparse.Namespace) -> tuple[Result, list[Sample]]:
    result = Result()
    headers = {
        "X-Actor-Id": args.actor_id,
        "X-Actor-Role": args.actor_role,
        "X-Business-Unit-Id": args.business_unit_id,
    }
    urls = [_url(args.base_url, path, args.business_unit_id) for path in args.paths]
    limits = httpx.Limits(
        max_connections=args.concurrency,
        max_keepalive_connections=args.concurrency,
    )
    async with httpx.AsyncClient(
        headers=headers,
        limits=limits,
        timeout=args.timeout,
    ) as client:
        warmup = await _warmup(client, urls, args.timeout)
        failed = [
            sample for sample in warmup if sample.status is None or not 200 <= sample.status < 300
        ]
        if failed:
            details = ", ".join(f"{sample.status or sample.error}" for sample in failed)
            raise SystemExit(f"预热请求失败，请检查 API、身份头和演示数据：{details}")

        result.started_at = time.time()
        deadline = time.monotonic() + args.duration
        await asyncio.gather(
            *(
                _worker(
                    client,
                    urls,
                    index=index,
                    deadline=deadline,
                    timeout=args.timeout,
                    result=result,
                )
                for index in range(args.concurrency)
            )
        )
        result.finished_at = time.time()
    return result, warmup


def summarize(
    result: Result,
    warmup: list[Sample],
    args: argparse.Namespace,
) -> dict[str, Any]:
    elapsed = max(result.finished_at - result.started_at, 1e-9)
    latencies = sorted(sample.latency_ms for sample in result.samples)
    statuses = Counter(
        str(sample.status) if sample.status is not None else "ERROR" for sample in result.samples
    )
    errors = Counter(sample.error for sample in result.samples if sample.error is not None)
    success = sum(
        1 for sample in result.samples if sample.status is not None and 200 <= sample.status < 300
    )
    total = len(result.samples)
    return {
        "started_at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(result.started_at),
        ),
        "base_url": args.base_url,
        "concurrency": args.concurrency,
        "duration_seconds": args.duration,
        "paths": list(args.paths),
        "requests": total,
        "success": success,
        "success_rate_percent": round(success / total * 100, 2) if total else 0.0,
        "throughput_rps": round(total / elapsed, 2),
        "latency_ms": {
            "p50": round(_percentile(latencies, 50), 2),
            "p95": round(_percentile(latencies, 95), 2),
            "p99": round(_percentile(latencies, 99), 2),
            "max": round(latencies[-1], 2) if latencies else 0.0,
        },
        "status_counts": dict(sorted(statuses.items())),
        "errors": dict(sorted(errors.items())),
        "warmup_latency_ms": [round(sample.latency_ms, 2) for sample in warmup],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OnDuty 只读并发冒烟压测",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="API 地址",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=50,
        help="并发 worker 数",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=60.0,
        help="计时压测时长（秒）",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="单请求超时（秒）",
    )
    parser.add_argument(
        "--actor-id",
        default="loadtest-monitor",
        help="开发身份头中的 actor id",
    )
    parser.add_argument(
        "--actor-role",
        default="admin",
        help="开发身份头中的角色",
    )
    parser.add_argument(
        "--business-unit-id",
        default="bu_demo",
        help="压测使用的业务单元",
    )
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        help="只读接口路径，可重复",
    )
    parser.add_argument(
        "--max-error-rate",
        type=float,
        default=1.0,
        help="允许的最大错误率（百分比），超过则退出码为 1",
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="将汇总结果写入 JSON 文件",
    )
    args = parser.parse_args()
    args.paths = tuple(args.paths) if args.paths else DEFAULT_PATHS
    if args.concurrency < 1:
        raise SystemExit("--concurrency 必须大于 0")
    if args.duration <= 0:
        raise SystemExit("--duration 必须大于 0")

    result, warmup = asyncio.run(run(args))
    summary = summarize(result, warmup, args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    error_rate = 100 - summary["success_rate_percent"]
    if error_rate > args.max_error_rate:
        raise SystemExit(f"错误率 {error_rate:.2f}% 超过阈值 {args.max_error_rate:.2f}%")


if __name__ == "__main__":
    main()
