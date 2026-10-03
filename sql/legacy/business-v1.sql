-- Initial business schema only; application startup never executes DDL.
-- DATETIME values use Asia/Shanghai wall-clock time (UTC+08:00).
-- source separates internal datasets; each source keeps one current stock list.
CREATE TABLE IF NOT EXISTS industry (
    source VARCHAR(80) NOT NULL,
    industry_code CHAR(6) NOT NULL,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (source, industry_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS industry_member (
    source VARCHAR(80) NOT NULL,
    industry_code CHAR(6) NOT NULL,
    market CHAR(2) NOT NULL,
    code CHAR(6) NOT NULL,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (source, industry_code, market, code),
    KEY ix_industry_security (source, code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stock (
    source VARCHAR(80) NOT NULL,
    node VARCHAR(40) NOT NULL DEFAULT 'hs_a',
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_symbol CHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    PRIMARY KEY (source, unified_code),
    UNIQUE KEY uq_stock_source_symbol (source, source_symbol)
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
    source VARCHAR(80) NOT NULL,
    trade_date DATE NOT NULL,
    is_trade BOOLEAN NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- Source records with different resumption times or descriptions coexist.
CREATE TABLE IF NOT EXISTS suspension_event (
    source VARCHAR(80) NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    suspended_at DATETIME(6) NOT NULL,
    resumed_at DATETIME(6) NULL,
    resume_key DATETIME(6) NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_dates JSON NULL,
    suspension_type VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_note VARCHAR(100) NOT NULL,
    reason VARCHAR(500) NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, market, code, suspended_at, resume_key, record_key),
    CONSTRAINT ck_suspension_resume_key CHECK (resume_key=COALESCE(resumed_at,'1000-01-01 00:00:00')),
    INDEX ix_suspension_start (source, suspended_at, market, code),
    INDEX ix_suspension_resume (source, resumed_at, market, code)
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
    source VARCHAR(80) NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    event_date DATE NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, record_key),
    INDEX ix_security_date (source, market, code, event_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS additional_issue (
    source VARCHAR(80) NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    event_date DATE NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, record_key),
    INDEX ix_security_date (source, market, code, event_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rights_issue (
    source VARCHAR(80) NOT NULL,
    record_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    event_date DATE NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, record_key),
    INDEX ix_security_date (source, market, code, event_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stock_intraday (
    source VARCHAR(80) NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, market, code, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS income_statement (
    source VARCHAR(80) NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    report_date DATE NOT NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, market, code, report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS balance_statement (
    source VARCHAR(80) NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    report_date DATE NOT NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, market, code, report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

CREATE TABLE IF NOT EXISTS cashflow_statement (
    source VARCHAR(80) NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    report_date DATE NOT NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, market, code, report_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
