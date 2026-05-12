#!/usr/bin/env python3
"""Run V-model gap analysis using v-model-traceability framework.

Builds a Kuzu graph from traceability CSVs, then queries for:
- Design contracts with no test coverage (untested contracts)
- Design contracts with only partial coverage (no full verified_by edge)
- Requirements with no design contract (unimplemented requirements)

Requires v-model-traceability on PYTHONPATH or installed.

Usage:
    PYTHONPATH=/path/to/v-model-traceability python scripts/check_v_model_gaps.py
    python scripts/check_v_model_gaps.py --verbose
"""

from __future__ import annotations

import importlib
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACEABILITY_DIR = REPO_ROOT / "traceability"


def _find_vmodel_root() -> Path | None:
    """Find v-model-traceability root by locating its schemas directory."""
    # Check PYTHONPATH entries for v-model-traceability
    for path_str in sys.path:
        candidate = Path(path_str) / "schemas" / "nodes"
        if candidate.exists():
            return Path(path_str)
    return None


def main() -> int:
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    try:
        build_graph_mod = importlib.import_module("scripts.build_graph")
        query_gaps_mod = importlib.import_module("scripts.query_gaps")
    except ImportError:
        print("ERROR: v-model-traceability not on PYTHONPATH.")
        print("Usage: PYTHONPATH=/path/to/v-model-traceability python scripts/check_v_model_gaps.py")
        return 2

    build_graph = build_graph_mod.build_graph
    run_gap_analysis = query_gaps_mod.run_gap_analysis

    vmodel_root = _find_vmodel_root()
    if vmodel_root is None:
        print("ERROR: Cannot find v-model-traceability schemas directory on PYTHONPATH.")
        return 2

    schema_dir = vmodel_root / "schemas"

    # Build graph in temp directory
    tmp_dir = Path(tempfile.mkdtemp(prefix="tesseron-vmodel-"))
    db_path = tmp_dir / "traceability.kuzu"

    try:
        print("Building traceability graph...")
        report = build_graph(
            csv_dir=TRACEABILITY_DIR,
            schema_dir=schema_dir,
            output_path=db_path,
        )

        if not report.success:
            print("FAIL: Graph build failed.")
            for err in report.validation_errors:
                print(f"  {err}")
            return 1

        if verbose:
            for table, count in sorted(report.tables_created.items()):
                print(f"  {table}: {count} rows")

        print("Running gap analysis...")
        gaps = run_gap_analysis(db_path)

        if gaps.untested_contracts:
            print(f"\nUNTESTED DESIGN CONTRACTS ({len(gaps.untested_contracts)}):")
            for item in gaps.untested_contracts:
                print(f"  {item.id}: {item.title} ({item.module})")

        if gaps.unimplemented_requirements:
            print(f"\nUNIMPLEMENTED REQUIREMENTS ({len(gaps.unimplemented_requirements)}):")
            for item in gaps.unimplemented_requirements:
                print(f"  {item.id}: {item.title}")

        if gaps.partial_only_contracts:
            print(f"\nPARTIAL-ONLY COVERAGE ({len(gaps.partial_only_contracts)} — no full verified_by edge):")
            for item in gaps.partial_only_contracts:
                print(f"  {item.id}: {item.title} ({item.module})")

        if gaps.has_gaps:
            print(
                f"\nFAIL: {len(gaps.untested_contracts)} untested contracts, "
                f"{len(gaps.unimplemented_requirements)} unimplemented requirements."
            )
            return 1

        if gaps.has_warnings:
            print(
                f"\nWARN: {len(gaps.partial_only_contracts)} design contracts have only partial coverage."
            )
            # Warnings don't fail — but are visible in CI output

        print("PASS: V-model traceability chain complete.")
        return 0

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
