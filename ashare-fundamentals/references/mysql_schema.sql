CREATE TABLE IF NOT EXISTS a_share_company (
  secucode VARCHAR(16) NOT NULL,
  security_code VARCHAR(12),
  exchange VARCHAR(8),
  name VARCHAR(128),
  `status` VARCHAR(32),
  listing_date DATE,
  delisting_date DATE,
  captured_at VARCHAR(64),
  source_path VARCHAR(512) NOT NULL,
  payload JSON NOT NULL,
  imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (secucode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS a_share_financial_statement (
  secucode VARCHAR(16) NOT NULL,
  report_date DATE NOT NULL,
  statement_type ENUM('balance_sheet','income_statement','cash_flow_statement') NOT NULL,
  frequency ENUM('annual','q1','q2','q3','other') NOT NULL,
  notice_date DATE,
  update_date DATE,
  report_type VARCHAR(32),
  security_name VARCHAR(128),
  org_type VARCHAR(32),
  source_path VARCHAR(512) NOT NULL,
  payload JSON NOT NULL,
  imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (secucode, report_date, statement_type),
  KEY idx_a_share_fs_report_date (report_date),
  KEY idx_a_share_fs_type_date (statement_type, report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS a_share_main_financial_indicator (
  secucode VARCHAR(16) NOT NULL,
  report_date DATE NOT NULL,
  notice_date DATE,
  update_date DATE,
  report_type VARCHAR(32),
  security_name VARCHAR(128),
  org_type VARCHAR(32),
  source_path VARCHAR(512) NOT NULL,
  payload JSON NOT NULL,
  imported_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (secucode, report_date),
  KEY idx_a_share_mfi_report_date (report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

