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

CREATE TABLE IF NOT EXISTS stock_market_day (
    kind VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    source_code VARCHAR(6) CHARACTER SET ascii COLLATE ascii_bin NULL,
    listing_date DATE NOT NULL,
    listing_source VARCHAR(16) NOT NULL,
    market_start DATE NOT NULL,
    identity_extra JSON NOT NULL,
    product_extra JSON NOT NULL,
    source_metadata JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    contract_version SMALLINT UNSIGNED NOT NULL,
    point_count INT UNSIGNED NOT NULL,
    key_set_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (kind, unified_code, trade_date),
    KEY ix_market_date (kind, trade_date, unified_code),
    CONSTRAINT ck_market_kind CHECK (kind IN ('trend','auction','volume','trades','entrust','large_order','quote')),
    CONSTRAINT ck_market_count CHECK (point_count BETWEEN 1 AND 100000),
    CONSTRAINT ck_market_contract CHECK (contract_version=2),
    CONSTRAINT ck_market_extra CHECK (JSON_STORAGE_SIZE(identity_extra)<=16384 AND JSON_STORAGE_SIZE(product_extra)<=16384 AND JSON_STORAGE_SIZE(source_metadata)<=16384)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS stock_intraday_trend (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    seq INT UNSIGNED NOT NULL,
    source_time TIME(0) NOT NULL,
    float_mask SMALLINT UNSIGNED NOT NULL,
    price DECIMAL(30,12) NOT NULL,
    average_price DECIMAL(30,12) NOT NULL,
    source_volume DECIMAL(30,12) NOT NULL,
    source_flag DECIMAL(30,12) NOT NULL,
    PRIMARY KEY (unified_code, trade_date, source_time),
    KEY ix_minute_date (trade_date, source_time, unified_code),
    CONSTRAINT ck_trend_seq CHECK (seq<241),
    CONSTRAINT ck_trend_mask CHECK (float_mask<256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS stock_opening_auction (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    seq INT UNSIGNED NOT NULL,
    source_time TIME(0) NOT NULL,
    float_mask SMALLINT UNSIGNED NOT NULL,
    price DECIMAL(30,12) NOT NULL,
    source_flag DECIMAL(30,12) NOT NULL,
    source_volume DECIMAL(30,12) NOT NULL,
    PRIMARY KEY (unified_code, trade_date, seq),
    CONSTRAINT ck_auction_seq CHECK (seq<100000),
    CONSTRAINT ck_auction_mask CHECK (float_mask<64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS stock_minute_volume (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    seq INT UNSIGNED NOT NULL,
    source_time TIME(0) NOT NULL,
    float_mask SMALLINT UNSIGNED NOT NULL,
    source_volume DECIMAL(30,12) NOT NULL,
    source_turnover DECIMAL(30,12) NOT NULL,
    source_flag DECIMAL(30,12) NOT NULL,
    PRIMARY KEY (unified_code, trade_date, source_time),
    KEY ix_minute_date (trade_date, source_time, unified_code),
    CONSTRAINT ck_volume_seq CHECK (seq<241),
    CONSTRAINT ck_volume_mask CHECK (float_mask<64)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS stock_intraday_trade_block (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    block_seq INT UNSIGNED NOT NULL,
    first_seq INT UNSIGNED NOT NULL,
    last_seq INT UNSIGNED NOT NULL,
    first_time TIME(0) NOT NULL,
    last_time TIME(0) NOT NULL,
    point_count SMALLINT UNSIGNED NOT NULL,
    format_version SMALLINT UNSIGNED NOT NULL,
    body BLOB NOT NULL,
    block_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (unified_code, trade_date, block_seq),
    KEY ix_trade_time (unified_code, trade_date, first_time, block_seq),
    CONSTRAINT ck_trade_block CHECK (format_version=1 AND point_count BETWEEN 1 AND 200 AND first_seq=block_seq*200 AND last_seq=first_seq+point_count-1 AND last_time>=first_time AND OCTET_LENGTH(body)<=24576)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS stock_minute_entrust (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    seq INT UNSIGNED NOT NULL,
    source_time TIME(0) NOT NULL,
    float_mask SMALLINT UNSIGNED NOT NULL,
    buy_volume DECIMAL(30,12) NOT NULL,
    sell_volume DECIMAL(30,12) NOT NULL,
    buy_turnover DECIMAL(30,12) NOT NULL,
    sell_turnover DECIMAL(30,12) NOT NULL,
    PRIMARY KEY (unified_code, trade_date, source_time),
    KEY ix_minute_date (trade_date, source_time, unified_code),
    CONSTRAINT ck_entrust_seq CHECK (seq<241),
    CONSTRAINT ck_entrust_mask CHECK (float_mask<256)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS stock_large_order_trend (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    seq INT UNSIGNED NOT NULL,
    source_time TIME(0) NOT NULL,
    float_mask SMALLINT UNSIGNED NOT NULL,
    net_amount DECIMAL(30,12) NOT NULL,
    PRIMARY KEY (unified_code, trade_date, source_time),
    KEY ix_minute_date (trade_date, source_time, unified_code),
    CONSTRAINT ck_large_order_seq CHECK (seq<241),
    CONSTRAINT ck_large_order_mask CHECK (float_mask<4)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS stock_daily_quote (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    float_mask BIGINT UNSIGNED NOT NULL,
    present_mask BIGINT UNSIGNED NOT NULL,
    `time` DECIMAL(30,12) NULL,
    `up_px` DECIMAL(30,12) NULL,
    `avg_px` DECIMAL(30,12) NULL,
    `low_px` DECIMAL(30,12) NULL,
    `down_px` DECIMAL(30,12) NULL,
    `high_px` DECIMAL(30,12) NULL,
    `last_px` DECIMAL(30,12) NULL,
    `open_px` DECIMAL(30,12) NULL,
    `pe_rate` DECIMAL(30,12) NULL,
    `jtPeRate` DECIMAL(30,12) NULL,
    `TTMPeRate` DECIMAL(30,12) NULL,
    `amount_in` DECIMAL(30,12) NULL,
    `amplitude` DECIMAL(30,12) NULL,
    `px_change` DECIMAL(30,12) NULL,
    `vol_ratio` DECIMAL(30,12) NULL,
    `amount_out` DECIMAL(30,12) NULL,
    `dyn_pb_rate` DECIMAL(30,12) NULL,
    `phcj_volume` DECIMAL(30,12) NULL,
    `entrust_rate` DECIMAL(30,12) NULL,
    `market_value` DECIMAL(30,12) NULL,
    `total_amount` DECIMAL(30,12) NULL,
    `total_shares` DECIMAL(30,12) NULL,
    `phcj_turnover` DECIMAL(30,12) NULL,
    `px_change_rate` DECIMAL(30,12) NULL,
    `total_turnover` DECIMAL(30,12) NULL,
    `turnover_ratio` DECIMAL(30,12) NULL,
    `circulation_value` DECIMAL(30,12) NULL,
    `circulation_amount` DECIMAL(30,12) NULL,
    `actualcirculation_value` DECIMAL(30,12) NULL,
    PRIMARY KEY (unified_code, trade_date),
    KEY ix_quote_date (trade_date, unified_code),
    CONSTRAINT ck_quote_mask CHECK (float_mask<288230376151711744 AND present_mask<536870912)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS stock_daily_quote_level (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    side CHAR(1) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    level TINYINT UNSIGNED NOT NULL,
    price DECIMAL(30,12) NOT NULL,
    source_volume DECIMAL(30,12) NOT NULL,
    float_mask TINYINT UNSIGNED NOT NULL,
    PRIMARY KEY (unified_code, trade_date, side, level),
    CONSTRAINT ck_quote_level CHECK (side IN ('b','s') AND level BETWEEN 1 AND 10),
    CONSTRAINT ck_quote_level_value CHECK (price>=0 AND source_volume>=0 AND float_mask<16)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

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
  CONSTRAINT ck_holder_totals CHECK (quality_flags BETWEEN 0 AND 255 AND (total_quantity IS NULL OR total_quantity>=0) AND (total_ratio IS NULL OR total_ratio BETWEEN 0 AND 100.15)),
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
  CONSTRAINT ck_holder_member_values CHECK (quantity>=0 AND (ratio IS NULL OR ratio BETWEEN 0 AND 100) AND (pledge_ratio IS NULL OR pledge_ratio BETWEEN 0 AND 100)),
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
