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
