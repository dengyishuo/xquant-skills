# Setup

## Core Python environment

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

This installs only the download and Parquet dependencies. It does not install MySQL, DuckDB, or R.

## Company universe

Generate a current mainland A-share list:

```bash
python ashare-fundamentals/scripts/fetch_universe.py \
  --output data/companies.csv
```

The download scripts require the columns `secucode`, `name`, and `status`. A user-supplied CSV with those columns is also supported.

## Small verification run

Use a dedicated directory:

```bash
python ashare-fundamentals/scripts/download_statements.py \
  --universe-csv data/companies.csv \
  --output-dir data/test-statements \
  --start-year 2024 --end-year 2025 \
  --symbols 600519.SH 000001.SZ
```

After verifying representative ordinary and financial companies, run the full universe without `--symbols`.

## DuckDB (optional)

From a repository clone:

```bash
python -m pip install -e '.[duckdb]'
duckdb
```

If you only have the unpacked Skill package (the ZIP has no `pyproject.toml`), install DuckDB directly:

```bash
python -m pip install duckdb
```

Example query:

```sql
SELECT SECUCODE, REPORT_DATE, EPSJB, ROEJQ
FROM read_parquet('data/indicators/annual/*.parquet')
ORDER BY REPORT_DATE DESC, SECUCODE;
```

