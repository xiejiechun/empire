-- Initial business schema only; application startup never executes DDL.
-- source separates internal datasets; each source keeps one current stock list.
CREATE TABLE IF NOT EXISTS stock (
    source VARCHAR(80) NOT NULL,
    node VARCHAR(40) NOT NULL DEFAULT 'hs_a',
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    code CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    name VARCHAR(100) NOT NULL,
    market CHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    source_symbol CHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    generation CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    started_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, unified_code),
    UNIQUE KEY uq_stock_source_symbol (source, source_symbol),
    INDEX ix_stock_generation (source, started_at, generation)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- One row per calendar date, including explicit non-trading days; no raw response storage.
CREATE TABLE IF NOT EXISTS trade_calendar (
    source VARCHAR(80) NOT NULL,
    trade_date DATE NOT NULL,
    is_trade BOOLEAN NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, trade_date)
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
    last_seen_at DATETIME(6) NOT NULL,
    PRIMARY KEY (source, news_id),
    INDEX ix_news_published (source, published_at, news_id),
    INDEX ix_news_important (source, is_important, published_at, news_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
