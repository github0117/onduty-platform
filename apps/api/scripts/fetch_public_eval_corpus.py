#!/usr/bin/env python3
"""Build a real-question evaluation corpus from public HR policy Q&A pages.

Sources (public government pages, fetched 2026-10-27):

- 甘肃政务服务网《人社政策直通车•50条》:
  https://zwfw.gansu.gov.cn/jinchang/zczx/zxfb/art/2026/art_9454f658c3374b9fa157b3a493c0fded.html
- 新疆人社厅 12333 电话咨询服务中心「热点问答」列表与详情页:
  https://rst.xinjiang.gov.cn/xjrst/c112710/list.shtml

The questions are real public questions; the answers are the published
policy answers. This is a public-domain benchmark, not the company's
de-identified internal tickets. Keep that distinction when reporting
retrieval quality.
"""

import argparse
import json
import random
import re
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

Gansu_URL = (
    "https://zwfw.gansu.gov.cn/jinchang/zczx/zxfb/art/2026/"
    "art_9454f658c3374b9fa157b3a493c0fded.html"
)
XINJIANG_BASE = "https://rst.xinjiang.gov.cn/xjrst/c112710/"
XINJIANG_PAGE_URL = re.compile(r"/xjrst/c112710/\d{6}/[0-9a-f]+\.shtml")
SECTION_PATTERN = re.compile(r"^[一二三四五六七八九十]+、")
QUESTION_PATTERN = re.compile(r"^(\d+)\.\s*问：(.*)$")
HEADERS = {"User-Agent": ("Mozilla/5.0 (compatible; knowledge-eval-research; contact: local-dev)")}
REQUEST_DELAY_SECONDS = 0.4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output_dir",
        nargs="?",
        default="../../outputs/acceptance/public_corpus",
    )
    parser.add_argument("--xinjiang-limit", type=int, default=80)
    parser.add_argument("--holdout-size", type=int, default=50)
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(
        headers=HEADERS,
        timeout=45,
        follow_redirects=True,
    ) as client:
        gansu = fetch_gansu(client)
        xinjiang = fetch_xinjiang(client, limit=args.xinjiang_limit)

    items = dedupe([*gansu, *xinjiang])
    if len(items) < args.holdout_size + 30:
        raise SystemExit(f"only {len(items)} usable Q&A pairs, need more sources")
    for index, item in enumerate(items):
        item["id"] = f"PUBLIC-HR-{index + 1:04d}"
    split = stratified_split(
        items,
        holdout_size=args.holdout_size,
        seed=20261027,
    )
    corpus_path = output_dir / "public_hr_eval.jsonl"
    corpus_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in split),
        encoding="utf-8",
    )
    summary = {
        "generated_on": date.today().isoformat(),
        "source": "public government HR policy Q&A",
        "not_internal_tickets": True,
        "total": len(split),
        "tuning": sum(item["dataset"] == "TUNING" for item in split),
        "holdout": sum(item["dataset"] == "HOLDOUT" for item in split),
        "by_source": _count_by(split, "source"),
        "by_source_dataset": _count_by_source_dataset(split),
        "question_chars": _length_range(split, "question"),
        "answer_chars": _length_range(split, "answer"),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def fetch_gansu(client: httpx.Client) -> list[dict[str, Any]]:
    response = client.get(Gansu_URL)
    response.raise_for_status()
    lines = _text_lines(response.text)
    items: list[dict[str, Any]] = []
    section = ""
    current: dict[str, Any] | None = None
    in_answer = False

    def flush() -> None:
        if current is not None and current["answer"].strip():
            items.append(current)

    for line in lines:
        if SECTION_PATTERN.match(line):
            flush()
            current = None
            section = line
            continue
        match = QUESTION_PATTERN.match(line)
        if match:
            flush()
            current = {
                "source": "gansu_policy_50",
                "source_url": Gansu_URL,
                "section": section,
                "question": match.group(2).strip(),
                "answer": "",
            }
            in_answer = False
            continue
        if current is None:
            continue
        if line.startswith("答："):
            current["answer"] = line[len("答：") :]
            in_answer = True
            continue
        if in_answer:
            current["answer"] = f"{current['answer']}{line}"
    flush()
    return [_normalize(item) for item in items]


def fetch_xinjiang(
    client: httpx.Client,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for page in range(1, 31):
        name = "list.shtml" if page == 1 else f"list_{page}.shtml"
        response = client.get(urljoin(XINJIANG_BASE, name))
        if response.status_code != 200:
            continue
        for href, title in _anchors(response.text, XINJIANG_PAGE_URL):
            if href in seen or not title or title == "[详细]":
                continue
            seen.add(href)
            links.append((href, title))
        time.sleep(REQUEST_DELAY_SECONDS)

    items: list[dict[str, Any]] = []
    for href, title in links:
        if len(items) >= limit:
            break
        response = client.get(urljoin(XINJIANG_BASE, href))
        time.sleep(REQUEST_DELAY_SECONDS)
        if response.status_code != 200:
            continue
        parsed = _parse_xinjiang_detail(response.text, title)
        if parsed is None:
            continue
        parsed.update(
            {
                "source": "xinjiang_12333",
                "source_url": urljoin(XINJIANG_BASE, href),
                "section": "12333 热点问答",
            }
        )
        items.append(_normalize(parsed))
    return items


def _parse_xinjiang_detail(
    html: str,
    fallback_question: str,
) -> dict[str, Any] | None:
    text = "\n".join(_text_lines(html))
    start = text.find("答：")
    if start < 0:
        return None
    end = text.find("【TOP】", start)
    answer = text[start + len("答：") : end if end > start else None]
    answer = re.sub(r"\s+", "", answer).strip()
    before = text[:start].rstrip().splitlines()
    question = before[-1].strip() if before else fallback_question
    if not question.endswith("？") and not question.endswith("?"):
        question = fallback_question
    if len(answer) < 20:
        return None
    return {"question": question, "answer": answer}


def stratified_split(
    items: list[dict[str, Any]],
    *,
    holdout_size: int,
    seed: int,
) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    by_source: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        by_source.setdefault(str(item["source"]), []).append(item)
    total = len(items)
    holdout_ids: set[str] = set()
    for source_items in by_source.values():
        source_holdout = round(holdout_size * len(source_items) / total)
        shuffled = list(source_items)
        rng.shuffle(shuffled)
        holdout_ids.update(str(item["id"]) for item in shuffled[:source_holdout])
    result: list[dict[str, Any]] = []
    for item in items:
        copy = dict(item)
        copy["dataset"] = "HOLDOUT" if str(item["id"]) in holdout_ids else "TUNING"
        result.append(copy)
    return result


def _normalize(item: dict[str, Any]) -> dict[str, Any]:
    question = re.sub(r"\s+", "", str(item["question"])).strip()
    question = re.sub(r"^问[:：]", "", question).strip()
    answer = re.sub(r"\s+", "", str(item["answer"])).strip()
    answer = re.sub(r"^答[:：]", "", answer).strip()
    return {
        "source": item["source"],
        "source_url": item["source_url"],
        "section": item.get("section", ""),
        "question": question,
        "answer": answer,
    }


def dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = re.sub(r"[\s，。？！,.?!、；;：:（）()]", "", item["question"])
        if not key or key in seen:
            continue
        if len(item["question"]) < 6 or len(item["answer"]) < 20:
            continue
        seen.add(key)
        result.append(item)
    return result


def _text_lines(html: str) -> list[str]:
    text = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    text = re.sub(r"<style.*?</style>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    return [
        line.replace("&nbsp;", " ").strip()
        for line in text.splitlines()
        if line.replace("&nbsp;", " ").strip()
    ]


def _anchors(
    html: str,
    pattern: re.Pattern[str],
) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for match in re.finditer(
        r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html,
        re.S,
    ):
        href = match.group(1)
        if not pattern.fullmatch(href):
            continue
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        result.append((href, title))
    return result


def _count_by(
    items: list[dict[str, Any]],
    key: str,
) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        value = str(item[key])
        result[value] = result.get(value, 0) + 1
    return result


def _count_by_source_dataset(
    items: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for item in items:
        source = str(item["source"])
        dataset = str(item["dataset"])
        bucket = result.setdefault(source, {})
        bucket[dataset] = bucket.get(dataset, 0) + 1
    return result


def _length_range(
    items: list[dict[str, Any]],
    key: str,
) -> dict[str, int]:
    lengths = [len(str(item[key])) for item in items]
    return {"min": min(lengths), "max": max(lengths)}


if __name__ == "__main__":
    main()
