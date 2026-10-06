---
name: ashare-fundamentals
description: Download, resume, validate, inventory, and optionally import A-share financial statements and fundamental indicators. Use for A股财报、三表、财务指标、Parquet 数据集、DuckDB 查询或 MySQL 入库；do not use for行情下载、交易执行或策略回测。
metadata:
  version: "0.2.2"
  author: "Deng Yishuo"
  display_name: "A股财库"
  display_name_en: "A-Share Fundamentals"
  description_zh: "下载、续传、校验和盘点 A 股三张财务报表及主要财务指标。"
  description_en: "Download, resume, validate, and inventory A-share statements and fundamental indicators."
---

# A股财库 · A-Share Fundamentals

Build a reproducible A-share fundamentals dataset without requiring R or a database.

This is a portable Agent Skill for WorkBuddy, Doubao Work, QwenWork, Codex, Claude Code, and other hosts that support `SKILL.md`. For installation and host-specific limitations, read [platforms.md](references/platforms.md); WorkBuddy may load it as `@references/platforms.md`.

## Choose the operation

- For a new dataset, read [setup.md](references/setup.md), generate the company universe, then download annual statements, interim statements, or indicators.
- For an interrupted run, rerun the same command. Resume is the default; use `--force` only when the user explicitly requests replacement or a file is proven corrupt.
- For status or coverage, run `scripts/inventory.py` and inspect generated summaries. Do not download or import for a read-only request.
- For MySQL, read [mysql.md](references/mysql.md). Treat MySQL and `PyMySQL` as optional; never install or start a database service without explicit user approval.
- For R, read [r-optional.md](references/r-optional.md). R is an optional consumer, not part of the download path.

## Runtime preflight

Before executing a script, confirm that the host exposes a local shell, Python 3.10+, outbound HTTPS, and a writable workspace. Web-only or cloud workspaces without local command execution can read the workflow but cannot run the downloader.

Check dependencies without changing the environment:

```bash
python3 -c "import pandas, pyarrow, requests; print('core dependencies ready')"
```

If a dependency is missing, explain the change and request approval before running `python3 -m pip install -r requirements.txt`. Never install MySQL, R, or optional Python packages implicitly.

## Workflow invariants

1. Confirm the requested securities, report periods, output directory, and whether the operation may mutate a database.
2. Use a separate output directory for `--limit` or `--symbols` tests so partial tests do not pollute production progress logs.
3. Preserve per-company Parquet files, empty markers, metadata, and append-only JSONL progress logs.
4. Treat a source-returned empty result separately from a transport, parsing, or schema failure.
5. Rebuild consolidated files and metadata before judging coverage.
6. Report concrete row counts, company counts, date ranges, missing securities, errors, output paths, and whether a database was changed.

## Commands

From this Skill directory:

```bash
python scripts/fetch_universe.py --output data/companies.csv

python scripts/download_statements.py \
  --universe-csv data/companies.csv --output-dir data/statements \
  --start-year 2016 --end-year 2025

python scripts/download_interim_statements.py \
  --universe-csv data/companies.csv --output-dir data/statements \
  --start-year 2016 --end-year 2025

python scripts/download_indicators.py \
  --universe-csv data/companies.csv --output-dir data/indicators \
  --start-year 2016 --end-year 2025

python scripts/inventory.py --data-root data --output outputs/inventory.json
```

Inspect each script with `--help` before adapting a period. For a current or future quarter, pass exact dates only through a reviewed period-specific wrapper; do not relabel annual files or assume unpublished data exists.

## Data source and safety

The bundled downloaders use public Eastmoney F10 endpoints and retain the source fields. Endpoints and terms may change. Avoid aggressive concurrency, obey applicable terms, and identify source-side gaps instead of fabricating rows. Never commit credentials or downloaded datasets.
