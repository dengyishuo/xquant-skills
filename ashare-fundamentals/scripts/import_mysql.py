#!/usr/bin/env python3
"""Optionally upsert generated Parquet datasets into an existing MySQL database."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Iterable

import pyarrow.parquet as pq


STATEMENT_TYPES = ("balance_sheet", "income_statement", "cash_flow_statement")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--statement-root", type=Path)
    parser.add_argument("--indicator-root", type=Path)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def clean(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items() if clean(item) is not None}
    return value


def text(row: dict, key: str) -> str | None:
    value = clean(row.get(key))
    return None if value in (None, "") else str(value)


def frequency(row: dict) -> str:
    label = text(row, "REPORT_TYPE") or ""
    if "一季" in label:
        return "q1"
    if "半年" in label or "中报" in label:
        return "q2"
    if "三季" in label:
        return "q3"
    if "年报" in label:
        return "annual"
    return {"03-31": "q1", "06-30": "q2", "09-30": "q3", "12-31": "annual"}.get(
        (text(row, "REPORT_DATE") or "")[-5:], "other"
    )


def batches(items: Iterable[tuple], size: int):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def statement_files(root: Path):
    for statement_type in STATEMENT_TYPES:
        seen = set()
        patterns = (f"annual/{statement_type}/*.parquet", f"interim/raw/{statement_type}/*.parquet")
        for pattern in patterns:
            for path in sorted(root.glob(pattern)):
                if path.resolve() not in seen:
                    seen.add(path.resolve())
                    yield statement_type, path


def indicator_files(root: Path):
    yield from sorted((root / "annual").glob("*.parquet"))


def rows_from(path: Path):
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(batch_size=1024):
        yield from batch.to_pylist()


def main() -> int:
    args = parse_args()
    discovered_statements = list(statement_files(args.statement_root)) if args.statement_root else []
    discovered_indicators = list(indicator_files(args.indicator_root)) if args.indicator_root else []
    print(json.dumps({
        "statement_files": len(discovered_statements),
        "indicator_files": len(discovered_indicators),
        "dry_run": args.dry_run,
    }))
    if args.dry_run:
        return 0
    if not discovered_statements and not discovered_indicators:
        raise SystemExit("no importable Parquet files found")
    try:
        import pymysql
    except ImportError as exc:
        raise SystemExit("PyMySQL is required: python -m pip install -e '.[mysql]'") from exc

    required = ("MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD")
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit(f"missing environment variables: {', '.join(missing)}")
    connection = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.environ["MYSQL_DATABASE"],
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        charset="utf8mb4",
        autocommit=False,
    )
    statement_sql = """INSERT INTO a_share_financial_statement
      (secucode,report_date,statement_type,frequency,notice_date,update_date,report_type,security_name,org_type,source_path,payload)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
      ON DUPLICATE KEY UPDATE frequency=VALUES(frequency),notice_date=VALUES(notice_date),
      update_date=VALUES(update_date),report_type=VALUES(report_type),security_name=VALUES(security_name),
      org_type=VALUES(org_type),source_path=VALUES(source_path),payload=VALUES(payload)"""
    indicator_sql = """INSERT INTO a_share_main_financial_indicator
      (secucode,report_date,notice_date,update_date,report_type,security_name,org_type,source_path,payload)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
      ON DUPLICATE KEY UPDATE notice_date=VALUES(notice_date),update_date=VALUES(update_date),
      report_type=VALUES(report_type),security_name=VALUES(security_name),org_type=VALUES(org_type),
      source_path=VALUES(source_path),payload=VALUES(payload)"""
    counts = {"statements": 0, "indicators": 0}
    try:
        with connection.cursor() as cursor:
            for statement_type, path in discovered_statements:
                prepared = (
                    (
                        text(row, "SECUCODE"), text(row, "REPORT_DATE"), statement_type,
                        frequency(row), text(row, "NOTICE_DATE"), text(row, "UPDATE_DATE"),
                        text(row, "REPORT_TYPE"), text(row, "SECURITY_NAME_ABBR"),
                        text(row, "ORG_TYPE"), str(path),
                        json.dumps(clean(row), ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                    ) for row in rows_from(path)
                )
                for batch in batches(prepared, args.batch_size):
                    cursor.executemany(statement_sql, batch)
                    connection.commit()
                    counts["statements"] += len(batch)
            for path in discovered_indicators:
                prepared = (
                    (
                        text(row, "SECUCODE"), text(row, "REPORT_DATE"), text(row, "NOTICE_DATE"),
                        text(row, "UPDATE_DATE"), text(row, "REPORT_TYPE"),
                        text(row, "SECURITY_NAME_ABBR"), text(row, "ORG_TYPE"), str(path),
                        json.dumps(clean(row), ensure_ascii=False, allow_nan=False, separators=(",", ":")),
                    ) for row in rows_from(path)
                )
                for batch in batches(prepared, args.batch_size):
                    cursor.executemany(indicator_sql, batch)
                    connection.commit()
                    counts["indicators"] += len(batch)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

