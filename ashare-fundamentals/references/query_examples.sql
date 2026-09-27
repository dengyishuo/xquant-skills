-- 示例 1：取一家公司最近 5 个报告期的核心三表数据。
-- 修改下面两处 '000001.SZ' 即可查询其他公司。
WITH recent_periods AS (
    SELECT DISTINCT report_date
    FROM a_share_financial_statement
    WHERE secucode = '000001.SZ'
    ORDER BY report_date DESC
    LIMIT 5
)
SELECT
    fs.secucode,
    MAX(fs.security_name) AS security_name,
    fs.report_date,
    MAX(fs.frequency) AS frequency,
    MAX(CASE WHEN fs.statement_type = 'balance_sheet'
        THEN CAST(fs.payload ->> '$.TOTAL_ASSETS' AS DECIMAL(38, 2)) END) AS total_assets,
    MAX(CASE WHEN fs.statement_type = 'balance_sheet'
        THEN CAST(fs.payload ->> '$.TOTAL_LIABILITIES' AS DECIMAL(38, 2)) END) AS total_liabilities,
    MAX(CASE WHEN fs.statement_type = 'balance_sheet'
        THEN CAST(fs.payload ->> '$.TOTAL_EQUITY' AS DECIMAL(38, 2)) END) AS total_equity,
    MAX(CASE WHEN fs.statement_type = 'income_statement'
        THEN CAST(COALESCE(fs.payload ->> '$.TOTAL_OPERATE_INCOME', fs.payload ->> '$.OPERATE_INCOME') AS DECIMAL(38, 2)) END) AS operating_income,
    MAX(CASE WHEN fs.statement_type = 'income_statement'
        THEN CAST(fs.payload ->> '$.PARENT_NETPROFIT' AS DECIMAL(38, 2)) END) AS parent_net_profit,
    MAX(CASE WHEN fs.statement_type = 'cash_flow_statement'
        THEN CAST(fs.payload ->> '$.NETCASH_OPERATE' AS DECIMAL(38, 2)) END) AS operating_cash_flow
FROM a_share_financial_statement AS fs
JOIN recent_periods AS rp ON rp.report_date = fs.report_date
WHERE fs.secucode = '000001.SZ'
GROUP BY fs.secucode, fs.report_date
ORDER BY fs.report_date DESC;

-- 示例 2：查看某一报告期三张报表的完整 JSON。
SELECT secucode, security_name, report_date, statement_type, frequency, payload
FROM a_share_financial_statement
WHERE secucode = '000001.SZ'
  AND report_date = '2025-12-31'
ORDER BY statement_type;

-- 示例 3：取主要财务指标中的每股收益、净资产收益率和资产负债率。
SELECT
    secucode,
    security_name,
    report_date,
    CAST(payload ->> '$.EPSJB' AS DECIMAL(18, 6)) AS basic_eps,
    CAST(payload ->> '$.ROEJQ' AS DECIMAL(18, 6)) AS weighted_roe,
    CAST(payload ->> '$.ZCFZL' AS DECIMAL(18, 6)) AS debt_asset_ratio
FROM a_share_main_financial_indicator
WHERE secucode = '000001.SZ'
ORDER BY report_date DESC
LIMIT 10;
