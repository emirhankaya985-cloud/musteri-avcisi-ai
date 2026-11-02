-- Additive, private run-level metrics: one row per GitHub run ID.
-- No customer address or recipient identifiers are stored in this table.
CREATE TABLE IF NOT EXISTS owner_scan_run_metrics (
    scan_run_id text PRIMARY KEY CHECK (scan_run_id ~ '^[0-9]{6,24}$'),
    report_day date NOT NULL,
    scanned_count integer NOT NULL CHECK (scanned_count >= 0),
    new_registered integer NOT NULL CHECK (new_registered >= 0),
    new_addresses integer NOT NULL CHECK (new_addresses >= 0),
    new_mx integer NOT NULL CHECK (new_mx >= 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (new_mx <= new_addresses),
    CHECK (new_addresses <= scanned_count),
    CHECK (new_registered <= scanned_count)
);
CREATE INDEX IF NOT EXISTS owner_scan_run_metrics_day_idx ON owner_scan_run_metrics(report_day);
-- Reversal: stop writing new metrics, keep historical rows; dropping is NOT required.
