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

CREATE TABLE IF NOT EXISTS stock_intraday (
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (unified_code, trade_date)
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
CREATE TABLE IF NOT EXISTS suspension_source_date (
    source_date DATE NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    suspended_at DATETIME(6) NOT NULL,
    resume_key DATETIME(6) NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (source_date, unified_code, suspended_at, resume_key, record_key),
    INDEX ix_suspension_identity (unified_code, suspended_at, resume_key, record_key, source_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
