#!/usr/bin/env python3
"""Independently audit the downloaded A-share Q1/Q2/Q3 dataset."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq


STATEMENTS = (
    "balance_sheet",
    "income_statement",
    "cash_flow_statement",
)
QUARTER_ENDS = ("03-31", "06-30", "09-30")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit company-level A-share Q1/Q2/Q3 Parquet files."
    )
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--workers", type=int, default=16)
    return parser.parse_args()


def audit_file(task: tuple[str, Path, Path]) -> dict[str, Any]:
    statement, path, dataset_dir = task
    code, exchange = path.stem.rsplit("_", 1)
    secucode = f"{code}.{exchange}"
    parquet_file = pq.ParquetFile(path)
    schema_names = set(parquet_file.schema_arrow.names)
    required = {"SECUCODE", "REPORT_DATE"}
    missing_columns = sorted(required - schema_names)
    dates: list[str] = []
    content_codes: set[str] = set()
    if not missing_columns:
        table = parquet_file.read(columns=["SECUCODE", "REPORT_DATE"])
        content_codes = {
            str(value).upper()
            for value in table.column("SECUCODE").to_pylist()
            if value is not None
        }
        dates = [
            str(value)[:10]
            for value in table.column("REPORT_DATE").to_pylist()
            if value is not None
        ]
    return {
        "statement": statement,
        "secucode": secucode,
        "raw_file": str(path.relative_to(dataset_dir)),
        "size_bytes": path.stat().st_size,
        "row_count": parquet_file.metadata.num_rows,
        "column_count": len(schema_names),
        "min_report_date": min(dates) if dates else "",
        "max_report_date": max(dates) if dates else "",
        "missing_columns": ",".join(missing_columns),
        "content_code_mismatch": bool(
            content_codes and content_codes != {secucode}
        ),
        "duplicate_dates": len(dates) - len(set(dates)),
        "dates": dates,
    }


def main() -> int:
    args = parse_args()
    dataset_dir = args.dataset_dir.resolve()
    interim_dir = dataset_dir / "interim"
    metadata_dir = interim_dir / "metadata"
    universe = pd.read_csv(
        dataset_dir / "metadata" / "companies.csv",
        dtype={"secucode": "string"},
    )
    universe_codes = set(universe["secucode"].str.upper())
    expected_dates = {
        f"{year}-{month_day}"
        for year in range(args.start_year, args.end_year + 1)
        for month_day in QUARTER_ENDS
    }

    tasks: list[tuple[str, Path, Path]] = []
    empty_markers: dict[str, list[Path]] = {}
    for statement in STATEMENTS:
        raw_dir = interim_dir / "raw" / statement
        tasks.extend(
            (statement, path, dataset_dir)
            for path in sorted(raw_dir.glob("*.parquet"))
        )
        empty_markers[statement] = sorted(raw_dir.glob("*.empty.json"))

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        audited = list(executor.map(audit_file, tasks))

    manifest_columns = [
        "statement",
        "secucode",
        "raw_file",
        "size_bytes",
        "row_count",
        "column_count",
        "min_report_date",
        "max_report_date",
    ]
    manifest = pd.DataFrame(audited)
    manifest[manifest_columns].to_csv(
        metadata_dir / "raw_file_manifest.csv",
        index=False,
        encoding="utf-8-sig",
    )

    raw_rows_by_statement = {
        statement: int(
            sum(
                item["row_count"]
                for item in audited
                if item["statement"] == statement
            )
        )
        for statement in STATEMENTS
    }
    file_codes_by_statement = {
        statement: {
            item["secucode"]
            for item in audited
            if item["statement"] == statement
        }
        for statement in STATEMENTS
    }
    invalid_date_rows = sum(
        1
        for item in audited
        for date in item["dates"]
        if date not in expected_dates
    )

    index = pd.read_parquet(metadata_dir / "report_index.parquet")
    index["report_date"] = index["report_date"].astype(str).str[:10]
    index_rows_by_statement = {
        key: int(value)
        for key, value in index["statement"].value_counts().to_dict().items()
    }
    index_duplicate_keys = int(
        index.duplicated(
            ["secucode", "statement", "report_date"]
        ).sum()
    )
    index_invalid_dates = int(
        (~index["report_date"].isin(expected_dates)).sum()
    )
    missing_raw_references = int(
        sum(
            not (dataset_dir / raw_file).is_file()
            for raw_file in index["raw_file"].drop_duplicates()
        )
    )

    latest_progress: dict[str, dict[str, Any]] = {}
    progress_path = (
        dataset_dir / "logs" / "interim_download_progress.jsonl"
    )
    for line in progress_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            latest_progress[record["secucode"]] = record
    latest_errors = sum(
        record.get("status") == "error"
        for record in latest_progress.values()
    )

    failures = {
        "unreadable_files": 0,
        "zero_row_parquet_files": sum(
            item["row_count"] == 0 for item in audited
        ),
        "files_missing_required_columns": sum(
            bool(item["missing_columns"]) for item in audited
        ),
        "files_with_code_mismatch": sum(
            item["content_code_mismatch"] for item in audited
        ),
        "duplicate_dates_within_files": int(
            sum(item["duplicate_dates"] for item in audited)
        ),
        "invalid_date_rows_in_raw_files": invalid_date_rows,
        "index_duplicate_keys": index_duplicate_keys,
        "index_invalid_dates": index_invalid_dates,
        "index_missing_raw_references": missing_raw_references,
        "latest_progress_errors": latest_errors,
    }
    companies_accounted_for = {
        statement: (
            file_codes_by_statement[statement]
            | {
                json.loads(path.read_text(encoding="utf-8"))[
                    "secucode"
                ]
                for path in empty_markers[statement]
            }
        )
        == universe_codes
        for statement in STATEMENTS
    }
    row_totals_match_index = {
        statement: raw_rows_by_statement[statement]
        == index_rows_by_statement.get(statement, 0)
        for statement in STATEMENTS
    }
    passed = (
        not any(failures.values())
        and all(companies_accounted_for.values())
        and all(row_totals_match_index.values())
        and set(latest_progress) == universe_codes
    )

    summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "scope": {
            "start_year": args.start_year,
            "end_year": args.end_year,
            "periods": ["Q1", "Q2", "Q3"],
            "universe_companies": len(universe_codes),
        },
        "files": {
            "parquet_files": len(audited),
            "empty_markers": sum(
                len(paths) for paths in empty_markers.values()
            ),
            "total_size_bytes": int(
                sum(item["size_bytes"] for item in audited)
            ),
        },
        "raw_rows_by_statement": raw_rows_by_statement,
        "index_rows": int(len(index)),
        "index_rows_by_statement": index_rows_by_statement,
        "companies_accounted_for_each_statement": (
            companies_accounted_for
        ),
        "row_totals_match_index": row_totals_match_index,
        "latest_progress_records": len(latest_progress),
        "failures": failures,
        "passed": passed,
    }
    output_path = metadata_dir / "final_audit.json"
    output_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
