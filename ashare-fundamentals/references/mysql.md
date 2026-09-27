# Optional MySQL backend

MySQL is not required for downloading or querying Parquet files. Use this path only when the user already has MySQL 8.0+ or explicitly chooses to install it.

## Install only the Python connector

```bash
python -m pip install -e '.[mysql]'
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

