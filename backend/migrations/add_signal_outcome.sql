ALTER TABLE signals ADD COLUMN outcome VARCHAR(16) NOT NULL DEFAULT 'PENDING';
ALTER TABLE signals ADD COLUMN outcome_at TIMESTAMPTZ;
ALTER TABLE signals ADD COLUMN outcome_pnl_pct NUMERIC(10, 4);
ALTER TABLE signals ADD COLUMN outcome_duration_minutes INTEGER;
CREATE INDEX ix_signal_outcome ON signals (outcome) WHERE outcome = 'PENDING';
