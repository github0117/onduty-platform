import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[4] / "scripts" / "check_licenses.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_licenses", _MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolve string annotations through sys.modules, so the
    # module must be registered before it is executed.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def licenses() -> ModuleType:
    return _load_module()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("MIT", "allowed"),
        ("BSD-3-Clause", "allowed"),
        ("Apache License, Version 2.0", "allowed"),
        ("MIT OR Apache-2.0", "allowed"),
        ("BSD-3-Clause, Apache-2.0, dependency licenses", "allowed"),
        (
            "BSD license (see license.txt for details), Copyright (c) 2000-2025, ReportLab Inc.",
            "allowed",
        ),
        ("MPL-2.0", "review"),
        ("LGPL-3.0-only", "review"),
        ("AGPL-3.0", "denied"),
        ("GPL-3.0-only", "denied"),
        ("SSPL-1.0", "denied"),
        ("BUSL-1.1", "denied"),
        ("MIT AND AGPL-3.0", "denied"),
        ("", "unknown"),
        ("Dual License", "unknown"),
        ("Totally Custom Terms", "unknown"),
    ],
)
def test_classify_license_expression(licenses: ModuleType, raw: str, expected: str) -> None:
    assert licenses.classify(raw).status == expected


def test_dual_license_expression_is_permissive(licenses: ModuleType) -> None:
    # SPDX "OR" means the consumer may choose; selecting MIT is compliant.
    assert licenses.classify("AGPL-3.0 OR MIT").status == "allowed"


def test_trove_classifiers_are_used_when_free_text_is_ambiguous(licenses: ModuleType) -> None:
    # python-dateutil declares the unhelpful "Dual License" but ships
    # BSD/Apache trove classifiers; the classifier fallback resolves it.
    assert licenses.classify("BSD License OR Apache Software License").status == "allowed"


def test_review_allowlist_entries_are_parsed(licenses: ModuleType, tmp_path: Path) -> None:
    allowlist = tmp_path / "review-allowlist.txt"
    allowlist.write_text(
        "# comment\n\npython:psycopg  # LGPL-3.0, dynamic linking\n",
        encoding="utf-8",
    )

    entries = licenses.load_allowlist(allowlist)

    assert entries == {"python:psycopg": "LGPL-3.0, dynamic linking"}


def test_allowlist_does_not_rescue_denied_licenses(licenses: ModuleType) -> None:
    class _Package:
        ecosystem = "python"
        name = "copyleft"
        version = "1.0"
        license_raw = "AGPL-3.0"

    assert licenses.classify(_Package.license_raw).status == "denied"
