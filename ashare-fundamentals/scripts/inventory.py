#!/usr/bin/env python3
"""Inventory local Parquet files and validation summaries without mutation."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def classify(path: Path) -> str:
    text = str(path).lower()
    for name in ("balance_sheet", "income_statement", "cash_flow_statement"):
        if name in text:
            return name
    if "indicator" in text:
        return "main_financial_indicator"
    if path.name in {"companies.parquet", "company.parquet"}:
        return "company"
    return "other"


def main() -> int:
    args = parse_args()
    root = args.data_root.resolve()
    if not root.is_dir():
        raise SystemExit(f"data root does not exist: {root}")
    files = sorted(root.rglob("*.parquet"))
    groups: dict[str, dict[str, object]] = {}
    years: Counter[str] = Counter()
    errors = []
    for path in files:
        kind = classify(path)
        entry = groups.setdefault(kind, {"files": 0, "rows": 0, "bytes": 0})
        entry["files"] = int(entry["files"]) + 1
        entry["bytes"] = int(entry["bytes"]) + path.stat().st_size
        try:
            metadata = pq.ParquetFile(path).metadata
            entry["rows"] = int(entry["rows"]) + metadata.num_rows
            schema_names = set(metadata.schema.names)
            if "REPORT_DATE" in schema_names:
                table = pq.read_table(path, columns=["REPORT_DATE"])
                for value in table.column(0).to_pylist():
                    if value:
                        years[str(value)[:4]] += 1
        except Exception as exc:
            errors.append({"file": str(path.relative_to(root)), "error": str(exc)})
    summaries = []
    for path in sorted(root.rglob("*summary.json")):
        try:
            summaries.append({"file": str(path.relative_to(root)), "content": json.loads(path.read_text())})
        except Exception as exc:
            errors.append({"file": str(path.relative_to(root)), "error": str(exc)})
    result = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "data_root": str(root),
        "parquet_files": len(files),
        "groups": groups,
        "report_year_row_occurrences": dict(sorted(years.items())),
        "validation_summaries": summaries,
        "errors": errors,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

