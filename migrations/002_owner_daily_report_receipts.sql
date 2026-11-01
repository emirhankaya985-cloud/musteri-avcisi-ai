-- Zero-cost, additive owner-only reporting receipt. No CRM/mail state change.
-- Apply once on the existing private Müşteri Avcısı PostgreSQL database.
CREATE TABLE IF NOT EXISTS public.owner_daily_report_receipts (
    report_day text PRIMARY KEY,
    state text NOT NULL CHECK (state IN ('reserved','confirmed','uncertain')),
    telegram_message_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- Rollback plan: stop the daily-report workflow; retain the receipt table.
-- DROP TABLE only after explicit owner approval and a verified backup.
