#!/usr/bin/env python3
"""Deterministic traceability checker for python-tesseron.

Verifies that every test specification ID has a corresponding test function,
and every test function references valid requirement IDs.

Usage:
    python scripts/check_traceability.py
    python scripts/check_traceability.py --verbose
"""

import csv
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACEABILITY_DIR = REPO_ROOT / "traceability"
TESTS_DIR = REPO_ROOT / "tests"


def extract_spec_test_ids() -> dict[str, set[str]]:
    """Extract expected test IDs from test specification .md files."""
    spec_ids: dict[str, set[str]] = {}

    patterns = {
        "state_transition_tests.md": re.compile(r"\bST-(\d+)\b"),
        "error_model_tests.md": re.compile(r"\bER-(\d+)\b"),
        "wire_format_tests.md": re.compile(r"\bWF-(\d+)\b"),
        "capability_tests.md": re.compile(r"\bCP-(\d+)\b"),
        "gap_analysis.md": re.compile(r"\b(SEC-\d+|API-\d+|WF-\d+|ST-\d+|CP-\d+)\b"),
    }

    for filename, pattern in patterns.items():
        filepath = TRACEABILITY_DIR / filename
        if not filepath.exists():
            print(f"  WARNING: {filename} not found")
            continue

        text = filepath.read_text()
        for match in pattern.finditer(text):
            test_id = match.group(0) if "-" in match.group(0) else f"{filename.split('_')[0].upper()}-{match.group(1).zfill(2)}"
            # Normalize: ST-1 -> ST-01
            prefix, num = test_id.rsplit("-", 1)
            test_id = f"{prefix}-{num.zfill(2)}"
            spec_ids.setdefault(filename, set()).add(test_id)

    # Flatten all spec IDs
    all_spec_ids = set()
    for ids in spec_ids.values():
        all_spec_ids.update(ids)

    # Add acceptance test IDs (AT-01 through AT-20)
    for i in range(1, 21):
        all_spec_ids.add(f"AT-{i:02d}")

    return {"by_file": spec_ids, "all": all_spec_ids}


def extract_implemented_test_ids() -> dict[str, list[str]]:
    """Extract test IDs from pytest test function docstrings."""
    implemented: dict[str, list[str]] = {}

    test_id_pattern = re.compile(
        r"\b(ST|ER|WF|CP|SEC|AT|API)-(\d+)\b"
    )

    for test_file in sorted(TESTS_DIR.glob("test_*.py")):
        text = test_file.read_text()
        # Find all test functions and their docstrings
        func_pattern = re.compile(
            r'(?:async\s+)?def\s+(test_\w+)\s*\([^)]*\)[^:]*:\s*\n\s*"""(.*?)"""',
            re.DOTALL,
        )
        for func_match in func_pattern.finditer(text):
            func_name = func_match.group(1)
            docstring = func_match.group(2)

            for id_match in test_id_pattern.finditer(docstring):
                test_id = f"{id_match.group(1)}-{id_match.group(2).zfill(2)}"
                implemented.setdefault(test_id, []).append(
                    f"{test_file.name}::{func_name}"
                )

    return implemented


def extract_requirement_ids() -> set[str]:
    """Extract all valid requirement IDs from requirements.csv."""
    req_ids = set()
    csv_path = TRACEABILITY_DIR / "requirements.csv"
    if not csv_path.exists():
        print("  WARNING: requirements.csv not found")
        return req_ids

    with open(csv_path) as f:
        for row in csv.DictReader(f):
            req_ids.add(row["id"])

    return req_ids


def extract_req_refs_from_tests() -> dict[str, list[str]]:
    """Extract requirement ID references from test docstrings."""
    req_refs: dict[str, list[str]] = {}
    req_pattern = re.compile(r"\bREQ-(\d+)\b")

    for test_file in sorted(TESTS_DIR.glob("test_*.py")):
        text = test_file.read_text()
        func_pattern = re.compile(
            r'(?:async\s+)?def\s+(test_\w+)\s*\([^)]*\)[^:]*:\s*\n\s*"""(.*?)"""',
            re.DOTALL,
        )
        for func_match in func_pattern.finditer(text):
            func_name = func_match.group(1)
            docstring = func_match.group(2)

            for req_match in req_pattern.finditer(docstring):
                req_id = f"REQ-{req_match.group(1).zfill(3)}"
                req_refs.setdefault(req_id, []).append(
                    f"{test_file.name}::{func_name}"
                )

    return req_refs


def main() -> int:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    errors = 0

    print("=== Traceability Check ===\n")

    # 1. Spec test IDs vs implemented test IDs
    spec_data = extract_spec_test_ids()
    spec_ids = spec_data["all"]
    implemented = extract_implemented_test_ids()
    impl_ids = set(implemented.keys())

    missing = sorted(spec_ids - impl_ids)
    extra = sorted(impl_ids - spec_ids)

    print(f"Spec test IDs: {len(spec_ids)}")
    print(f"Implemented test IDs: {len(impl_ids)}")
    print(f"Coverage: {len(spec_ids & impl_ids)}/{len(spec_ids)} ({100 * len(spec_ids & impl_ids) / len(spec_ids):.0f}%)")
    print()

    if missing:
        print(f"MISSING ({len(missing)} spec tests not implemented):")
        for tid in missing:
            print(f"  {tid}")
        errors += len(missing)
        print()

    if extra and verbose:
        print(f"EXTRA ({len(extra)} implemented tests not in spec):")
        for tid in extra:
            print(f"  {tid}: {', '.join(implemented[tid])}")
        print()

    # 2. Requirement ID references
    valid_reqs = extract_requirement_ids()
    req_refs = extract_req_refs_from_tests()
    referenced_reqs = set(req_refs.keys())

    invalid_refs = sorted(referenced_reqs - valid_reqs)
    unreferenced = sorted(valid_reqs - referenced_reqs)

    print(f"Valid requirements: {len(valid_reqs)}")
    print(f"Requirements referenced in tests: {len(referenced_reqs)}")
    print(f"Requirement coverage: {len(valid_reqs & referenced_reqs)}/{len(valid_reqs)} ({100 * len(valid_reqs & referenced_reqs) / len(valid_reqs):.0f}%)")
    print()

    if invalid_refs:
        print(f"INVALID requirement references ({len(invalid_refs)}):")
        for rid in invalid_refs:
            print(f"  {rid}: referenced by {', '.join(req_refs[rid])}")
        errors += len(invalid_refs)
        print()

    if unreferenced and verbose:
        print(f"UNREFERENCED requirements ({len(unreferenced)} — no test mentions them):")
        for rid in unreferenced:
            print(f"  {rid}")
        print()

    # 3. Summary
    print("=== Summary ===")
    if errors == 0:
        print("PASS: All spec test IDs implemented, all requirement references valid.")
    else:
        print(f"FAIL: {errors} issue(s) found.")

    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
