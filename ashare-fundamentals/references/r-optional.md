# Optional R usage

R is not used by the downloader. Install it only if the user wants to consume the generated data from R.

Parquet path:

```r
install.packages("arrow")
library(arrow)
x <- open_dataset("data/indicators/annual", format = "parquet")
```

DuckDB path:

```r
install.packages(c("DBI", "duckdb"))
con <- DBI::dbConnect(duckdb::duckdb())
DBI::dbGetQuery(con, "SELECT * FROM read_parquet('data/indicators/annual/*.parquet') LIMIT 10")
```

MySQL path (only when a server already exists):

```r
install.packages(c("DBI", "RMariaDB"))
con <- DBI::dbConnect(
  RMariaDB::MariaDB(),
  host = Sys.getenv("MYSQL_HOST", "127.0.0.1"),
  port = as.integer(Sys.getenv("MYSQL_PORT", "3306")),
  dbname = Sys.getenv("MYSQL_DATABASE"),
  user = Sys.getenv("MYSQL_USER"),
  password = Sys.getenv("MYSQL_PASSWORD")
)
```

