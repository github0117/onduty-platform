#!/usr/bin/env python3
"""Audit third-party dependency licenses for Python and Node.

The check fails closed: copyleft licenses that would contaminate a
commercially distributed product (AGPL, GPL, SSPL, BUSL, ...) block the
build, and any license the script cannot classify must be registered in
the review allowlist together with a reason.

Usage:
    uv run --project apps/api python scripts/check_licenses.py
    uv run --project apps/api python scripts/check_licenses.py --skip-node
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = ROOT / "docs" / "licensing"
DEFAULT_REPORT = REPORT_DIR / "third-party-licenses.csv"
DEFAULT_ALLOWLIST = REPORT_DIR / "review-allowlist.txt"

# Permissive licenses: safe for closed-source distribution.
ALLOWED = {
    "0bsd",
    "apache-2.0",
    "blueoak-1.0.0",
    "bsd-2-clause",
    "bsd-3-clause",
    "bsl-1.0",
    "cc-by-4.0",
    "cc0-1.0",
    "hpnd",
    "isc",
    "mit",
    "mit-0",
    "mit-cmu",
    "psf-2.0",
    "python-2.0",
    "unlicense",
    "zlib",
}

# Weak copyleft: usable as an unmodified dependency, but each occurrence
# must be acknowledged explicitly in the review allowlist.
REVIEW = {
    "cddl-1.0",
    "epl-2.0",
    "lgpl-2.1",
    "lgpl-3.0",
    "mpl-2.0",
}

# Strong copyleft / source-available licenses: block outright.
DENIED = {
    "agpl-3.0",
    "busl-1.1",
    "commons-clause",
    "elastic-2.0",
    "gpl-2.0",
    "gpl-3.0",
    "sspl-1.0",
    "cc-by-nc-4.0",
}

# Free-text spellings that appear in package metadata instead of SPDX ids.
ALIASES = {
    "apache 2.0": "apache-2.0",
    "apache license, version 2.0": "apache-2.0",
    "apache software license": "apache-2.0",
    "bsd": "bsd-3-clause",
    "bsd license": "bsd-3-clause",
    "bsd license (see license.txt for details)": "bsd-3-clause",
    "modified bsd": "bsd-3-clause",
    "mozilla public 2.0 (mpl 2.0": "mpl-2.0",
    "mozilla public license 2.0 (mpl 2.0)": "mpl-2.0",
    "new bsd": "bsd-3-clause",
    "mit license": "mit",
    "python software foundation license": "psf-2.0",
}

# Boilerplate that says nothing about the license terms themselves. Anything
# after a copyright notice is attribution, not terms.
_NOISE = re.compile(
    r"(copyright[\s\S]*$|see (?:the )?license\.txt[^,;]*|for details|"
    r"dependency licen[cs]es?|and (?:its|their) dependencies)",
    re.IGNORECASE,
)

_SUFFIXES = ("-only", "-or-later")
_SPLIT_OR = re.compile(r"\s+OR\s+", re.IGNORECASE)
_SPLIT_AND = re.compile(r"\s+AND\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Package:
    ecosystem: str
    name: str
    version: str
    license_raw: str


@dataclass(frozen=True)
class Verdict:
    status: str  # allowed | review | denied | unknown
    reason: str


def _normalize_atom(text: str) -> str:
    value = _NOISE.sub(" ", text)
    value = value.strip().strip("(),;.").strip()
    value = re.sub(r"\s+", " ", value).lower()
    # Aliases must be matched before "license" is dropped: "Apache Software
    # License" and "Apache License, Version 2.0" only resolve via the table.
    alias = ALIASES.get(value)
    if alias:
        return alias
    value = value.replace(" license", "").replace(" licence", "")
    for suffix in _SUFFIXES:
        value = value.replace(suffix, "")
    value = value.strip("(),;.").strip()
    return ALIASES.get(value, value)


def _classify_atom(text: str) -> Verdict:
    atom = _normalize_atom(text)
    if not atom:
        return Verdict("unknown", "empty license")
    if atom in ALLOWED:
        return Verdict("allowed", atom)
    if atom in REVIEW:
        return Verdict("review", atom)
    if atom in DENIED:
        return Verdict("denied", atom)
    # Text such as "BSD-3-Clause, Apache-2.0" lists several licenses inline;
    # accept it only when every token is allowed.
    tokens = [token for token in re.split(r"[,/;]| and ", atom) if token.strip()]
    if len(tokens) > 1:
        return _combine_and([_classify_atom(token) for token in tokens])
    return Verdict("unknown", atom)


def _combine_and(verdicts: list[Verdict]) -> Verdict:
    statuses = {verdict.status for verdict in verdicts}
    if not statuses:
        return Verdict("unknown", "empty license")
    if "denied" in statuses:
        return Verdict("denied", "; ".join(v.reason for v in verdicts if v.status == "denied"))
    if "unknown" in statuses:
        return Verdict("unknown", "; ".join(v.reason for v in verdicts if v.status == "unknown"))
    if "review" in statuses:
        return Verdict("review", "; ".join(v.reason for v in verdicts if v.status == "review"))
    return Verdict("allowed", "; ".join(v.reason for v in verdicts))


def classify(license_text: str) -> Verdict:
    """Classify an SPDX expression or free-text license field."""
    text = (license_text or "").strip()
    if not text or text.lower() in {"none", "unknown", "unlicensed"}:
        return Verdict("unknown", "no license declared")
    branches = [branch for branch in _SPLIT_OR.split(text) if branch.strip()]
    if len(branches) > 1:
        # "MIT OR Apache-2.0" is safe: the consumer may pick the permissive one.
        # A denied token still blocks, because it signals a copyleft variant.
        branch_verdicts = [
            _combine_and([_classify_atom(a) for a in _SPLIT_AND.split(b)]) for b in branches
        ]
        statuses = {v.status for v in branch_verdicts}
        if "denied" in statuses and not statuses.difference({"denied", "review", "unknown"}):
            return Verdict(
                "denied", "; ".join(v.reason for v in branch_verdicts if v.status == "denied")
            )
        if "allowed" in statuses:
            return Verdict(
                "allowed", "; ".join(v.reason for v in branch_verdicts if v.status == "allowed")
            )
        if "review" in statuses:
            return Verdict(
                "review", "; ".join(v.reason for v in branch_verdicts if v.status == "review")
            )
        return Verdict("unknown", "; ".join(v.reason for v in branch_verdicts))
    return _combine_and([_classify_atom(a) for a in _SPLIT_AND.split(text)])


def python_packages() -> list[Package]:
    import importlib.metadata as metadata

    packages: list[Package] = []
    for dist in metadata.distributions():
        meta = dist.metadata
        name = meta.get("Name") or "unknown"
        if name.lower().replace("_", "-") == "ticket-agent-api":
            continue
        expression = (meta.get("License-Expression") or "").strip()
        free_text = (meta.get("License") or "").strip()
        classifiers = [
            item.split("::")[-1].strip()
            for item in meta.get_all("Classifier") or []
            if item.startswith("License ::")
        ]
        classifier_text = " OR ".join(dict.fromkeys(classifiers))
        raw = expression or free_text
        if classify(raw).status == "unknown" and classifier_text:
            # "Dual License" and truncated free text carry no usable terms;
            # the trove classifiers do.
            raw = classifier_text
        packages.append(Package("python", name, dist.version, raw or ""))
    return packages


def node_packages(web_root: Path) -> list[Package]:
    packages: dict[tuple[str, str], Package] = {}
    node_modules = web_root / "node_modules"
    store = node_modules / ".pnpm"
    candidates = list(node_modules.glob("*/package.json"))
    candidates += list(node_modules.glob("@*/*/package.json"))
    candidates += list(store.glob("*/node_modules/*/package.json"))
    # Scoped packages live one directory deeper: @scope/name.
    candidates += list(store.glob("*/node_modules/@*/*/package.json"))
    for path in candidates:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get("name")
        if not name:
            continue
        raw = data.get("license") or data.get("licenses") or ""
        if isinstance(raw, dict):
            raw = raw.get("type", "")
        if isinstance(raw, list):
            raw = " OR ".join(
                item.get("type", "") if isinstance(item, dict) else str(item) for item in raw
            )
        key = (name, str(data.get("version", "")))
        packages[key] = Package("node", name, key[1], str(raw))
    return list(packages.values())


def load_allowlist(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    if not path.exists():
        return entries
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entry, _, reason = stripped.partition("#")
        key = entry.strip().lower()
        if key:
            entries[key] = reason.strip()
    return entries


def _allowlist_key(package: Package) -> str:
    return f"{package.ecosystem}:{package.name.lower()}"


def _display(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    parser.add_argument("--web-root", type=Path, default=ROOT / "apps" / "web")
    parser.add_argument("--skip-node", action="store_true", help="Python dependencies only")
    parser.add_argument("--node-only", action="store_true", help="Node dependencies only")
    args = parser.parse_args()
    if args.skip_node and args.node_only:
        parser.error("--skip-node and --node-only are mutually exclusive")

    packages = [] if args.node_only else python_packages()
    if not args.skip_node:
        packages += node_packages(args.web_root)
    packages.sort(key=lambda item: (item.ecosystem, item.name.lower(), item.version))

    allowlist = load_allowlist(args.allowlist)
    rows: list[tuple[Package, Verdict, str]] = []
    denied: list[tuple[Package, Verdict]] = []
    unregistered: list[tuple[Package, Verdict]] = []

    for package in packages:
        verdict = classify(package.license_raw)
        note = allowlist.get(_allowlist_key(package), "")
        if verdict.status == "denied":
            denied.append((package, verdict))
        elif verdict.status == "unknown" and not note or verdict.status == "review" and not note:
            unregistered.append((package, verdict))
        rows.append((package, verdict, note))

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            ["ecosystem", "name", "version", "license", "status", "reason", "allowlist_note"]
        )
        for package, verdict, note in rows:
            writer.writerow(
                [
                    package.ecosystem,
                    package.name,
                    package.version,
                    package.license_raw,
                    verdict.status,
                    verdict.reason,
                    note,
                ]
            )

    counts: dict[str, int] = {}
    for _, verdict, _ in rows:
        counts[verdict.status] = counts.get(verdict.status, 0) + 1
    print(
        f"checked={len(rows)} "
        + " ".join(
            f"{status}={counts.get(status, 0)}"
            for status in ("allowed", "review", "unknown", "denied")
        )
    )
    print(f"report={_display(args.report)}")

    if denied:
        print("\nDENIED licenses (blocked):", file=sys.stderr)
        for package, verdict in denied:
            print(
                f"  {package.ecosystem} {package.name}=={package.version} -> {verdict.reason}",
                file=sys.stderr,
            )
    if unregistered:
        print(
            "\nUnregistered review/unknown licenses. Register them in "
            f"{_display(args.allowlist)} with a reason, e.g. "
            "'python:psycopg # LGPL-3.0, used unmodified via dynamic linking':",
            file=sys.stderr,
        )
        for package, verdict in unregistered:
            print(
                f"  {_allowlist_key(package)}=={package.version} -> {verdict.reason}",
                file=sys.stderr,
            )

    return 1 if denied or unregistered else 0


if __name__ == "__main__":
    raise SystemExit(main())
