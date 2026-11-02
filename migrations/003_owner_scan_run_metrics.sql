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

-- Gmail events are immutable fingerprints of verified inbound messages.
-- No recipient, sender, body, SMTP credentials or provider message IDs.
CREATE TABLE IF NOT EXISTS owner_mail_notice_metrics (
    notice_digest text PRIMARY KEY CHECK (notice_digest ~ '^[0-9a-f]{64}$'),
    report_day date NOT NULL,
    kind text NOT NULL CHECK (kind IN ('failed','delayed','reply')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS owner_mail_notice_metrics_day_idx ON owner_mail_notice_metrics(report_day);
CREATE TABLE IF NOT EXISTS owner_mail_watch_runs (
    watch_run_id text PRIMARY KEY CHECK (watch_run_id ~ '^[0-9]{6,24}$'),
    report_day date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS owner_mail_watch_runs_day_idx ON owner_mail_watch_runs(report_day);
