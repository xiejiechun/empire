-- Historical input for explicit typed market migration only.
CREATE TABLE IF NOT EXISTS stock_market_day (
    kind VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    unified_code VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    trade_date DATE NOT NULL,
    payload JSON NOT NULL,
    content_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    version_observed_at DATETIME(6) NOT NULL,
    PRIMARY KEY (kind, unified_code, trade_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;
