-- Initial business schema only; application startup never executes DDL.
-- DATETIME values use Asia/Shanghai wall-clock time (UTC+08:00).
-- Fixed source ownership is declared in contracts/business_schema.py; news retains per-row source.
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
