# Optional MySQL backend

MySQL is not required for downloading or querying Parquet files. Use this path only when the user already has MySQL 8.0+ or explicitly chooses to install it.

## Install only the Python connector

From a repository clone:

```bash
python -m pip install -e '.[mysql]'
```

If you only have the unpacked Skill package (the ZIP has no `pyproject.toml`), install the connector directly:

```bash
python -m pip install PyMySQL
```

Set credentials in environment variables; never commit them:

```bash
export MYSQL_HOST=127.0.0.1
export MYSQL_PORT=3306
export MYSQL_DATABASE=xquant
export MYSQL_USER=xquant
export MYSQL_PASSWORD='...'
```

Create the tables:

```bash
mysql -h "$MYSQL_HOST" -P "$MYSQL_PORT" -u "$MYSQL_USER" -p \
  "$MYSQL_DATABASE" < ashare-fundamentals/references/mysql_schema.sql
```

Import Parquet files with the Python importer:

```bash
python ashare-fundamentals/scripts/import_mysql.py \
  --statement-root data/statements \
  --indicator-root data/indicators
```

The importer uses upserts and batches rows. Run `--dry-run` first when checking discovery. Database mutation still requires the user's authorization.

## Example queries

[query_examples.sql](query_examples.sql) holds ready-to-run statements for common questions, including the latest reporting periods per company and cross-statement lookups. Run them with the `mysql` client once the tables are loaded.

