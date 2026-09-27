#!/usr/bin/env python3
"""Download 2016-2025 annual main financial indicators for A shares.

The source is Eastmoney's structured F10 ``MAINFINADATA`` endpoint.  One
request is made per security, the requested annual dates are filtered at the
server, and the result is stored as a resumable company-level Parquet file.
The consolidation pass creates annual files, one all-years Parquet file, a
gzip-compressed CSV, coverage tables, a column dictionary, and checksums.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
import random
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests


DATA_URL = "https://datacenter.eastmoney.com/securities/api/data/get"
STRING_COLUMNS = {
    "SECUCODE",
    "SECURITY_CODE",
    "SECURITY_NAME_ABBR",
    "ORG_CODE",
    "ORG_TYPE",
    "REPORT_TYPE",
    "REPORT_DATE_NAME",
    "SECURITY_TYPE_CODE",
    "CURRENCY",
    "IS_BZ",
}
DATE_COLUMNS = {"REPORT_DATE", "NOTICE_DATE", "UPDATE_DATE"}

# The endpoint contains 141 fields.  These descriptions cover the identifiers
# and the commonly used cross-industry indicators; every source field is still
# retained even when its description is intentionally left blank.
COLUMN_DESCRIPTIONS = {
    "SECUCODE": "证券代码（含交易所后缀）",
    "SECURITY_CODE": "证券代码",
    "SECURITY_NAME_ABBR": "证券简称",
    "ORG_CODE": "机构代码",
    "ORG_TYPE": "机构类型",
    "REPORT_DATE": "报告日期",
    "REPORT_TYPE": "报告类型",
    "REPORT_DATE_NAME": "报告期名称",
    "SECURITY_TYPE_CODE": "证券类型代码",
    "NOTICE_DATE": "公告日期",
    "UPDATE_DATE": "数据更新日期",
    "CURRENCY": "币种",
    "EPSJB": "基本每股收益（元）",
    "EPSKCJB": "扣非每股收益（元）",
    "EPSXS": "稀释每股收益（元）",
    "BPS": "每股净资产（元）",
    "MGZBGJ": "每股资本公积金（元）",
    "MGWFPLR": "每股未分配利润（元）",
    "MGJYXJJE": "每股经营现金流（元）",
    "TOTALOPERATEREVE": "营业总收入（元）",
    "MLR": "毛利润（元）",
    "PARENTNETPROFIT": "归属母公司股东净利润（元）",
    "KCFJCXSYJLR": "扣除非经常性损益净利润（元）",
    "TOTALOPERATEREVETZ": "营业总收入同比增长（%）",
    "PARENTNETPROFITTZ": "归母净利润同比增长（%）",
    "KCFJCXSYJLRTZ": "扣非净利润同比增长（%）",
    "YYZSRGDHBZC": "营业总收入滚动环比增长（%）",
    "NETPROFITRPHBZC": "归母净利润滚动环比增长（%）",
    "KFJLRGDHBZC": "扣非净利润滚动环比增长（%）",
    "ROEJQ": "加权净资产收益率（%）",
    "ROEKCJQ": "扣非加权净资产收益率（%）",
    "ZZCJLL": "加权总资产收益率（%）",
    "XSJLL": "净利率（%）",
    "XSMLL": "毛利率（%）",
    "YSZKYYSR": "预收账款/营业收入",
    "XSJXLYYSR": "销售净现金流/营业收入",
    "JYXJLYYSR": "经营净现金流/营业收入",
    "TAXRATE": "实际税率（%）",
    "LD": "流动比率",
    "SD": "速动比率",
    "XJLLB": "现金流量比率",
    "ZCFZL": "资产负债率（%）",
    "QYCS": "权益乘数",
    "CQBL": "产权比率",
    "ZZCZZTS": "总资产周转天数（天）",
    "CHZZTS": "存货周转天数（天）",
    "YSZKZZTS": "应收账款周转天数（天）",
    "TOAZZL": "总资产周转率（次）",
    "CHZZL": "存货周转率（次）",
    "YSZKZZL": "应收账款周转率（次）",
    "TOTALDEPOSITS": "存款总额（银行）",
    "GROSSLOANS": "贷款总额（银行）",
    "LTDRR": "存贷款比率（银行）",
    "NEWCAPITALADER": "资本充足率（银行）",
    "HXYJBCZL": "核心一级资本充足率（银行）",
    "NONPERLOAN": "不良贷款率（银行）",
    "BLDKBBL": "拨备覆盖率（银行）",
    "NZBJE": "内在价值（保险）",
    "TOTAL_ROI": "总投资收益率（保险）",
    "NET_ROI": "净投资收益率（保险）",
    "EARNED_PREMIUM": "已赚保费（保险）",
    "COMPENSATE_EXPENSE": "赔付支出（保险）",
    "SURRENDER_RATE_LIFE": "寿险退保率（保险）",
    "SOLVENCY_AR": "偿付能力充足率（保险）",
    "JZB": "净资本（证券）",
    "JZC": "净资产（证券）",
    "JZBJZC": "净资本/净资产（证券）",
    "ROIC": "投入资本回报率（%）",
    "ROICTZ": "投入资本回报率同比增长（%）",
    "PER_TOI": "每股营业总收入（元）",
    "PER_OI": "每股营业收入（元）",
    "PER_EBIT": "每股 EBIT（元）",
    "STAFF_NUM": "员工人数",
    "AVG_TOI": "人均营业总收入",
    "AVG_NET_PROFIT": "人均净利润",
    "PREPAID_ACCOUNTS_RATIO": "预付账款比率",
    "ACCOUNTS_PAYABLE_TR": "应付账款周转率",
    "FIXED_ASSET_TR": "固定资产周转率",
    "CURRENT_ASSET_TR": "流动资产周转率",
    "PREPAID_ACCOUNTS_TDAYS": "预付账款周转天数",
    "PAYABLE_TDAYS": "应付账款周转天数",
    "OPERATE_CYCLE": "营业周期",
    "GUARD_SPEED_RATIO": "保守速动比率",
    "CASH_RATIO": "现金比率",
    "INTEREST_COVERAGE_RATIO": "利息保障倍数",
    "CA_TA": "流动资产/总资产",
    "NCA_TA": "非流动资产/总资产",
    "LIQUIDATION_RATIO": "清算价值比率",
    "INTEREST_DEBT_RATIO": "有息负债比率",
    "FC_LIABILITIES": "固定资产/负债",
    "FCFF_FORWARD": "企业自由现金流（前向口径）",
    "FCFF_BACK": "企业自由现金流（后向口径）",
    "NCO_OP": "经营净现金流/营业利润",
    "NCO_NETPROFIT": "经营净现金流/净利润",
    "NCO_FIXED": "经营净现金流/固定资产",
    "UNIVERSE_STATUS": "公司清单中的上市/退市状态",
    "UNIVERSE_NAME": "公司清单中的证券名称",
    "LISTING_DATE": "上市日期（若清单可用）",
    "DELISTING_DATE": "退市日期（若清单可用）",
}

_thread_local = threading.local()


class DownloadError(RuntimeError):
    """Raised after all network retries are exhausted."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download ten years of annual A-share main indicators."
    )
    parser.add_argument("--universe-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--start-year", type=int, default=2016)
    parser.add_argument("--end-year", type=int, default=2025)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--consolidate-only", action="store_true")
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


def requested_dates(start_year: int, end_year: int) -> list[str]:
    return [f"{year}-12-31" for year in range(start_year, end_year + 1)]


def fetch_company(
    secucode: str, start_year: int, end_year: int, retries: int
) -> list[dict[str, Any]]:
    dates = ",".join(
        f"'{item}'" for item in requested_dates(start_year, end_year)
    )
    params = {
        "type": "RPT_F10_FINANCE_MAINFINADATA",
        "sty": "APP_F10_MAINFINADATA",
        "quoteColumns": "",
        "filter": (
            f'(SECUCODE="{secucode}")'
            f"(REPORT_DATE in ({dates}))"
        ),
        "p": "1",
        "ps": "200",
        "sr": "-1",
        "st": "REPORT_DATE",
        "source": "HSF10",
        "client": "PC",
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = get_session().get(
                DATA_URL, params=params, timeout=(10, 45)
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("success") is False and payload.get("result") is None:
                message = payload.get("message") or "source returned an error"
                if message not in {"返回数据为空", "ok"}:
                    raise DownloadError(str(message))
                return []
            return (payload.get("result") or {}).get("data") or []
        except (requests.RequestException, ValueError, DownloadError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                delay = min(15.0, 0.8 * (2**attempt)) + random.random() * 0.6
                time.sleep(delay)
    raise DownloadError(f"request failed after {retries} attempts: {last_error}")


def normalize_rows(
    rows: list[dict[str, Any]], start_year: int, end_year: int
) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "REPORT_DATE" not in frame or "SECUCODE" not in frame:
        raise DownloadError("response is missing SECUCODE or REPORT_DATE")

    report_dates = pd.to_datetime(frame["REPORT_DATE"], errors="coerce")
    keep = (
        report_dates.dt.year.between(start_year, end_year)
        & report_dates.dt.month.eq(12)
        & report_dates.dt.day.eq(31)
    )
    frame = frame.loc[keep].copy()
    if frame.empty:
        return frame

    for column in DATE_COLUMNS & set(frame.columns):
        parsed = pd.to_datetime(frame[column], errors="coerce")
        frame[column] = parsed.dt.strftime("%Y-%m-%d").astype("string")
    for column in frame.columns:
        if column in STRING_COLUMNS or column in DATE_COLUMNS:
            frame[column] = frame[column].astype("string")
        else:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

    sort_columns = ["REPORT_DATE"]
    if "UPDATE_DATE" in frame:
        sort_columns.append("UPDATE_DATE")
    frame.sort_values(sort_columns, inplace=True)
    frame.drop_duplicates(
        subset=["SECUCODE", "REPORT_DATE"], keep="last", inplace=True
    )
    frame.sort_values("REPORT_DATE", ascending=False, inplace=True)
    frame.reset_index(drop=True, inplace=True)
    return frame


def atomic_write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.part"
    )
    try:
        frame.to_parquet(
            temporary, index=False, engine="pyarrow", compression="zstd"
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.part")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def company_paths(output_dir: Path, secucode: str) -> tuple[Path, Path]:
    safe_code = secucode.replace(".", "_")
    folder = output_dir / "raw" / "by_company"
    return folder / f"{safe_code}.parquet", folder / f"{safe_code}.empty.json"


def result_is_complete(parquet_path: Path, empty_path: Path, force: bool) -> bool:
    if force:
        return False
    if empty_path.exists():
        return True
    if not parquet_path.exists() or parquet_path.stat().st_size == 0:
        return False
    try:
        frame = pd.read_parquet(
            parquet_path, columns=["SECUCODE", "REPORT_DATE"]
        )
        return not frame.empty
    except Exception:
        return False


def download_company(
    record: dict[str, Any], args: argparse.Namespace
) -> dict[str, Any]:
    started = time.monotonic()
    secucode = str(record["secucode"]).upper()
    parquet_path, empty_path = company_paths(args.output_dir, secucode)
    if result_is_complete(parquet_path, empty_path, args.force):
        return {
            "secucode": secucode,
            "status": "skipped",
            "seconds": round(time.monotonic() - started, 3),
        }
    try:
        rows = fetch_company(
            secucode, args.start_year, args.end_year, args.retries
        )
        frame = normalize_rows(rows, args.start_year, args.end_year)
        if frame.empty:
            atomic_write_json(
                {
                    "secucode": secucode,
                    "name": record.get("name", ""),
                    "reason": "source_returned_no_requested_annual_rows",
                    "checked_at": datetime.now().astimezone().isoformat(),
                },
                empty_path,
            )
            if parquet_path.exists():
                parquet_path.unlink()
            row_count = 0
        else:
            source_codes = set(frame["SECUCODE"].dropna().astype(str))
            if source_codes != {secucode}:
                raise DownloadError(
                    f"source code mismatch: expected {secucode}, got {source_codes}"
                )
            atomic_write_parquet(frame, parquet_path)
            if empty_path.exists():
                empty_path.unlink()
            row_count = len(frame)
        return {
            "secucode": secucode,
            "name": record.get("name", ""),
            "universe_status": record.get("status", ""),
            "status": "completed",
            "rows": row_count,
            "seconds": round(time.monotonic() - started, 3),
            "finished_at": datetime.now().astimezone().isoformat(),
        }
    except Exception as exc:
        return {
            "secucode": secucode,
            "name": record.get("name", ""),
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
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
        raise ValueError(f"universe is missing columns: {sorted(missing)}")
    frame["secucode"] = frame["secucode"].str.upper()
    frame.drop_duplicates("secucode", keep="last", inplace=True)
    frame.sort_values("secucode", inplace=True, ignore_index=True)
    if args.symbols:
        selected = {item.upper() for item in args.symbols}
        frame = frame.loc[frame["secucode"].isin(selected)].copy()
    if args.limit:
        frame = frame.head(args.limit).copy()
    if frame.empty:
        raise ValueError("selected universe is empty")
    return frame


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def run_download(universe: pd.DataFrame, args: argparse.Namespace) -> Counter:
    records = universe.to_dict(orient="records")
    progress_path = args.output_dir / "logs" / "download_progress.jsonl"
    counts: Counter = Counter()
    rows = 0
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=args.workers
    ) as executor:
        futures = {
            executor.submit(download_company, record, args): record["secucode"]
            for record in records
        }
        for index, future in enumerate(
            concurrent.futures.as_completed(futures), start=1
        ):
            secucode = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "secucode": secucode,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            append_jsonl(progress_path, result)
            counts[result["status"]] += 1
            rows += int(result.get("rows") or 0)
            if (
                index == 1
                or index % 50 == 0
                or index == len(records)
                or result["status"] == "error"
            ):
                elapsed = max(time.monotonic() - started, 0.001)
                rate = index / elapsed
                eta = (len(records) - index) / max(rate, 0.001) / 60
                logging.info(
                    "progress %d/%d | completed=%d skipped=%d errors=%d "
                    "| new_rows=%d | %.2f companies/s | ETA %.1f min",
                    index,
                    len(records),
                    counts["completed"],
                    counts["skipped"],
                    counts["error"],
                    rows,
                    rate,
                    eta,
                )
    return counts


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def latest_progress_errors(progress_path: Path) -> list[dict[str, Any]]:
    if not progress_path.exists():
        return []
    latest: dict[str, dict[str, Any]] = {}
    with progress_path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                latest[item["secucode"]] = item
    return [item for item in latest.values() if item.get("status") == "error"]


def consolidate(
    universe: pd.DataFrame,
    output_dir: Path,
    start_year: int,
    end_year: int,
) -> dict[str, Any]:
    raw_folder = output_dir / "raw" / "by_company"
    universe_index = universe.set_index("secucode")
    parts: list[pd.DataFrame] = []
    read_errors: list[dict[str, str]] = []

    for path in sorted(raw_folder.glob("*.parquet")):
        try:
            frame = pd.read_parquet(path)
            if frame.empty:
                continue
            if {"SECUCODE", "REPORT_DATE"} - set(frame.columns):
                raise ValueError("missing SECUCODE or REPORT_DATE")
            parts.append(frame)
        except Exception as exc:
            read_errors.append(
                {"file": str(path), "error": f"{type(exc).__name__}: {exc}"}
            )
    if not parts:
        raise RuntimeError("no company Parquet files were available")

    combined = pd.concat(parts, ignore_index=True, sort=False)
    combined["REPORT_DATE"] = combined["REPORT_DATE"].astype("string")
    combined["UNIVERSE_STATUS"] = combined["SECUCODE"].map(
        universe_index["status"]
    )
    combined["UNIVERSE_NAME"] = combined["SECUCODE"].map(
        universe_index["name"]
    )
    for source, target in (
        ("listing_date", "LISTING_DATE"),
        ("delisting_date", "DELISTING_DATE"),
    ):
        if source in universe_index.columns:
            combined[target] = combined["SECUCODE"].map(universe_index[source])
            combined[target] = combined[target].astype("string")

    combined.sort_values(
        ["REPORT_DATE", "SECUCODE"], inplace=True, ignore_index=True
    )
    duplicate_count = int(
        combined.duplicated(["SECUCODE", "REPORT_DATE"], keep=False).sum()
    )
    combined.drop_duplicates(
        ["SECUCODE", "REPORT_DATE"], keep="last", inplace=True
    )
    parsed_dates = pd.to_datetime(combined["REPORT_DATE"], errors="coerce")
    combined["REPORT_YEAR_INT"] = parsed_dates.dt.year.astype("Int64")
    valid_dates = (
        parsed_dates.dt.year.between(start_year, end_year)
        & parsed_dates.dt.month.eq(12)
        & parsed_dates.dt.day.eq(31)
    )
    invalid_date_rows = int((~valid_dates).sum())
    combined = combined.loc[valid_dates].copy()

    annual_files: list[Path] = []
    rows_by_year: list[dict[str, Any]] = []
    for year in range(start_year, end_year + 1):
        annual = combined.loc[combined["REPORT_YEAR_INT"].eq(year)].copy()
        annual.sort_values("SECUCODE", inplace=True, ignore_index=True)
        path = output_dir / "annual" / f"main_financial_indicators_{year}.parquet"
        atomic_write_parquet(annual, path)
        annual_files.append(path)
        rows_by_year.append(
            {
                "year": year,
                "rows": len(annual),
                "companies": annual["SECUCODE"].nunique(),
                "columns": len(annual.columns),
                "file_bytes": path.stat().st_size,
            }
        )

    all_years_folder = output_dir / "all_years"
    parquet_path = (
        all_years_folder
        / f"a_share_main_financial_indicators_{start_year}_{end_year}.parquet"
    )
    csv_path = (
        all_years_folder
        / f"a_share_main_financial_indicators_{start_year}_{end_year}.csv.gz"
    )
    combined.sort_values(
        ["SECUCODE", "REPORT_DATE"], inplace=True, ignore_index=True
    )
    atomic_write_parquet(combined, parquet_path)
    all_years_folder.mkdir(parents=True, exist_ok=True)
    csv_temp = csv_path.with_name(f".{csv_path.name}.{os.getpid()}.part")
    try:
        combined.to_csv(
            csv_temp,
            index=False,
            encoding="utf-8-sig",
            compression="gzip",
        )
        os.replace(csv_temp, csv_path)
    finally:
        if csv_temp.exists():
            csv_temp.unlink()

    metadata = output_dir / "metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_by_year).to_csv(
        metadata / "rows_by_year.csv", index=False, encoding="utf-8-sig"
    )
    universe.to_csv(
        metadata / "companies.csv", index=False, encoding="utf-8-sig"
    )
    atomic_write_parquet(universe, metadata / "companies.parquet")

    coverage = (
        combined.groupby("SECUCODE", observed=True)
        .agg(
            rows=("REPORT_DATE", "size"),
            first_report_date=("REPORT_DATE", "min"),
            last_report_date=("REPORT_DATE", "max"),
        )
        .reset_index()
    )
    years_by_code = (
        combined.groupby("SECUCODE", observed=True)["REPORT_YEAR_INT"]
        .apply(lambda values: ",".join(str(int(item)) for item in sorted(values)))
        .to_dict()
    )
    coverage["years_present"] = coverage["SECUCODE"].map(years_by_code)
    coverage = universe[["secucode", "name", "status"]].merge(
        coverage, how="left", left_on="secucode", right_on="SECUCODE"
    )
    coverage["rows"] = coverage["rows"].fillna(0).astype(int)
    coverage["years_present"] = coverage["years_present"].fillna("")
    expected_years = set(range(start_year, end_year + 1))
    coverage["missing_years"] = coverage["years_present"].map(
        lambda value: ",".join(
            str(year)
            for year in sorted(
                expected_years
                - {int(item) for item in value.split(",") if item}
            )
        )
    )
    coverage.drop(columns=["SECUCODE"], inplace=True)
    coverage.to_csv(
        metadata / "company_coverage.csv", index=False, encoding="utf-8-sig"
    )

    dictionary_rows: list[dict[str, Any]] = []
    for column in combined.columns:
        non_null = int(combined[column].notna().sum())
        dictionary_rows.append(
            {
                "column": column,
                "description_zh": COLUMN_DESCRIPTIONS.get(column, ""),
                "dtype": str(combined[column].dtype),
                "non_null_rows": non_null,
                "coverage_pct": round(non_null / len(combined) * 100, 4),
            }
        )
    pd.DataFrame(dictionary_rows).to_csv(
        metadata / "column_dictionary.csv", index=False, encoding="utf-8-sig"
    )

    manifest_rows = []
    for path in annual_files + [parquet_path, csv_path]:
        manifest_rows.append(
            {
                "file": str(path.relative_to(output_dir)),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    pd.DataFrame(manifest_rows).to_csv(
        metadata / "file_manifest.csv", index=False, encoding="utf-8-sig"
    )

    progress_errors = latest_progress_errors(
        output_dir / "logs" / "download_progress.jsonl"
    )
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "source": "Eastmoney F10 RPT_F10_FINANCE_MAINFINADATA",
        "start_year": start_year,
        "end_year": end_year,
        "universe_companies": int(len(universe)),
        "raw_parquet_files": len(list(raw_folder.glob("*.parquet"))),
        "empty_markers": len(list(raw_folder.glob("*.empty.json"))),
        "rows": int(len(combined)),
        "companies_with_data": int(combined["SECUCODE"].nunique()),
        "columns": int(len(combined.columns)),
        "duplicate_rows_before_deduplication": duplicate_count,
        "invalid_date_rows_removed": invalid_date_rows,
        "read_errors": read_errors,
        "latest_download_errors": progress_errors,
        "rows_by_year": rows_by_year,
        "all_years_parquet": str(parquet_path.relative_to(output_dir)),
        "all_years_csv_gz": str(csv_path.relative_to(output_dir)),
    }
    atomic_write_json(summary, metadata / "validation_summary.json")
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
    if args.workers < 1 or args.retries < 1:
        raise ValueError("workers and retries must be positive")
    universe = load_universe(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
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
        universe, args.output_dir, args.start_year, args.end_year
    )
    logging.info(
        "consolidated %d rows from %d companies into %d columns",
        summary["rows"],
        summary["companies_with_data"],
        summary["columns"],
    )
    return 1 if summary["read_errors"] or summary["latest_download_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
