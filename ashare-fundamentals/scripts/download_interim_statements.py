#!/usr/bin/env python3
"""
Download Q1, Q2 (half-year), and Q3 statements for A-share companies.

This script reuses the request, retry, normalization, and atomic-write helpers
from the annual downloader.  Quarterly files are stored separately under
<output>/interim so the annual dataset is never overwritten.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq

import download_a_share_financial_statements as common


QUARTERS = {
    "Q1": "03-31",
    "Q2": "06-30",
    "Q3": "09-30",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Q1/Q2/Q3 A-share financial statements."
    )
    parser.add_argument("--universe-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--workers", type=int, default=20)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Skip network downloads and rebuild the quarterly index.",
    )
    return parser.parse_args()


def requested_dates(start_year: int, end_year: int) -> list[str]:
    return [
        f"{year}-{month_day}"
        for year in range(start_year, end_year + 1)
        for month_day in QUARTERS.values()
    ]


def period_from_date(report_date: str) -> str:
    year = report_date[:4]
    month_day = report_date[5:10]
    for quarter, expected in QUARTERS.items():
        if month_day == expected:
            return f"{year}{quarter}"
    return ""


def fetch_ajax_chunk(
    api_symbol: str,
    company_type: str,
    statement: str,
    dates: list[str],
    retries: int,
) -> list[dict[str, Any]]:
    config = common.STATEMENTS[statement]
    url = f"{common.FINANCE_ANALYSIS_ROOT}/{config['ajax_path']}"
    payload = common.request_json(
        url,
        {
            "companyType": company_type,
            "reportDateType": "0",
            "reportType": "1",
            "dates": ",".join(dates),
            "code": api_symbol,
        },
        retries,
    )
    return payload.get("data") or []


def fetch_ajax_statement(
    api_symbol: str,
    company_type: str,
    statement: str,
    date_chunks: list[list[str]],
    retries: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in date_chunks:
        rows.extend(
            fetch_ajax_chunk(
                api_symbol,
                company_type,
                statement,
                chunk,
                retries,
            )
        )
    return rows


def detect_special_company_type_and_balance(
    api_symbol: str,
    date_chunks: list[list[str]],
    retries: int,
) -> tuple[str | None, list[dict[str, Any]]]:
    # Eastmoney companyType: 1 securities, 2 insurance, 3 banking, 4 general.
    for company_type in ("1", "2", "3", "4"):
        collected: list[dict[str, Any]] = []
        found = False
        for chunk in reversed(date_chunks):
            rows = fetch_ajax_chunk(
                api_symbol,
                company_type,
                "balance_sheet",
                chunk,
                retries,
            )
            if rows:
                collected.extend(rows)
                found = True
                break
        if found:
            for chunk in date_chunks:
                collected.extend(
                    fetch_ajax_chunk(
                        api_symbol,
                        company_type,
                        "balance_sheet",
                        chunk,
                        retries,
                    )
                )
            return company_type, collected
    return None, []


def rows_to_dataframe(
    rows: list[dict[str, Any]],
    allowed_dates: set[str],
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "REPORT_DATE" not in frame:
        raise common.DownloadError("response does not contain REPORT_DATE")

    parsed_dates = pd.to_datetime(frame["REPORT_DATE"], errors="coerce")
    normalized_dates = parsed_dates.dt.strftime("%Y-%m-%d")
    keep = normalized_dates.isin(allowed_dates)
    frame = frame.loc[keep].copy()
    if frame.empty:
        return frame

    frame["REPORT_DATE"] = normalized_dates.loc[keep]
    for date_column in ("NOTICE_DATE", "UPDATE_DATE"):
        if date_column in frame:
            parsed = pd.to_datetime(frame[date_column], errors="coerce")
            frame[date_column] = parsed.dt.strftime("%Y-%m-%d")

    sort_columns = ["REPORT_DATE"]
    if "UPDATE_DATE" in frame:
        sort_columns.append("UPDATE_DATE")
    frame.sort_values(sort_columns, inplace=True)
    subset = [
        column
        for column in ("SECUCODE", "REPORT_DATE")
        if column in frame.columns
    ]
    frame.drop_duplicates(subset=subset, keep="last", inplace=True)
    frame.sort_values("REPORT_DATE", ascending=False, inplace=True)
    frame.reset_index(drop=True, inplace=True)

    for column in frame.select_dtypes(include=["object"]).columns:
        if column in common.STRING_COLUMNS:
            frame[column] = frame[column].astype("string")
            continue
        non_null = frame[column].dropna()
        if non_null.empty:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
            continue
        numeric = pd.to_numeric(non_null, errors="coerce")
        if numeric.notna().all():
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        else:
            frame[column] = frame[column].astype("string")
    return frame


def statement_paths(
    output_dir: Path,
    statement: str,
    secucode: str,
) -> tuple[Path, Path]:
    safe_code = secucode.replace(".", "_")
    folder = output_dir / "interim" / "raw" / statement
    return folder / f"{safe_code}.parquet", folder / f"{safe_code}.empty.json"


def frame_period_records(
    frame: pd.DataFrame,
    raw_path: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        report_date = str(getattr(row, "REPORT_DATE"))
        records.append(
            {
                "report_date": report_date,
                "period": period_from_date(report_date),
                "report_type": str(getattr(row, "REPORT_TYPE", "") or ""),
                "notice_date": str(getattr(row, "NOTICE_DATE", "") or ""),
                "update_date": str(getattr(row, "UPDATE_DATE", "") or ""),
                "raw_file": str(raw_path.relative_to(output_dir)),
            }
        )
    return records


def write_statement_result(
    output_dir: Path,
    secucode: str,
    statement: str,
    rows: list[dict[str, Any]],
    allowed_dates: set[str],
) -> tuple[int, list[dict[str, Any]]]:
    parquet_path, empty_path = statement_paths(
        output_dir, statement, secucode
    )
    frame = rows_to_dataframe(rows, allowed_dates)
    if frame.empty:
        common.atomic_write_json(
            {
                "secucode": secucode,
                "statement": statement,
                "periods": ["Q1", "Q2", "Q3"],
                "reason": "source_returned_no_interim_rows",
                "checked_at": datetime.now().astimezone().isoformat(),
            },
            empty_path,
        )
        if parquet_path.exists():
            parquet_path.unlink()
        return 0, []
    common.atomic_write_parquet(frame, parquet_path)
    if empty_path.exists():
        empty_path.unlink()
    return len(frame), frame_period_records(frame, parquet_path, output_dir)


def statement_is_complete(
    parquet_path: Path,
    empty_path: Path,
    force: bool,
) -> bool:
    if force:
        return False
    if empty_path.exists():
        return True
    if not parquet_path.exists() or parquet_path.stat().st_size == 0:
        return False
    try:
        dates = pd.read_parquet(parquet_path, columns=["REPORT_DATE"])
        return not dates.empty
    except Exception:
        return False


def download_company(
    record: dict[str, Any],
    output_dir: Path,
    start_year: int,
    end_year: int,
    retries: int,
    force: bool,
) -> dict[str, Any]:
    started = time.monotonic()
    secucode = str(record["secucode"]).upper()
    api_symbol = common.api_symbol_from_secucode(secucode)
    dates = requested_dates(start_year, end_year)
    allowed_dates = set(dates)
    date_chunks = [
        dates[index : index + 5] for index in range(0, len(dates), 5)
    ]

    pending: list[str] = []
    for statement in common.STATEMENTS:
        parquet_path, empty_path = statement_paths(
            output_dir, statement, secucode
        )
        if not statement_is_complete(parquet_path, empty_path, force):
            pending.append(statement)
    if not pending:
        return {
            "secucode": secucode,
            "name": record.get("name", ""),
            "universe_status": record.get("status", ""),
            "status": "skipped",
            "seconds": round(time.monotonic() - started, 3),
        }

    row_counts: dict[str, int] = {}
    period_records: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    company_type: str | None = None

    try:
        if "balance_sheet" in pending:
            balance_rows = common.fetch_direct(
                secucode, "balance_sheet", dates, retries
            )
            if not balance_rows:
                company_type, balance_rows = (
                    detect_special_company_type_and_balance(
                        api_symbol, date_chunks, retries
                    )
                )
            count, records = write_statement_result(
                output_dir,
                secucode,
                "balance_sheet",
                balance_rows,
                allowed_dates,
            )
            row_counts["balance_sheet"] = count
            period_records["balance_sheet"] = records
        else:
            balance_path, _ = statement_paths(
                output_dir, "balance_sheet", secucode
            )
            if balance_path.exists():
                column_count = len(pd.read_parquet(balance_path).columns)
                company_type = "4" if column_count >= 300 else None

        for statement in ("income_statement", "cash_flow_statement"):
            if statement not in pending:
                continue
            if company_type is None:
                rows = common.fetch_direct(
                    secucode, statement, dates, retries
                )
                if not rows:
                    detected_type, _ = (
                        detect_special_company_type_and_balance(
                            api_symbol, date_chunks, retries
                        )
                    )
                    company_type = detected_type
                    if company_type:
                        rows = fetch_ajax_statement(
                            api_symbol,
                            company_type,
                            statement,
                            date_chunks,
                            retries,
                        )
            elif company_type == "4":
                rows = common.fetch_direct(
                    secucode, statement, dates, retries
                )
            else:
                rows = fetch_ajax_statement(
                    api_symbol,
                    company_type,
                    statement,
                    date_chunks,
                    retries,
                )
            count, records = write_statement_result(
                output_dir,
                secucode,
                statement,
                rows,
                allowed_dates,
            )
            row_counts[statement] = count
            period_records[statement] = records
    except Exception as exc:
        errors["company"] = f"{type(exc).__name__}: {exc}"

    return {
        "secucode": secucode,
        "name": record.get("name", ""),
        "universe_status": record.get("status", ""),
        "status": "error" if errors else "completed",
        "company_type": company_type or "general_or_unknown",
        "row_counts": row_counts,
        "period_records": period_records,
        "errors": errors,
        "seconds": round(time.monotonic() - started, 3),
        "finished_at": datetime.now().astimezone().isoformat(),
    }


def load_universe(args: argparse.Namespace) -> pd.DataFrame:
    frame = pd.read_csv(
        args.universe_csv,
        dtype={"secucode": "string", "code": "string"},
    )
    required = {"secucode", "name", "status"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(
            f"universe is missing required columns: {sorted(missing)}"
        )
    frame["secucode"] = frame["secucode"].str.upper()
    frame.drop_duplicates("secucode", keep="last", inplace=True)
    frame.sort_values("secucode", inplace=True, ignore_index=True)
    if args.symbols:
        symbols = {symbol.upper() for symbol in args.symbols}
        frame = frame.loc[frame["secucode"].isin(symbols)].copy()
    if args.limit:
        frame = frame.head(args.limit).copy()
    if frame.empty:
        raise ValueError("the selected universe is empty")
    return frame


def run_download(
    universe: pd.DataFrame,
    args: argparse.Namespace,
) -> Counter:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = (
        args.output_dir / "logs" / "interim_download_progress.jsonl"
    )
    records = universe.to_dict(orient="records")
    counts: Counter = Counter()
    row_totals: Counter = Counter()
    started = time.monotonic()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        future_map = {
            executor.submit(
                download_company,
                record,
                args.output_dir,
                args.start_year,
                args.end_year,
                args.retries,
                args.force,
            ): record["secucode"]
            for record in records
        }
        for index, future in enumerate(
            concurrent.futures.as_completed(future_map), start=1
        ):
            secucode = future_map[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "secucode": secucode,
                    "status": "error",
                    "errors": {
                        "worker": f"{type(exc).__name__}: {exc}"
                    },
                    "finished_at": datetime.now().astimezone().isoformat(),
                }
            common.append_jsonl(progress_path, result)
            counts[result["status"]] += 1
            row_totals.update(result.get("row_counts") or {})

            if (
                index == 1
                or index % 25 == 0
                or index == len(records)
                or result["status"] == "error"
            ):
                elapsed = max(time.monotonic() - started, 0.001)
                rate = index / elapsed
                remaining = (len(records) - index) / max(rate, 0.001)
                logging.info(
                    "progress %d/%d | completed=%d skipped=%d errors=%d "
                    "| %.2f companies/s | ETA %.1f min | rows=%s",
                    index,
                    len(records),
                    counts["completed"],
                    counts["skipped"],
                    counts["error"],
                    rate,
                    remaining / 60,
                    dict(row_totals),
                )
    return counts


def read_period_records_from_file(
    path: Path,
    output_dir: Path,
) -> list[dict[str, Any]]:
    columns = [
        "REPORT_DATE",
        "REPORT_TYPE",
        "NOTICE_DATE",
        "UPDATE_DATE",
    ]
    available = set(pq.ParquetFile(path).schema_arrow.names)
    frame = pd.read_parquet(
        path, columns=[column for column in columns if column in available]
    )
    return frame_period_records(frame, path, output_dir)


def build_index_and_summary(
    universe: pd.DataFrame,
    output_dir: Path,
    start_year: int,
    end_year: int,
    *,
    use_progress_cache: bool = True,
    progress_filename: str = "interim_download_progress.jsonl",
) -> dict[str, Any]:
    progress_path = output_dir / "logs" / progress_filename
    cached: dict[tuple[str, str], list[dict[str, Any]]] = {}
    latest_status: dict[str, str] = {}
    if progress_path.exists():
        for line in progress_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            secucode = item["secucode"]
            latest_status[secucode] = item.get("status", "")
            if use_progress_cache:
                for statement, records in (
                    item.get("period_records") or {}
                ).items():
                    cached[(secucode, statement)] = records

    universe_lookup = universe.set_index("secucode").to_dict("index")
    index_rows: list[dict[str, Any]] = []
    statement_summary: dict[str, Any] = {}
    quality_rows: list[dict[str, Any]] = []

    for statement in common.STATEMENTS:
        raw_folder = output_dir / "interim" / "raw" / statement
        parquet_files = sorted(raw_folder.glob("*.parquet"))
        empty_files = sorted(raw_folder.glob("*.empty.json"))
        for path in parquet_files:
            code, exchange = path.stem.rsplit("_", 1)
            secucode = f"{code}.{exchange}"
            records = (
                cached.get((secucode, statement))
                if use_progress_cache
                else None
            )
            if records is None:
                records = read_period_records_from_file(path, output_dir)
            company = universe_lookup.get(secucode, {})
            for record in records:
                index_rows.append(
                    {
                        "secucode": secucode,
                        "name": company.get("name", ""),
                        "universe_status": company.get("status", "unknown"),
                        "statement": statement,
                        **record,
                    }
                )
        for path in empty_files:
            marker = json.loads(path.read_text(encoding="utf-8"))
            secucode = marker["secucode"]
            company = universe_lookup.get(secucode, {})
            quality_rows.append(
                {
                    "secucode": secucode,
                    "name": company.get("name", ""),
                    "report_date": "",
                    "period": "",
                    "issue": f"{statement}: no Q1/Q2/Q3 rows in source",
                }
            )
        statement_summary[statement] = {
            "parquet_files": len(parquet_files),
            "empty_markers": len(empty_files),
        }

    index = pd.DataFrame(index_rows)
    if not index.empty:
        index.sort_values(
            ["statement", "report_date", "secucode"],
            inplace=True,
            ignore_index=True,
        )
        index.drop_duplicates(
            ["secucode", "statement", "report_date"],
            keep="last",
            inplace=True,
            ignore_index=True,
        )

    metadata_dir = output_dir / "interim" / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    index.to_parquet(
        metadata_dir / "report_index.parquet",
        index=False,
        compression="zstd",
    )
    index.to_csv(
        metadata_dir / "report_index.csv",
        index=False,
        encoding="utf-8-sig",
    )

    counts = (
        index.groupby(["statement", "period"], as_index=False)
        .agg(rows=("secucode", "size"), companies=("secucode", "nunique"))
        .sort_values(["statement", "period"])
    )
    counts.to_csv(
        metadata_dir / "rows_by_period.csv",
        index=False,
        encoding="utf-8-sig",
    )

    presence = (
        index.assign(present=True)
        .pivot_table(
            index=["secucode", "name", "report_date", "period"],
            columns="statement",
            values="present",
            aggfunc="max",
            fill_value=False,
        )
        .reset_index()
    )
    for statement in common.STATEMENTS:
        if statement not in presence:
            presence[statement] = False
    mismatches = presence.loc[
        ~(
            presence["balance_sheet"]
            & presence["income_statement"]
            & presence["cash_flow_statement"]
        )
    ].copy()
    if not mismatches.empty:
        mismatches["issue"] = "statements_not_aligned_for_period"
        quality_rows.extend(mismatches.to_dict(orient="records"))
    quality = pd.DataFrame(quality_rows)
    quality.to_csv(
        metadata_dir / "quality_issues.csv",
        index=False,
        encoding="utf-8-sig",
    )

    allowed_dates = set(requested_dates(start_year, end_year))
    bad_dates = (
        int((~index["report_date"].isin(allowed_dates)).sum())
        if not index.empty
        else 0
    )
    duplicates = (
        int(
            index.duplicated(
                ["secucode", "statement", "report_date"]
            ).sum()
        )
        if not index.empty
        else 0
    )
    latest_errors = sum(status == "error" for status in latest_status.values())
    accounted = all(
        details["parquet_files"] + details["empty_markers"] == len(universe)
        for details in statement_summary.values()
    )
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "start_year": start_year,
        "end_year": end_year,
        "periods": ["Q1", "Q2", "Q3"],
        "universe_companies": int(len(universe)),
        "statements": statement_summary,
        "index_rows": int(len(index)),
        "rows_by_statement": {
            key: int(value)
            for key, value in index["statement"].value_counts().items()
        },
        "duplicate_keys": duplicates,
        "bad_dates": bad_dates,
        "documented_quality_issues": int(len(quality)),
        "latest_progress_records": len(latest_status),
        "latest_progress_errors": latest_errors,
        "all_companies_accounted_for_each_statement": accounted,
        "passed": accounted and latest_errors == 0 and duplicates == 0
        and bad_dates == 0,
    }
    common.atomic_write_json(
        summary, metadata_dir / "validation_summary.json"
    )
    return summary


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if args.start_year > args.end_year:
        raise ValueError("start year must not be after end year")
    universe = load_universe(args)
    logging.info(
        "selected %d companies for Q1/Q2/Q3 %d-%d",
        len(universe),
        args.start_year,
        args.end_year,
    )
    if not args.index_only:
        counts = run_download(universe, args)
        logging.info("download pass finished: %s", dict(counts))
    summary = build_index_and_summary(
        universe,
        args.output_dir,
        args.start_year,
        args.end_year,
    )
    logging.info(
        "interim validation summary: %s",
        json.dumps(summary, ensure_ascii=False),
    )
    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
