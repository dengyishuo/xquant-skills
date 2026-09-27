#!/usr/bin/env python3
"""
Download complete annual financial statements for A-share companies.

The downloader uses Eastmoney's structured F10 endpoints and keeps each
company/report type in a separate Parquet file.  Downloads are atomic,
retryable, and resumable.  Financial companies use their industry-specific
schemas instead of being forced into the general-company schema.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import os
import random
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests


DATA_CENTER_URL = "https://datacenter.eastmoney.com/securities/api/data/get"
FINANCE_ANALYSIS_ROOT = (
    "https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis"
)

STATEMENTS = {
    "balance_sheet": {
        "direct_type": "RPT_F10_FINANCE_GBALANCE",
        "direct_style": "F10_FINANCE_GBALANCE",
        "ajax_path": "zcfzbAjaxNew",
    },
    "income_statement": {
        "direct_type": "RPT_F10_FINANCE_GINCOME",
        "direct_style": "APP_F10_GINCOME",
        "ajax_path": "lrbAjaxNew",
    },
    "cash_flow_statement": {
        "direct_type": "RPT_F10_FINANCE_GCASHFLOW",
        "direct_style": "APP_F10_GCASHFLOW",
        "ajax_path": "xjllbAjaxNew",
    },
}

STRING_COLUMNS = {
    "SECUCODE",
    "SECURITY_CODE",
    "SECURITY_NAME_ABBR",
    "ORG_CODE",
    "ORG_TYPE",
    "REPORT_DATE",
    "REPORT_TYPE",
    "REPORT_DATE_NAME",
    "SECURITY_TYPE_CODE",
    "NOTICE_DATE",
    "UPDATE_DATE",
    "CURRENCY",
    "OPINION_TYPE",
    "OSOPINION_TYPE",
    "LISTING_STATE",
}

_thread_local = threading.local()


class DownloadError(RuntimeError):
    """Raised when a request cannot be completed after retries."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download 10 years of complete annual A-share statements."
    )
    parser.add_argument(
        "--universe-csv",
        type=Path,
        required=True,
        help="CSV containing at least secucode, name, and status columns.",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Download only the first N companies; intended for testing.",
    )
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=[],
        help="Optional exact SECUCODE values, e.g. 600519.SH 601398.SH.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace existing statement files and empty markers.",
    )
    parser.add_argument(
        "--consolidate-only",
        action="store_true",
        help="Skip downloads and rebuild annual consolidated files.",
    )
    return parser.parse_args()


def get_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json, text/plain, */*",
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"
                ),
            }
        )
        _thread_local.session = session
    return session


def request_json(
    url: str,
    params: dict[str, str],
    retries: int,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = get_session().get(url, params=params, timeout=(10, 45))
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                delay = min(12.0, 0.8 * (2**attempt)) + random.random() * 0.5
                time.sleep(delay)
    raise DownloadError(f"request failed after {retries} attempts: {last_error}")


def requested_dates(start_year: int, end_year: int) -> list[str]:
    return [f"{year}-12-31" for year in range(start_year, end_year + 1)]


def fetch_direct(
    secucode: str,
    statement: str,
    dates: list[str],
    retries: int,
) -> list[dict[str, Any]]:
    config = STATEMENTS[statement]
    quoted_dates = ",".join(f"'{item}'" for item in dates)
    params = {
        "type": config["direct_type"],
        "sty": config["direct_style"],
        "filter": (
            f'(SECUCODE="{secucode}")'
            f"(REPORT_DATE in ({quoted_dates}))"
        ),
        "p": "1",
        "ps": "200",
        "sr": "-1",
        "st": "REPORT_DATE",
        "source": "HSF10",
        "client": "PC",
    }
    payload = request_json(DATA_CENTER_URL, params, retries)
    result = payload.get("result") or {}
    data = result.get("data") or []
    if data:
        return data
    if payload.get("success") is False and payload.get("message") not in {
        "返回数据为空",
        "ok",
        None,
    }:
        raise DownloadError(
            f"{secucode} {statement}: {payload.get('message', 'unknown error')}"
        )
    return []


def fetch_ajax_chunk(
    api_symbol: str,
    company_type: str,
    statement: str,
    dates: list[str],
    retries: int,
) -> list[dict[str, Any]]:
    config = STATEMENTS[statement]
    url = f"{FINANCE_ANALYSIS_ROOT}/{config['ajax_path']}"
    params = {
        "companyType": company_type,
        "reportDateType": "1",
        "reportType": "1",
        "dates": ",".join(dates),
        "code": api_symbol,
    }
    payload = request_json(url, params, retries)
    return payload.get("data") or []


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
                found = True
                collected.extend(rows)
                break
        if found:
            # The detection request fetched one chunk. Fetch all remaining dates;
            # duplicates are removed later, which keeps this branch simple.
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


def rows_to_dataframe(
    rows: list[dict[str, Any]],
    start_year: int,
    end_year: int,
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "REPORT_DATE" not in frame:
        raise DownloadError("response does not contain REPORT_DATE")

    parsed_dates = pd.to_datetime(frame["REPORT_DATE"], errors="coerce")
    keep = (
        parsed_dates.dt.year.between(start_year, end_year)
        & (parsed_dates.dt.month == 12)
        & (parsed_dates.dt.day == 31)
    )
    frame = frame.loc[keep].copy()
    if frame.empty:
        return frame

    frame["REPORT_DATE"] = parsed_dates.loc[keep].dt.strftime("%Y-%m-%d")
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

    # Normalize mixed object columns so PyArrow can write every industry schema.
    for column in frame.select_dtypes(include=["object"]).columns:
        if column in STRING_COLUMNS:
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


def atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.part"
    )
    try:
        frame.to_parquet(
            temporary,
            index=False,
            engine="pyarrow",
            compression="zstd",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.part"
    )
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def statement_paths(
    output_dir: Path,
    statement: str,
    secucode: str,
) -> tuple[Path, Path]:
    safe_code = secucode.replace(".", "_")
    folder = output_dir / "raw" / statement
    return folder / f"{safe_code}.parquet", folder / f"{safe_code}.empty.json"


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
        columns = pd.read_parquet(parquet_path, columns=["REPORT_DATE"])
        return "REPORT_DATE" in columns and not columns.empty
    except Exception:
        return False


def write_statement_result(
    output_dir: Path,
    secucode: str,
    statement: str,
    rows: list[dict[str, Any]],
    start_year: int,
    end_year: int,
) -> int:
    parquet_path, empty_path = statement_paths(output_dir, statement, secucode)
    frame = rows_to_dataframe(rows, start_year, end_year)
    if frame.empty:
        atomic_write_json(
            {
                "secucode": secucode,
                "statement": statement,
                "start_year": start_year,
                "end_year": end_year,
                "reason": "source_returned_no_annual_rows",
                "checked_at": datetime.now().astimezone().isoformat(),
            },
            empty_path,
        )
        if parquet_path.exists():
            parquet_path.unlink()
        return 0
    atomic_write_parquet(frame, parquet_path)
    if empty_path.exists():
        empty_path.unlink()
    return len(frame)


def api_symbol_from_secucode(secucode: str) -> str:
    code, exchange = secucode.split(".")
    return f"{exchange}{code}"


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
    api_symbol = api_symbol_from_secucode(secucode)
    dates = requested_dates(start_year, end_year)
    date_chunks = [dates[index : index + 5] for index in range(0, len(dates), 5)]

    pending: list[str] = []
    for statement in STATEMENTS:
        parquet_path, empty_path = statement_paths(
            output_dir, statement, secucode
        )
        if not statement_is_complete(parquet_path, empty_path, force):
            pending.append(statement)
    if not pending:
        return {
            "secucode": secucode,
            "name": record.get("name", ""),
            "status": "skipped",
            "row_counts": {},
            "seconds": round(time.monotonic() - started, 3),
        }

    row_counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    company_type: str | None = None
    balance_rows: list[dict[str, Any]] | None = None

    try:
        if "balance_sheet" in pending:
            balance_rows = fetch_direct(
                secucode, "balance_sheet", dates, retries
            )
            if not balance_rows:
                company_type, balance_rows = (
                    detect_special_company_type_and_balance(
                        api_symbol, date_chunks, retries
                    )
                )
            row_counts["balance_sheet"] = write_statement_result(
                output_dir,
                secucode,
                "balance_sheet",
                balance_rows,
                start_year,
                end_year,
            )
        else:
            # Determine the schema family from an existing balance file.
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
                rows = fetch_direct(secucode, statement, dates, retries)
                if not rows:
                    detected_type, _ = detect_special_company_type_and_balance(
                        api_symbol, date_chunks, retries
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
                rows = fetch_direct(secucode, statement, dates, retries)
            else:
                rows = fetch_ajax_statement(
                    api_symbol,
                    company_type,
                    statement,
                    date_chunks,
                    retries,
                )
            row_counts[statement] = write_statement_result(
                output_dir,
                secucode,
                statement,
                rows,
                start_year,
                end_year,
            )
    except Exception as exc:
        errors["company"] = f"{type(exc).__name__}: {exc}"

    return {
        "secucode": secucode,
        "name": record.get("name", ""),
        "universe_status": record.get("status", ""),
        "status": "error" if errors else "completed",
        "company_type": company_type or "unknown",
        "row_counts": row_counts,
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


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_download(
    universe: pd.DataFrame,
    args: argparse.Namespace,
) -> Counter:
    args.output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = args.output_dir / "logs" / "download_progress.jsonl"
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
            append_jsonl(progress_path, result)
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


def iter_parquet_files(folder: Path) -> Iterable[Path]:
    return sorted(folder.glob("*.parquet"))


def consolidate(
    universe: pd.DataFrame,
    output_dir: Path,
    start_year: int,
    end_year: int,
) -> dict[str, Any]:
    company_status = universe.set_index("secucode")["status"].to_dict()
    company_name = universe.set_index("secucode")["name"].to_dict()
    summary: dict[str, Any] = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "start_year": start_year,
        "end_year": end_year,
        "universe_companies": int(len(universe)),
        "statements": {},
    }

    for statement in STATEMENTS:
        raw_folder = output_dir / "raw" / statement
        by_year: dict[int, list[pd.DataFrame]] = defaultdict(list)
        read_errors: list[dict[str, str]] = []
        for path in iter_parquet_files(raw_folder):
            try:
                frame = pd.read_parquet(path)
                if frame.empty or "REPORT_DATE" not in frame:
                    continue
                if "SECUCODE" not in frame:
                    stem = path.stem
                    code, exchange = stem.rsplit("_", 1)
                    frame["SECUCODE"] = f"{code}.{exchange}"
                frame["REPORT_YEAR"] = pd.to_datetime(
                    frame["REPORT_DATE"], errors="coerce"
                ).dt.year
                frame["UNIVERSE_STATUS"] = (
                    frame["SECUCODE"].map(company_status).fillna("unknown")
                )
                frame["UNIVERSE_NAME"] = (
                    frame["SECUCODE"].map(company_name).fillna("")
                )
                for year, part in frame.groupby("REPORT_YEAR", dropna=True):
                    year_int = int(year)
                    if start_year <= year_int <= end_year:
                        by_year[year_int].append(part.copy())
            except Exception as exc:
                read_errors.append(
                    {
                        "file": str(path),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        statement_summary: dict[str, Any] = {
            "raw_files": sum(1 for _ in iter_parquet_files(raw_folder)),
            "empty_markers": len(list(raw_folder.glob("*.empty.json"))),
            "read_errors": read_errors,
            "years": {},
        }
        for year in range(start_year, end_year + 1):
            parts = by_year.get(year, [])
            if not parts:
                statement_summary["years"][str(year)] = {
                    "rows": 0,
                    "companies": 0,
                }
                continue
            combined = pd.concat(parts, ignore_index=True, sort=False)
            combined.sort_values(
                ["SECUCODE", "REPORT_DATE"], inplace=True, ignore_index=True
            )
            combined.drop_duplicates(
                subset=["SECUCODE", "REPORT_DATE"],
                keep="last",
                inplace=True,
                ignore_index=True,
            )
            annual_path = (
                output_dir
                / "annual"
                / statement
                / f"{statement}_{year}.parquet"
            )
            atomic_write_parquet(combined, annual_path)
            statement_summary["years"][str(year)] = {
                "rows": int(len(combined)),
                "companies": int(combined["SECUCODE"].nunique()),
                "columns": int(len(combined.columns)),
                "file": str(annual_path.relative_to(output_dir)),
                "bytes": annual_path.stat().st_size,
            }
        summary["statements"][statement] = statement_summary

    summary_path = output_dir / "metadata" / "validation_summary.json"
    atomic_write_json(summary, summary_path)
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
        "selected %d companies for %d-%d",
        len(universe),
        args.start_year,
        args.end_year,
    )
    if not args.consolidate_only:
        counts = run_download(universe, args)
        logging.info("download pass finished: %s", dict(counts))
    summary = consolidate(
        universe,
        args.output_dir,
        args.start_year,
        args.end_year,
    )
    logging.info(
        "validation summary written: %s",
        args.output_dir / "metadata" / "validation_summary.json",
    )
    errors = 0
    progress_path = args.output_dir / "logs" / "download_progress.jsonl"
    if progress_path.exists():
        latest: dict[str, dict[str, Any]] = {}
        for line in progress_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                latest[item["secucode"]] = item
        errors = sum(item.get("status") == "error" for item in latest.values())
    read_errors = sum(
        len(item.get("read_errors", []))
        for item in summary["statements"].values()
    )
    return 1 if errors or read_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
