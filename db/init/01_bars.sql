CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

CREATE TABLE IF NOT EXISTS bars (
    symbol      TEXT        NOT NULL,
    timestamp   TIMESTAMPTZ NOT NULL,
    open        FLOAT8      NOT NULL,
    high        FLOAT8      NOT NULL,
    low         FLOAT8      NOT NULL,
    close       FLOAT8      NOT NULL,
    volume      BIGINT      NOT NULL,
    PRIMARY KEY (symbol, timestamp)
);

SELECT create_hypertable('bars', 'timestamp'::name, if_not_exists => TRUE);