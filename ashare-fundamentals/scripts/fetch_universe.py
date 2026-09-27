#!/usr/bin/env python3
"""Fetch the current mainland A-share universe from Eastmoney."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests


URLS = (
    "https://82.push2.eastmoney.com/api/qt/clist/get",
    "https://push2.eastmoney.com/api/qt/clist/get",
)
FIELDS = "f12,f13,f14,f26"
MARKETS = "m:1+t:2,m:1+t:23,m:0+t:6,m:0+t:80,m:0+t:81"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45)
    return parser.parse_args()


def normalize_date(value: object) -> str:
    text = str(value or "").split(".")[0]
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return ""


def main() -> int:
    args = parse_args()
    params = {
        "pn": "1", "pz": "10000", "po": "1", "np": "1", "fltt": "2",
        "invt": "2", "fid": "f12", "fs": MARKETS, "fields": FIELDS,
    }
    rows = []
    errors = []
    for url in URLS:
        try:
            response = requests.get(
                url,
                params=params,
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                timeout=args.timeout,
            )
            response.raise_for_status()
            rows = ((response.json().get("data") or {}).get("diff") or [])
            if rows:
                break
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    if not rows:
        detail = "; ".join(errors) if errors else "source returned no rows"
        raise RuntimeError(
            "company-universe endpoint is unavailable; retry later or supply a CSV "
            f"with secucode,name,status columns. Details: {detail}"
        )

    captured_at = datetime.now().astimezone().isoformat()
    records = []
    for row in rows:
        code = str(row.get("f12") or "").zfill(6)
        market = str(row.get("f13") or "")
        exchange = "SH" if market == "1" else "BJ" if code.startswith(("4", "8", "92")) else "SZ"
        records.append({
            "secucode": f"{code}.{exchange}",
            "code": code,
            "exchange": exchange,
            "name": str(row.get("f14") or ""),
            "status": "listed",
            "listing_date": normalize_date(row.get("f26")),
            "delisting_date": "",
            "captured_at": captured_at,
        })
    frame = pd.DataFrame(records).drop_duplicates("secucode", keep="last")
    frame.sort_values("secucode", inplace=True, ignore_index=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"wrote {len(frame)} securities to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
