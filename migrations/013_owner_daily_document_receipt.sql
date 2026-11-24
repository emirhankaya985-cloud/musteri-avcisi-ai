-- Additive receipt for the private daily Excel document upload.
-- Existing report/message history is preserved.
ALTER TABLE public.owner_daily_report_receipts
    ADD COLUMN IF NOT EXISTS telegram_document_message_id bigint;

-- Rollback: keep this column populated as an audit receipt; do not drop it
-- while daily reports or message history are retained.
