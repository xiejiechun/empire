-- Initial business schema only; application startup never executes DDL.
-- DATETIME values use Asia/Shanghai wall-clock time (UTC+08:00).
-- Fixed source ownership is declared in contracts/business_schema.py; news retains per-row source.
CREATE TABLE IF NOT EXISTS stock_index (
    index_code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    source_group VARCHAR(40) NOT NULL,
    members_available BOOLEAN NULL,
    member_count INT UNSIGNED NOT NULL DEFAULT 0,
    member_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
    PRIMARY KEY (index_code),
    CONSTRAINT ck_index_code CHECK (index_code REGEXP '^[0-9A-Z]{6}$'),
    CONSTRAINT ck_index_members CHECK (member_count < 10000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stock_index_member (
    index_code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_code VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NULL,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (index_code, source_code),
    KEY ix_index_security (unified_code, index_code),
    KEY ix_index_source_security (source_code, index_code),
    CONSTRAINT ck_index_member_code CHECK (source_code REGEXP '^[0-9]{5,6}$'),
    CONSTRAINT ck_index_member_unified CHECK (unified_code IS NULL OR unified_code REGEXP '^[0-9]{6}[.](SH|SZ|BJ)$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS industry (
    industry_code CHAR(6) NOT NULL,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (industry_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS industry_member (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    industry_code CHAR(6) NOT NULL,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (industry_code, unified_code),
    KEY ix_industry_security (unified_code, industry_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stock (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (unified_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- One last SQL-confirmed archive state per collection project, not a run history.
CREATE TABLE IF NOT EXISTS collection_state (
    namespace VARCHAR(160) NOT NULL,
    project_id VARCHAR(100) NOT NULL,
    source VARCHAR(80) NOT NULL,
    dataset VARCHAR(80) NOT NULL,
    payload JSON NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (namespace, project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- One row per calendar date, including explicit non-trading days; no raw response storage.
CREATE TABLE IF NOT EXISTS trade_calendar (
    trade_date DATE NOT NULL,
    is_trade BOOLEAN NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Source records with different resumption times or descriptions coexist.
CREATE TABLE IF NOT EXISTS suspension_event (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    suspended_at DATETIME(6) NOT NULL,
    resumed_at DATETIME(6) NULL,
    resume_key DATETIME(6) NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_dates_known BOOLEAN NOT NULL,
    suspension_type VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_note VARCHAR(100) NOT NULL,
    reason VARCHAR(500) NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (unified_code, suspended_at, resume_key, record_key),
    CONSTRAINT ck_suspension_resume_key_v2 CHECK (resume_key=COALESCE(resumed_at,'1000-01-01 00:00:00')),
    INDEX ix_suspension_start (suspended_at, unified_code),
    INDEX ix_suspension_resume (resumed_at, unified_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Historical flash-news business records; no successful original responses or operation logs.
CREATE TABLE IF NOT EXISTS finance_news (
    source VARCHAR(80) NOT NULL,
    news_id BIGINT NOT NULL,
    title VARCHAR(256) NOT NULL,
    content MEDIUMTEXT NOT NULL,
    published_at DATETIME(6) NOT NULL,
    source_updated_at DATETIME(6) NOT NULL,
    is_important BOOLEAN NOT NULL DEFAULT FALSE,
    tags JSON NOT NULL,
    url VARCHAR(2048) NOT NULL,
    first_seen_at DATETIME(6) NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, news_id),
    INDEX ix_news_published (source, published_at, news_id),
    INDEX ix_news_important (source, is_important, published_at, news_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- User configuration only; runtime cursors and logs remain in Redis.
CREATE TABLE IF NOT EXISTS app_setting (
    namespace VARCHAR(160) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    setting_key VARCHAR(120) NOT NULL,
    payload JSON NOT NULL,
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (namespace, kind, setting_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS dividend_plan (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    event_date DATE NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    INDEX ix_security_date (unified_code, event_date),
    INDEX ix_security_order ((RIGHT(unified_code,2)), unified_code, record_key),
    INDEX ix_event_date (event_date DESC, (RIGHT(unified_code,2)), unified_code, record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS additional_issue (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    event_date DATE NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    INDEX ix_security_date (unified_code, event_date),
    INDEX ix_security_order ((RIGHT(unified_code,2)), unified_code, record_key),
    INDEX ix_event_date (event_date DESC, (RIGHT(unified_code,2)), unified_code, record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rights_issue (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    event_date DATE NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    INDEX ix_security_date (unified_code, event_date),
    INDEX ix_security_order ((RIGHT(unified_code,2)), unified_code, record_key),
    INDEX ix_event_date (event_date DESC, (RIGHT(unified_code,2)), unified_code, record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;



















CREATE TABLE IF NOT EXISTS income_statement (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    report_date DATE NOT NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (unified_code, report_date),
    INDEX ix_report_date (report_date DESC, (RIGHT(unified_code,2)), unified_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS balance_statement (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    report_date DATE NOT NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (unified_code, report_date),
    INDEX ix_report_date (report_date DESC, (RIGHT(unified_code,2)), unified_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS cashflow_statement (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    report_date DATE NOT NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (unified_code, report_date),
    INDEX ix_report_date (report_date DESC, (RIGHT(unified_code,2)), unified_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Source appearances are business associations, not collection run history.
CREATE TABLE IF NOT EXISTS security_name_change (
    name_kind VARCHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    event_date DATE NOT NULL,
    old_name VARCHAR(200) NULL,
    new_name VARCHAR(200) NULL,
    source_occurrences INT UNSIGNED NOT NULL,
    csrc_industry VARCHAR(200) NULL,
    tdx_industry VARCHAR(200) NULL,
    PRIMARY KEY (name_kind, record_key),
    KEY ix_name_security (name_kind, unified_code, event_date, record_key),
    KEY ix_name_date (name_kind, event_date, unified_code, record_key),
    CONSTRAINT ck_name_kind CHECK (name_kind IN ('company','security')),
    CONSTRAINT ck_name_occurrences CHECK (source_occurrences BETWEEN 1 AND 29999),
    CONSTRAINT ck_name_old CHECK (old_name IS NULL OR CHAR_LENGTH(TRIM(old_name))>0),
    CONSTRAINT ck_name_new CHECK (new_name IS NULL OR CHAR_LENGTH(TRIM(new_name))>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS suspension_source_date (
    source_date DATE NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    suspended_at DATETIME(6) NOT NULL,
    resume_key DATETIME(6) NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (source_date, unified_code, suspended_at, resume_key, record_key),
    INDEX ix_suspension_identity (unified_code, suspended_at, resume_key, record_key, source_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS stock_listing (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    listing_date DATE NOT NULL,
    establish_date DATE NULL,
    issuance_num DECIMAL(24,4) NULL,
    issuance_price DECIMAL(24,4) NULL,
    first_day_open_price DECIMAL(24,4) NULL,
    estimated_raised DECIMAL(24,4) NULL,
    actual_raised DECIMAL(24,4) NULL,
    issuance_pe DECIMAL(20,4) NULL,
    winning_rate DECIMAL(20,10) NULL,
    lead_underwriter VARCHAR(2048) NULL,
    sponsor VARCHAR(2048) NULL,
    history MEDIUMTEXT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    contract_version SMALLINT UNSIGNED NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (unified_code),
    KEY ix_listing_date (listing_date, unified_code),
    CONSTRAINT ck_listing_dates CHECK (listing_date >= '1900-01-01' AND (establish_date IS NULL OR establish_date >= '1900-01-01')),
    CONSTRAINT ck_listing_numbers CHECK ((issuance_num IS NULL OR issuance_num >= 0) AND (issuance_price IS NULL OR issuance_price >= 0) AND (first_day_open_price IS NULL OR first_day_open_price >= 0) AND (estimated_raised IS NULL OR estimated_raised >= 0) AND (actual_raised IS NULL OR actual_raised >= 0) AND (winning_rate IS NULL OR winning_rate BETWEEN 0 AND 100)),
    CONSTRAINT ck_listing_history CHECK (history IS NULL OR OCTET_LENGTH(history) <= 262144),
    CONSTRAINT ck_listing_contract CHECK (contract_version IN (1, 2))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS security_listing_event (
    event_date DATE NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    event_type VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT NULL,
    PRIMARY KEY (event_date, unified_code, event_type, record_key),
    KEY ix_security_date (unified_code, event_date, event_type, record_key),
    KEY ix_type_date (event_type, event_date, unified_code, record_key),
    CONSTRAINT ck_listing_event_date CHECK (event_date >= '1990-12-19'),
    CONSTRAINT ck_listing_event_type CHECK (event_type IN ('suspended', 'resumed', 'terminated')),
    CONSTRAINT ck_listing_event_description CHECK (description IS NULL OR CHAR_LENGTH(description) <= 2000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS security_code_alias (
    legacy_code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    listing_date DATE NOT NULL,
    version_observed_at DATETIME NOT NULL,
    PRIMARY KEY (legacy_code),
    UNIQUE KEY ux_alias_security (unified_code),
    CONSTRAINT ck_alias_old CHECK (REGEXP_LIKE(legacy_code, '^[48][0-9]{5}$')),
    CONSTRAINT ck_alias_current CHECK (REGEXP_LIKE(unified_code, '^920[0-9]{3}[.]BJ$')),
    CONSTRAINT ck_alias_name CHECK (CHAR_LENGTH(TRIM(name)) BETWEEN 1 AND 100)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS index_daily_price (
    index_code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    open DECIMAL(18,6) NULL,
    high DECIMAL(18,6) NULL,
    low DECIMAL(18,6) NULL,
    close DECIMAL(18,6) NOT NULL,
    volume DECIMAL(24,4) NOT NULL,
    amount DECIMAL(24,4) NULL,
    PRIMARY KEY (index_code, trade_date),
    KEY ix_index_price_date (trade_date, index_code),
    CONSTRAINT ck_index_price_code CHECK (REGEXP_LIKE(index_code, '^[0-9A-Z]{6}$')),
    CONSTRAINT ck_index_price_date CHECK (trade_date >= '1990-01-01'),
    CONSTRAINT ck_index_price_ohlc CHECK (close > 0 AND (open IS NULL OR open > 0) AND (high IS NULL OR high > 0) AND (low IS NULL OR low > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS index_price_year (
    index_code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    quote_year SMALLINT UNSIGNED NOT NULL,
    source_count SMALLINT UNSIGNED NOT NULL,
    row_count SMALLINT UNSIGNED NOT NULL,
    first_date DATE NOT NULL,
    last_date DATE NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    complete BOOLEAN NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (index_code, quote_year),
    CONSTRAINT ck_index_year_code CHECK (REGEXP_LIKE(index_code, '^[0-9A-Z]{6}$')),
    CONSTRAINT ck_index_year_count CHECK (source_count BETWEEN 1 AND 366 AND row_count BETWEEN 1 AND 366),
    CONSTRAINT ck_index_year_dates CHECK (YEAR(first_date) = quote_year AND YEAR(last_date) = quote_year AND first_date <= last_date),
    CONSTRAINT ck_index_year_hash CHECK (REGEXP_LIKE(content_hash, '^[0-9a-f]{64}$')),
    CONSTRAINT ck_index_year_complete CHECK (complete IN (0,1) AND (complete = 0 OR source_count = row_count))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS security_st_event (
    event_kind VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    event_date DATE NOT NULL,
    old_name VARCHAR(200) NULL,
    new_name VARCHAR(200) NULL,
    source_occurrences INT UNSIGNED NOT NULL,
    csrc_industry VARCHAR(200) NULL,
    tdx_industry VARCHAR(200) NULL,
    reason VARCHAR(2000) NULL,
    PRIMARY KEY (event_kind, record_key),
    KEY ix_st_security (event_kind, unified_code, event_date, record_key),
    KEY ix_st_date (event_kind, event_date, unified_code, record_key),
    CONSTRAINT ck_event_kind CHECK (event_kind IN ('implementation','removal')),
    CONSTRAINT ck_st_occurrences CHECK (source_occurrences = 1),
    CONSTRAINT ck_st_old CHECK (old_name IS NULL OR CHAR_LENGTH(TRIM(old_name))>0),
    CONSTRAINT ck_st_new CHECK (new_name IS NULL OR CHAR_LENGTH(TRIM(new_name))>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
CREATE TABLE IF NOT EXISTS trading_rule_citation (
  citation_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  issuer VARCHAR(100) NOT NULL,
  title VARCHAR(200) NOT NULL,
  source_url VARCHAR(1000) NOT NULL,
  published_date DATE NOT NULL,
  document_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  clause_key VARCHAR(100) NOT NULL,
  excerpt VARCHAR(4000) NOT NULL,
  PRIMARY KEY (citation_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS trading_rule_value (
  record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  kind VARCHAR(30) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  market VARCHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  board VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  condition_key VARCHAR(50) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  parameter_key VARCHAR(50) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  effective_start DATE NOT NULL,
  effective_end DATE NULL,
  number_value DECIMAL(16,8) NULL,
  text_value VARCHAR(200) NOT NULL,
  start_time TIME NULL,
  end_time TIME NULL,
  unit VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  citation_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  PRIMARY KEY (record_key),
  KEY ix_rule_kind_market (kind,market,record_key),
  KEY ix_rule_citation (citation_key),
  KEY ix_rule_effective (kind,effective_start,record_key),
  CONSTRAINT fk_rule_citation FOREIGN KEY (citation_key) REFERENCES trading_rule_citation(citation_key),
  CONSTRAINT ck_rule_dates CHECK (effective_end IS NULL OR effective_end >= effective_start),
  CONSTRAINT ck_rule_number CHECK (number_value IS NULL OR number_value >= 0),
  CONSTRAINT ck_rule_session CHECK ((start_time IS NULL AND end_time IS NULL) OR (start_time IS NOT NULL AND end_time IS NOT NULL AND start_time < end_time))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stock_repurchase_plan (
  plan_id VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(100) NOT NULL,
  share_type VARCHAR(80) NOT NULL,
  plan_date DATE NOT NULL,
  updated_date DATE NOT NULL,
  progress_code VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  plan_updated_date DATE NULL,
  actual_through DATE NULL,
  notice_date DATE NULL,
  start_date DATE NULL,
  end_date DATE NULL,
  finish_date DATE NULL,
  shareholder_notice_date DATE NULL,
  advance_date DATE NULL,
  plan_price_upper DECIMAL(28,8) NULL,
  plan_price_lower DECIMAL(28,8) NULL,
  plan_quantity_upper DECIMAL(28,8) NULL,
  plan_quantity_lower DECIMAL(28,8) NULL,
  plan_amount_upper DECIMAL(28,8) NULL,
  plan_amount_lower DECIMAL(28,8) NULL,
  actual_price_upper DECIMAL(28,8) NULL,
  actual_price_lower DECIMAL(28,8) NULL,
  actual_quantity DECIMAL(28,8) NULL,
  actual_amount DECIMAL(28,8) NULL,
  objective MEDIUMTEXT NULL,
  remark MEDIUMTEXT NULL,
  progress_remark MEDIUMTEXT NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (plan_id),
  KEY ix_security_date (unified_code,plan_date,plan_id),
  KEY ix_plan_date (plan_date,plan_id),
  KEY ix_progress_date (progress_code,plan_date,plan_id),
  CONSTRAINT ck_repurchase_plan_price_upper CHECK (plan_price_upper IS NULL OR plan_price_upper >= 0),
  CONSTRAINT ck_repurchase_plan_price_lower CHECK (plan_price_lower IS NULL OR plan_price_lower >= 0),
  CONSTRAINT ck_repurchase_plan_quantity_upper CHECK (plan_quantity_upper IS NULL OR plan_quantity_upper >= 0),
  CONSTRAINT ck_repurchase_plan_quantity_lower CHECK (plan_quantity_lower IS NULL OR plan_quantity_lower >= 0),
  CONSTRAINT ck_repurchase_plan_amount_upper CHECK (plan_amount_upper IS NULL OR plan_amount_upper >= 0),
  CONSTRAINT ck_repurchase_plan_amount_lower CHECK (plan_amount_lower IS NULL OR plan_amount_lower >= 0),
  CONSTRAINT ck_repurchase_actual_price_upper CHECK (actual_price_upper IS NULL OR actual_price_upper >= 0),
  CONSTRAINT ck_repurchase_actual_price_lower CHECK (actual_price_lower IS NULL OR actual_price_lower >= 0),
  CONSTRAINT ck_repurchase_actual_quantity CHECK (actual_quantity IS NULL OR actual_quantity >= 0),
  CONSTRAINT ck_repurchase_actual_amount CHECK (actual_amount IS NULL OR actual_amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS earnings_forecast (
  record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(100) NULL,
  report_date DATE NOT NULL,
  announcement_date DATE NULL,
  forecast_type VARCHAR(100) NULL,
  forecast_text MEDIUMTEXT NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (record_key),
  KEY ix_security_date (unified_code,report_date,record_key),
  KEY ix_date (report_date,unified_code,record_key),
  KEY ix_type_date (forecast_type,report_date,record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS earnings_quick (
  record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(100) NULL,
  source_id VARCHAR(100) NULL,
  report_date DATE NOT NULL,
  announcement_date DATE NULL,
  source_date DATE NULL,
  profit_basis VARCHAR(100) NULL,
  profit_scope VARCHAR(100) NULL,
  roe_scope VARCHAR(100) NULL,
  net_profit DECIMAL(28,8) NULL,
  roe DECIMAL(28,8) NULL,
  eps DECIMAL(28,8) NULL,
  assets DECIMAL(28,8) NULL,
  equity DECIMAL(28,8) NULL,
  comparison_value DECIMAL(28,8) NULL,
  previous_profit DECIMAL(28,8) NULL,
  previous_roe DECIMAL(28,8) NULL,
  profit_change DECIMAL(28,8) NULL,
  roe_change DECIMAL(28,8) NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (record_key),
  KEY ix_security_date (unified_code,report_date,record_key),
  KEY ix_date (report_date,unified_code,record_key),
  KEY ix_source_report (source_id,report_date,record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS earnings_disclosure (
  record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(100) NULL,
  report_date DATE NOT NULL,
  first_scheduled DATE NULL,
  changed_1 DATE NULL,
  changed_2 DATE NULL,
  changed_3 DATE NULL,
  actual_date DATE NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (record_key),
  KEY ix_security_date (unified_code,report_date,record_key),
  KEY ix_date (report_date,unified_code,record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS earnings_report (
  record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(100) NULL,
  report_date DATE NOT NULL,
  announcement_date DATE NULL,
  roe DECIMAL(28,8) NULL,
  previous_roe DECIMAL(28,8) NULL,
  net_profit DECIMAL(28,8) NULL,
  previous_profit DECIMAL(28,8) NULL,
  revenue DECIMAL(28,8) NULL,
  previous_revenue DECIMAL(28,8) NULL,
  operating_cashflow DECIMAL(28,8) NULL,
  eps DECIMAL(28,8) NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (record_key),
  KEY ix_security_date (unified_code,report_date,record_key),
  KEY ix_date (report_date,unified_code,record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS shareholder_count (
  record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(100) NULL,
  statistics_date DATE NOT NULL,
  holders BIGINT NULL,
  average_float DECIMAL(28,8) NULL,
  holder_change_pct DECIMAL(28,8) NULL,
  top_float_shares DECIMAL(28,8) NULL,
  top_float_pct DECIMAL(28,8) NULL,
  top_shares DECIMAL(28,8) NULL,
  top_pct DECIMAL(28,8) NULL,
  holder_change BIGINT NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (record_key),
  KEY ix_security_date (unified_code,statistics_date,record_key),
  KEY ix_date (statistics_date,unified_code,record_key),
  CONSTRAINT ck_holders CHECK (holders IS NULL OR holders >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE IF NOT EXISTS shareholder_change (
  record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  name VARCHAR(100) NOT NULL,
  data_month DATE NOT NULL,
  change_end DATE NOT NULL,
  change_start VARCHAR(10) NULL,
  announcement_date DATE NULL,
  actor VARCHAR(512) NOT NULL,
  price DECIMAL(28,8) NULL,
  shares_changed DECIMAL(28,8) NULL,
  shares_after DECIMAL(28,8) NULL,
  reason VARCHAR(512) NULL,
  leader VARCHAR(512) NULL,
  position VARCHAR(512) NULL,
  relationship VARCHAR(512) NULL,
  occurrence SMALLINT UNSIGNED NOT NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (record_key),
  KEY ix_month (data_month,unified_code,record_key),
  KEY ix_security_date (unified_code,change_end,record_key),
  KEY ix_date (change_end,unified_code,record_key),
  CONSTRAINT ck_change_month CHECK (DAYOFMONTH(data_month)=1 AND YEAR(data_month)=YEAR(change_end) AND MONTH(data_month)=MONTH(change_end)),
  CONSTRAINT ck_change_dates CHECK (change_start IS NULL OR (change_start REGEXP '^[0-9]{4}-[0-9]{2}(-[0-9]{2})?$' AND change_start<=CAST(change_end AS CHAR) COLLATE utf8mb4_unicode_ci)),
  CONSTRAINT ck_change_shares CHECK (shares_after IS NULL OR shares_after>=0),
  CONSTRAINT ck_change_occurrence CHECK (occurrence BETWEEN 1 AND 9999)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS holder_report (
  report_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  kind VARCHAR(24) NOT NULL,
  unified_code CHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  instrument_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  instrument_name VARCHAR(200) NOT NULL,
  report_date DATE NOT NULL,
  report_type VARCHAR(16) NOT NULL,
  total_quantity DECIMAL(24,4) NULL,
  total_quantity_scale BIGINT NULL,
  total_quantity_decimals SMALLINT NULL,
  total_ratio DECIMAL(9,4) NULL,
  ratio_basis VARCHAR(64) NOT NULL,
  quality_flags SMALLINT NOT NULL,
  member_count SMALLINT NOT NULL,
  exit_count SMALLINT NOT NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (report_key),
  KEY ix_security_date (kind,unified_code,report_date,report_key),
  KEY ix_date (kind,report_date,unified_code,report_key),
  CONSTRAINT ck_holder_report_kind CHECK (kind IN ('top_holders','float_holders','bond_holders')),
  CONSTRAINT ck_holder_report_type CHECK ((report_type='periodic' AND ((total_quantity IS NULL AND total_quantity_scale IS NULL AND total_quantity_decimals IS NULL) OR (total_quantity IS NOT NULL AND total_quantity_scale IS NOT NULL AND total_quantity_decimals IS NOT NULL))) OR (report_type='change_notice' AND total_quantity IS NULL AND total_ratio IS NULL AND total_quantity_scale IS NULL AND total_quantity_decimals IS NULL)),
  CONSTRAINT ck_holder_totals CHECK (quality_flags BETWEEN 0 AND 511 AND (total_quantity IS NULL OR total_quantity>=0) AND (total_ratio IS NULL OR total_ratio BETWEEN 0 AND 100.15)),
  CONSTRAINT ck_holder_counts CHECK (member_count BETWEEN 1 AND 200 AND (kind IN ('top_holders','float_holders') OR member_count<=10) AND exit_count BETWEEN 0 AND 200),
  CONSTRAINT ck_holder_precision CHECK (total_quantity_scale IN (1,10000,100000000) AND total_quantity_decimals BETWEEN 0 AND 4)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS holder_member (
  report_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  member_group VARCHAR(8) NOT NULL,
  seq SMALLINT NOT NULL,
  source_rank SMALLINT NULL,
  holder_name VARCHAR(512) NOT NULL,
  holder_id VARCHAR(80) NULL,
  quantity DECIMAL(24,4) NULL,
  quantity_scale BIGINT NULL,
  quantity_decimals SMALLINT NULL,
  ratio DECIMAL(9,4) NULL,
  change_quantity DECIMAL(24,4) NULL,
  change_label VARCHAR(16) NULL,
  actual_change VARCHAR(128) NULL,
  share_type VARCHAR(128) NULL,
  pledge_ratio DECIMAL(9,4) NULL,
  pledge_status VARCHAR(64) NULL,
  PRIMARY KEY (report_key,member_group,seq),
  CONSTRAINT fk_holder_report FOREIGN KEY (report_key) REFERENCES holder_report(report_key),
  CONSTRAINT ck_holder_member_group CHECK (member_group IN ('current','exited') AND seq BETWEEN 1 AND 200 AND (source_rank IS NULL OR source_rank BETWEEN 1 AND 9999)),
  CONSTRAINT ck_holder_member_values CHECK (quantity>=0 AND (ratio IS NULL OR ratio BETWEEN 0 AND 99999.9999) AND (pledge_ratio IS NULL OR pledge_ratio BETWEEN 0 AND 100)),
  CONSTRAINT ck_holder_member_precision CHECK ((quantity IS NULL AND quantity_scale IS NULL AND quantity_decimals IS NULL) OR (quantity IS NOT NULL AND quantity_scale IS NOT NULL AND quantity_decimals IS NOT NULL AND quantity_scale IN (1,10000,100000000) AND quantity_decimals BETWEEN 0 AND 4))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS restricted_share_unlock (
  record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  group_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unlock_date DATE NOT NULL,
  reason_code VARCHAR(128) NOT NULL,
  name VARCHAR(100) NULL,
  industry VARCHAR(200) NULL,
  reason VARCHAR(1024) NULL,
  shares DECIMAL(28,8) NULL,
  total_shares DECIMAL(28,8) NULL,
  occurrence SMALLINT UNSIGNED NOT NULL,
  detail_status VARCHAR(16) NOT NULL,
  detail_count INT UNSIGNED NOT NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (record_key),
  KEY ix_group (group_key,record_key),
  KEY ix_security_date (unified_code,unlock_date,record_key),
  KEY ix_date (unlock_date,unified_code,record_key),
  CONSTRAINT ck_unlock_security CHECK (unified_code REGEXP '^[0-9]{6}\\.(SH|SZ|BJ)$'),
  CONSTRAINT ck_unlock_shares CHECK (shares>=0 AND total_shares>=0),
  CONSTRAINT ck_unlock_occurrence CHECK (occurrence BETWEEN 1 AND 65535),
  CONSTRAINT ck_unlock_detail CHECK ((detail_status='present' AND detail_count BETWEEN 1 AND 10000) OR (detail_status='source_empty' AND detail_count=0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS restricted_share_unlock_detail (
  record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  group_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  unlock_date DATE NOT NULL,
  reason_code VARCHAR(128) NOT NULL,
  holder VARCHAR(512) NOT NULL,
  reason VARCHAR(1024) NULL,
  shares DECIMAL(28,8) NULL,
  occurrence SMALLINT UNSIGNED NOT NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (group_key,record_key),
  KEY ix_date (unlock_date,unified_code,record_key),
  CONSTRAINT ck_unlock_member_security CHECK (unified_code REGEXP '^[0-9]{6}\\.(SH|SZ|BJ)$'),
  CONSTRAINT ck_unlock_member_shares CHECK (shares>=0),
  CONSTRAINT ck_unlock_member_occurrence CHECK (occurrence BETWEEN 1 AND 65535),
  CONSTRAINT ck_unlock_holder CHECK (CHAR_LENGTH(TRIM(holder))>0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS restricted_share_unlock_industry (
  unlock_month DATE NOT NULL,
  industry VARCHAR(200) NOT NULL,
  basis_date DATE NOT NULL,
  shares DECIMAL(28,8) NULL,
  unlock_value DECIMAL(28,8) NULL,
  market_cap DECIMAL(28,8) NULL,
  negotiable_cap DECIMAL(28,8) NULL,
  market_percent DECIMAL(28,8) NULL,
  float_percent DECIMAL(28,8) NULL,
  content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  version_observed_at DATETIME(6) NOT NULL,
  PRIMARY KEY (unlock_month,industry),
  KEY ix_industry_month (industry,unlock_month),
  CONSTRAINT ck_unlock_industry_month CHECK (DAY(unlock_month)=1),
  CONSTRAINT ck_unlock_industry_name CHECK (CHAR_LENGTH(TRIM(industry))>0),
  CONSTRAINT ck_unlock_industry_values CHECK (shares>=0 AND unlock_value>=0 AND market_cap>=0 AND negotiable_cap>=0 AND market_percent>=0 AND float_percent>=0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS capital_funding (
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    section VARCHAR(20) NOT NULL,
    event_date DATE NULL,
    issue_type VARCHAR(100) NULL,
    issue_start DATE NULL,
    net_amount DECIMAL(28,6) NULL,
    balance_date DATE NULL,
    balance_amount DECIMAL(28,6) NULL,
    usage_ratio DECIMAL(28,6) NULL,
    in_window BOOLEAN NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    KEY idx_funding_date (section,event_date,unified_code,record_key),
    KEY idx_funding_security (section,unified_code,event_date,record_key),
    KEY idx_funding_window (unified_code,in_window,record_key),
    CONSTRAINT ck_funding_window CHECK (in_window IN (0,1)),
    CONSTRAINT ck_funding_section CHECK (section IN ('raise_'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS capital_project (
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    section VARCHAR(20) NOT NULL,
    event_date DATE NULL,
    project_name VARCHAR(1000) NULL,
    committed_amount DECIMAL(28,6) NULL,
    invested_amount DECIMAL(28,6) NULL,
    duration_years DECIMAL(28,6) NULL,
    return_ratio DECIMAL(28,6) NULL,
    predicted_profit DECIMAL(28,6) NULL,
    description TEXT NULL,
    in_window BOOLEAN NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    KEY idx_project_date (section,event_date,unified_code,record_key),
    KEY idx_project_security (section,unified_code,event_date,record_key),
    KEY idx_project_window (unified_code,in_window,record_key),
    CONSTRAINT ck_project_window CHECK (in_window IN (0,1)),
    CONSTRAINT ck_project_section CHECK (section IN ('progress'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS capital_transaction (
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    section VARCHAR(20) NOT NULL,
    event_date DATE NULL,
    target TEXT NULL,
    buyer TEXT NULL,
    seller TEXT NULL,
    counterparty TEXT NULL,
    amount DECIMAL(28,6) NULL,
    currency VARCHAR(40) NULL,
    status VARCHAR(100) NULL,
    transfer_ratio DECIMAL(28,6) NULL,
    payment VARCHAR(200) NULL,
    method TEXT NULL,
    relationship TEXT NULL,
    description TEXT NULL,
    impact TEXT NULL,
    in_window BOOLEAN NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    KEY idx_transaction_date (section,event_date,unified_code,record_key),
    KEY idx_transaction_security (section,unified_code,event_date,record_key),
    KEY idx_transaction_window (unified_code,in_window,record_key),
    CONSTRAINT ck_transaction_window CHECK (in_window IN (0,1)),
    CONSTRAINT ck_transaction_section CHECK (section IN ('asset','transfer','connect'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS capital_equity_summary (
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    section VARCHAR(20) NOT NULL,
    event_date DATE NULL,
    investment_type VARCHAR(200) NULL,
    holding_count INT NULL,
    initial_amount DECIMAL(28,6) NULL,
    final_amount DECIMAL(28,6) NULL,
    profit DECIMAL(28,6) NULL,
    profit_estimated BOOLEAN NOT NULL,
    impact VARCHAR(1000) NULL,
    in_window BOOLEAN NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    KEY idx_equity_summary_date (section,event_date,unified_code,record_key),
    KEY idx_equity_summary_security (section,unified_code,event_date,record_key),
    KEY idx_equity_summary_window (unified_code,in_window,record_key),
    CONSTRAINT ck_equity_summary_window CHECK (in_window IN (0,1)),
    CONSTRAINT ck_equity_summary_section CHECK (section IN ('invest'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS capital_equity_position (
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    section VARCHAR(20) NOT NULL,
    event_date DATE NULL,
    category VARCHAR(100) NULL,
    target VARCHAR(1000) NULL,
    investment_type VARCHAR(200) NULL,
    quantity DECIMAL(28,6) NULL,
    quantity_estimated BOOLEAN NOT NULL,
    ratio DECIMAL(28,6) NULL,
    profit DECIMAL(28,6) NULL,
    in_window BOOLEAN NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    KEY idx_equity_position_date (section,event_date,unified_code,record_key),
    KEY idx_equity_position_security (section,unified_code,event_date,record_key),
    KEY idx_equity_position_window (unified_code,in_window,record_key),
    CONSTRAINT ck_equity_position_window CHECK (in_window IN (0,1)),
    CONSTRAINT ck_equity_position_section CHECK (section IN ('invest'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS capital_ipo (
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    section VARCHAR(20) NOT NULL,
    event_date DATE NULL,
    target VARCHAR(1000) NULL,
    ratio DECIMAL(28,6) NULL,
    initial_amount DECIMAL(28,6) NULL,
    status VARCHAR(200) NULL,
    industry VARCHAR(500) NULL,
    eps DECIMAL(28,6) NULL,
    in_window BOOLEAN NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    KEY idx_ipo_date (section,event_date,unified_code,record_key),
    KEY idx_ipo_security (section,unified_code,event_date,record_key),
    KEY idx_ipo_window (unified_code,in_window,record_key),
    CONSTRAINT ck_ipo_window CHECK (in_window IN (0,1)),
    CONSTRAINT ck_ipo_section CHECK (section IN ('ipo'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS capital_encumbrance (
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    section VARCHAR(20) NOT NULL,
    event_date DATE NULL,
    holder VARCHAR(1000) NULL,
    institution TEXT NULL,
    quantity DECIMAL(28,6) NULL,
    start_date DATE NULL,
    end_date DATE NULL,
    description TEXT NULL,
    in_window BOOLEAN NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    KEY idx_encumbrance_date (section,event_date,unified_code,record_key),
    KEY idx_encumbrance_security (section,unified_code,event_date,record_key),
    KEY idx_encumbrance_window (unified_code,in_window,record_key),
    CONSTRAINT ck_encumbrance_window CHECK (in_window IN (0,1)),
    CONSTRAINT ck_encumbrance_section CHECK (section IN ('pledge','freeze'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS capital_release (
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    section VARCHAR(20) NOT NULL,
    event_date DATE NULL,
    parent_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    quantity DECIMAL(28,6) NULL,
    actual_date DATE NULL,
    description TEXT NULL,
    in_window BOOLEAN NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (record_key),
    KEY idx_release_date (section,event_date,unified_code,record_key),
    KEY idx_release_security (section,unified_code,event_date,record_key),
    KEY idx_release_window (unified_code,in_window,record_key),
    CONSTRAINT ck_release_window CHECK (in_window IN (0,1)),
    CONSTRAINT ck_release_section CHECK (section IN ('pledge','freeze')),
    KEY idx_capital_release_parent (parent_key,record_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS theme_daily (
    business_date DATE NOT NULL,
    theme_id VARCHAR(65) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_theme_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    concept_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    name VARCHAR(128) NOT NULL,
    parent_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    new_flag INT UNSIGNED NOT NULL,
    rank_no INT NULL,
    display_order INT NOT NULL,
    hot_score BIGINT UNSIGNED NULL,
    change_rate DOUBLE NOT NULL,
    limit_up_count INT UNSIGNED NOT NULL,
    observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (business_date,theme_id),
    KEY idx_theme_daily_history (theme_id,business_date),
    KEY idx_theme_daily_rank (business_date,rank_no,theme_id),
    CONSTRAINT ck_theme_daily_child CHECK ((parent_id IS NULL AND concept_id IS NULL AND hot_score IS NOT NULL) OR (parent_id IS NOT NULL AND concept_id IS NOT NULL AND hot_score IS NULL AND rank_no IS NULL))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS theme_detail (
    theme_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(128) NOT NULL,
    brief MEDIUMTEXT NOT NULL,
    introduction MEDIUMTEXT NOT NULL,
    source_created_at DATETIME(6) NULL,
    source_updated_at DATETIME(6) NULL,
    observed_at DATETIME(6) NOT NULL,
    content_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (theme_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS theme_category (
    theme_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    category_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    parent_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    name VARCHAR(128) NOT NULL,
    `order` INT NOT NULL,
    plate_code VARCHAR(32) NOT NULL,
    first_shelved_at DATETIME(6) NULL,
    updated_at DATETIME(6) NULL,
    is_new BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (theme_id,category_id),
    KEY idx_theme_category_parent (theme_id,parent_id,`order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS theme_stock (
    theme_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_stock_id CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(128) NOT NULL,
    PRIMARY KEY (theme_id,unified_code),
    UNIQUE KEY uq_theme_stock_source (theme_id,source_stock_id),
    KEY idx_theme_stock_security (unified_code,theme_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS theme_stock_reason (
    theme_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    relation_id CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    category_id VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    reason MEDIUMTEXT NOT NULL,
    first_shelved_at DATETIME(6) NULL,
    updated_at DATETIME(6) NULL,
    is_new BIGINT UNSIGNED NOT NULL,
    is_hot BIGINT UNSIGNED NOT NULL,
    source_is_zz BIGINT UNSIGNED NOT NULL,
    occurrences INT UNSIGNED NOT NULL,
    PRIMARY KEY (theme_id,relation_id),
    KEY idx_theme_reason_category (theme_id,category_id,relation_id),
    CONSTRAINT ck_theme_reason_occurrences CHECK (occurrences BETWEEN 1 AND 50000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS yuanhang_daily_price (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    open DECIMAL(28,10) NOT NULL,
    high DECIMAL(28,10) NOT NULL,
    low DECIMAL(28,10) NOT NULL,
    close DECIMAL(28,10) NOT NULL,
    volume_shares DECIMAL(28,10) NULL,
    amount_yuan DECIMAL(28,10) NULL,
    PRIMARY KEY (unified_code,trade_date),
    KEY idx_yuanhang_price_date (trade_date,unified_code),
    CONSTRAINT ck_yuanhang_price_values CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0 AND volume_shares >= 0 AND (amount_yuan IS NULL OR amount_yuan >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS yuanhang_price_year (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    quote_year SMALLINT UNSIGNED NOT NULL,
    native_market CHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_count INT UNSIGNED NOT NULL,
    row_count INT UNSIGNED NOT NULL,
    first_date DATE NULL,
    last_date DATE NULL,
    key_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    contract_version SMALLINT UNSIGNED NOT NULL,
    verified_through DATE NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (unified_code,quote_year),
    CONSTRAINT ck_yuanhang_year_count CHECK (quote_year BETWEEN 1900 AND 2100 AND source_count = row_count AND row_count <= 366),
    CONSTRAINT ck_yuanhang_year_dates CHECK ((row_count = 0 AND first_date IS NULL AND last_date IS NULL) OR (row_count > 0 AND first_date IS NOT NULL AND last_date IS NOT NULL AND first_date <= last_date AND YEAR(first_date) = quote_year AND YEAR(last_date) = quote_year))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS yuanhang_corporate_action (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    ex_date DATE NOT NULL,
    event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    bonus_ratio DECIMAL(28,10) NOT NULL,
    transfer_ratio DECIMAL(28,10) NOT NULL,
    rights_ratio DECIMAL(28,10) NOT NULL,
    rights_price DECIMAL(28,10) NOT NULL,
    cash_per_share DECIMAL(28,10) NOT NULL,
    PRIMARY KEY (unified_code,ex_date,event_key),
    KEY idx_yuanhang_action_date (ex_date,unified_code),
    CONSTRAINT ck_yuanhang_action_values CHECK ((bonus_ratio >= 0 OR (bonus_ratio > -1 AND transfer_ratio = 0 AND rights_ratio = 0 AND rights_price = 0 AND cash_per_share = 0)) AND transfer_ratio >= 0 AND rights_ratio >= 0 AND rights_price >= 0 AND cash_per_share >= 0 AND (rights_ratio = 0 OR rights_price > 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS yuanhang_capital (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    capital_kind VARCHAR(11) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    effective_date DATE NOT NULL,
    shares DECIMAL(28,10) NULL,
    PRIMARY KEY (unified_code,capital_kind,effective_date),
    CONSTRAINT ck_yuanhang_capital_kind CHECK (capital_kind IN ('total','circulating','free_float')),
    CONSTRAINT ck_yuanhang_capital_shares CHECK ((shares IS NOT NULL AND shares > 0) OR (shares IS NULL AND capital_kind = 'circulating'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS yuanhang_series_proof (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    series_kind VARCHAR(7) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    native_market CHAR(4) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_count INT UNSIGNED NOT NULL,
    row_count INT UNSIGNED NOT NULL,
    first_date DATE NULL,
    last_date DATE NULL,
    key_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    contract_version SMALLINT UNSIGNED NOT NULL,
    response_group CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    total_count INT UNSIGNED NOT NULL,
    circulating_count INT UNSIGNED NOT NULL,
    free_float_count INT UNSIGNED NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (unified_code,series_kind),
    CONSTRAINT ck_yuanhang_series_kind CHECK (series_kind IN ('actions','capital')),
    CONSTRAINT ck_yuanhang_series_count CHECK (source_count = row_count AND ((series_kind = 'actions' AND row_count <= 2000 AND total_count = 0 AND circulating_count = 0 AND free_float_count = 0) OR (series_kind = 'capital' AND row_count <= 30000 AND total_count > 0 AND circulating_count > 0 AND free_float_count > 0 AND total_count + circulating_count + free_float_count = row_count))),
    CONSTRAINT ck_yuanhang_series_dates CHECK ((row_count = 0 AND first_date IS NULL AND last_date IS NULL) OR (row_count > 0 AND first_date IS NOT NULL AND last_date IS NOT NULL AND first_date <= last_date))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS yuanhang_limit_pool (

    trade_date DATE NOT NULL,

    pool_type VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

    source_total INT UNSIGNED NOT NULL,

    filter_text VARCHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

    key_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

    content_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

    contract_version SMALLINT UNSIGNED NOT NULL,

    observed_at DATETIME(6) NOT NULL,

    PRIMARY KEY (trade_date,pool_type),

    KEY idx_yuanhang_limit_pool_kind (pool_type,trade_date),

    CONSTRAINT ck_yuanhang_limit_pool_count CHECK (source_total <= 10000),

    CONSTRAINT ck_yuanhang_limit_pool_filter CHECK (filter_text = 'HS,GEM2STAR')

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;



CREATE TABLE IF NOT EXISTS yuanhang_limit_member (

    trade_date DATE NOT NULL,

    pool_type VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_market_id SMALLINT UNSIGNED NULL,
    identity_basis VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

    change_rate DECIMAL(48,24) NULL,

    latest DECIMAL(48,24) NULL,

    turnover_rate DECIMAL(48,24) NULL,

    currency_value DECIMAL(48,24) NULL,

    sum_market_value DECIMAL(48,24) NULL,

    rise_rate DECIMAL(48,24) NULL,

    turnover DECIMAL(48,24) NULL,

    order_amount DECIMAL(48,24) NULL,

    order_volume DECIMAL(48,24) NULL,

    limit_up_suc_rate DECIMAL(48,24) NULL,

    open_num INT UNSIGNED NULL,

    high_days_value INT UNSIGNED NULL,

    is_new INT UNSIGNED NULL,

    is_again_limit INT UNSIGNED NULL,

    name VARCHAR(80) NOT NULL,

    market_type VARCHAR(32) NOT NULL,

    reason_type TEXT NULL,

    limit_up_type VARCHAR(128) NULL,

    limit_down_type VARCHAR(128) NULL,

    high_days VARCHAR(80) NULL,

    change_tag VARCHAR(80) NULL,

    top_concept VARCHAR(1024) NULL,

    first_limit_up_time DATETIME NULL,

    last_limit_up_time DATETIME NULL,

    first_limit_down_time DATETIME NULL,

    last_limit_down_time DATETIME NULL,

    PRIMARY KEY (trade_date,pool_type,unified_code),

    KEY idx_yuanhang_limit_member_security (unified_code,trade_date,pool_type),
    KEY ix_yuanhang_member_date_code (trade_date,unified_code),

    CONSTRAINT ck_yuanhang_limit_member_probability CHECK (limit_up_suc_rate IS NULL OR limit_up_suc_rate BETWEEN 0 AND 1)

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;



CREATE TABLE IF NOT EXISTS yuanhang_limit_reason (

    trade_date DATE NOT NULL,

    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

    name VARCHAR(80) NULL,

    reason_text TEXT NULL,

    reason_kind TEXT NULL,

    availability VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

    content_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,

    observed_at DATETIME(6) NOT NULL,

    PRIMARY KEY (trade_date,unified_code),

    KEY idx_yuanhang_limit_reason_security (unified_code,trade_date),
    KEY ix_yuanhang_reason_planning (trade_date,unified_code,observed_at,content_sha256),

    CONSTRAINT ck_yuanhang_limit_reason_availability CHECK (availability IN ('available','no_content'))

) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS hot_list_day (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    list_date DATE NOT NULL,
    directory_listed BOOLEAN NOT NULL,
    detail_status VARCHAR(20) NOT NULL,
    reason_count INT NOT NULL,
    seat_count INT NOT NULL,
    auxiliary JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NULL,
    PRIMARY KEY (unified_code,list_date),
    KEY ix_date (list_date,unified_code),
    CONSTRAINT ck_hot_list_listed CHECK (directory_listed IN (0,1)),
    CONSTRAINT ck_hot_list_status CHECK (detail_status IN ('pending','present','partial','source_empty')),
    CONSTRAINT ck_hot_list_counts CHECK (reason_count >= 0 AND reason_count <= 1000 AND seat_count >= 0 AND seat_count <= 10000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS hot_list_reason (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    list_date DATE NOT NULL,
    seq INT NOT NULL,
    reason_code VARCHAR(32) NOT NULL,
    reason VARCHAR(1000) NOT NULL,
    volume DECIMAL(28,8) NULL,
    turnover DECIMAL(28,8) NULL,
    close_price DECIMAL(28,8) NULL,
    change_pct DECIMAL(20,8) NULL,
    PRIMARY KEY (unified_code,list_date,seq),
    KEY ix_reason (reason_code,list_date,unified_code),
    CONSTRAINT ck_hot_reason_seq CHECK (seq >= 1 AND seq <= 1000),
    CONSTRAINT ck_hot_reason_positive CHECK ((volume IS NULL OR volume >= 0) AND (turnover IS NULL OR turnover >= 0) AND (close_price IS NULL OR close_price >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS hot_list_seat (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    list_date DATE NOT NULL,
    seq INT NOT NULL,
    reason_code VARCHAR(32) NOT NULL,
    side CHAR(1) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    seat_rank INT NOT NULL,
    seat_name VARCHAR(256) NOT NULL,
    buy_amount DECIMAL(28,8) NULL,
    sell_amount DECIMAL(28,8) NULL,
    net_amount DECIMAL(28,8) NULL,
    extension JSON NOT NULL,
    PRIMARY KEY (unified_code,list_date,seq),
    KEY ix_seat_name (seat_name,list_date,unified_code),
    CONSTRAINT ck_hot_seat_seq CHECK (seq >= 1 AND seq <= 10000),
    CONSTRAINT ck_hot_seat_rank CHECK (seat_rank >= 1 AND seat_rank <= 1000),
    CONSTRAINT ck_hot_seat_side CHECK (side IN ('B','S')),
    CONSTRAINT ck_hot_seat_positive CHECK ((buy_amount IS NULL OR buy_amount >= 0) AND (sell_amount IS NULL OR sell_amount >= 0))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;
