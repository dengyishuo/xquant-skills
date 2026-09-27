#!/usr/bin/env python3
"""Convert Parquet batches into MySQL-friendly TSV without handling credentials."""

import argparse
import csv
import datetime as dt
import decimal
import json
import math
from pathlib import Path

import pyarrow.parquet as pq


COMMON = {
    "secucode": "SECUCODE",
    "report_date": "REPORT_DATE",
    "notice_date": "NOTICE_DATE",
    "update_date": "UPDATE_DATE",
    "report_type": "REPORT_TYPE",
    "security_name": "SECURITY_NAME_ABBR",
    "org_type": "ORG_TYPE",
}


def clean(value):
    if value is None:
        return None
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item = clean(item)
            if item is not None:
                cleaned[str(key)] = item
        return cleaned
    return value


def compact_payload(row):
    payload = {}
    for key, value in row.items():
        value = clean(value)
        if value is not None:
            payload[key] = value
    return json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def text_value(row, key):
    value = clean(row.get(key))
    return "" if value is None else str(value)


def frequency(report_type, report_date):
    label = str(report_type or "")
    if "一季" in label:
        return "q1"
    if "半年" in label or "中报" in label:
        return "q2"
    if "三季" in label:
        return "q3"
    if "年报" in label:
        return "annual"
    return {"03-31": "q1", "06-30": "q2", "09-30": "q3", "12-31": "annual"}.get(str(report_date or "")[-5:], "other")


def relative_source(path, data_root):
    try:
        return str(path.resolve().relative_to(data_root.resolve()))
    except ValueError:
        return str(path.resolve())


def statement_row(row, statement_type, source):
    values = {name: text_value(row, source_name) for name, source_name in COMMON.items()}
    return {
        "secucode": values["secucode"], "report_date": values["report_date"],
        "statement_type": statement_type,
        "frequency": frequency(values["report_type"], values["report_date"]),
        "notice_date": values["notice_date"], "update_date": values["update_date"],
        "report_type": values["report_type"], "security_name": values["security_name"],
        "org_type": values["org_type"], "source_path": source, "payload": compact_payload(row),
    }


def indicator_row(row, source):
    values = {name: text_value(row, source_name) for name, source_name in COMMON.items()}
    return {
        "secucode": values["secucode"], "report_date": values["report_date"],
        "notice_date": values["notice_date"], "update_date": values["update_date"],
        "report_type": values["report_type"], "security_name": values["security_name"],
        "org_type": values["org_type"], "source_path": source, "payload": compact_payload(row),
    }


def company_row(row, source):
    return {
        "secucode": text_value(row, "secucode"), "security_code": text_value(row, "code"),
        "exchange": text_value(row, "exchange"), "name": text_value(row, "name"),
        "status": text_value(row, "status"), "listing_date": text_value(row, "listing_date"),
        "delisting_date": text_value(row, "delisting_date"), "captured_at": text_value(row, "captured_at"),
        "source_path": source, "payload": compact_payload(row),
    }


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("companies", "statements", "indicators"), required=True)
    parser.add_argument("--file-list", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--statement-type", choices=("balance_sheet", "income_statement", "cash_flow_statement"))
    parser.add_argument("--batch-size", type=int, default=1024)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.mode == "statements" and not args.statement_type:
        raise SystemExit("--statement-type is required in statements mode")
    files = [Path(line.strip()) for line in Path(args.file_list).read_text().splitlines() if line.strip()]
    if not files:
        raise SystemExit("file list is empty")
    data_root = Path(args.data_root)
    if args.mode == "companies":
        fields = ["secucode", "security_code", "exchange", "name", "status", "listing_date", "delisting_date", "captured_at", "source_path", "payload"]
    elif args.mode == "statements":
        fields = ["secucode", "report_date", "statement_type", "frequency", "notice_date", "update_date", "report_type", "security_name", "org_type", "source_path", "payload"]
    else:
        fields = ["secucode", "report_date", "notice_date", "update_date", "report_type", "security_name", "org_type", "source_path", "payload"]

    rows_written = 0
    with Path(args.output).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", quoting=csv.QUOTE_NONE, quotechar=None)
        writer.writeheader()
        for parquet_path in files:
            if not parquet_path.is_file():
                raise FileNotFoundError(parquet_path)
            source = relative_source(parquet_path, data_root)
            parquet = pq.ParquetFile(parquet_path)
            for batch in parquet.iter_batches(batch_size=args.batch_size):
                for row in batch.to_pylist():
                    if args.mode == "companies":
                        output = company_row(row, source)
                    elif args.mode == "statements":
                        output = statement_row(row, args.statement_type, source)
                    else:
                        output = indicator_row(row, source)
                    if not output["secucode"]:
                        raise ValueError(f"missing secucode in {parquet_path}")
                    writer.writerow(output)
                    rows_written += 1
    print(json.dumps({"mode": args.mode, "files": len(files), "rows": rows_written, "output": str(Path(args.output))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
