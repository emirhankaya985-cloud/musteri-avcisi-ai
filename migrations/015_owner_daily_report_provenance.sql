ALTER TABLE public.owner_daily_report_receipts
    ADD COLUMN IF NOT EXISTS github_run_id text,
    ADD COLUMN IF NOT EXISTS github_run_attempt integer,
    ADD COLUMN IF NOT EXISTS crm_row_count integer,
    ADD COLUMN IF NOT EXISTS source_snapshot_at timestamptz,
    ADD COLUMN IF NOT EXISTS crm_snapshot_sha256 text,
    ADD COLUMN IF NOT EXISTS workbook_sha256 text,
    ADD COLUMN IF NOT EXISTS generated_at timestamptz,
    ADD COLUMN IF NOT EXISTS document_sent_at timestamptz,
    ADD COLUMN IF NOT EXISTS failure_stage text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='owner_daily_report_run_attempt_nonnegative') THEN
        ALTER TABLE public.owner_daily_report_receipts ADD CONSTRAINT owner_daily_report_run_attempt_nonnegative
            CHECK (github_run_attempt IS NULL OR github_run_attempt > 0) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='owner_daily_report_crm_count_nonnegative') THEN
        ALTER TABLE public.owner_daily_report_receipts ADD CONSTRAINT owner_daily_report_crm_count_nonnegative
            CHECK (crm_row_count IS NULL OR crm_row_count >= 0) NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='owner_daily_report_snapshot_sha256_format') THEN
        ALTER TABLE public.owner_daily_report_receipts ADD CONSTRAINT owner_daily_report_snapshot_sha256_format
            CHECK (crm_snapshot_sha256 IS NULL OR crm_snapshot_sha256 ~ '^[a-f0-9]{64}$') NOT VALID;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='owner_daily_report_workbook_sha256_format') THEN
        ALTER TABLE public.owner_daily_report_receipts ADD CONSTRAINT owner_daily_report_workbook_sha256_format
            CHECK (workbook_sha256 IS NULL OR workbook_sha256 ~ '^[a-f0-9]{64}$') NOT VALID;
    END IF;
END $$;
