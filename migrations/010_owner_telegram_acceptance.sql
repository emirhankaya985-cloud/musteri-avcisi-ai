-- Exactly one owner-only Telegram acceptance notification; never customers.
-- The claim is committed BEFORE contacting Telegram to make retries at-most-once.
CREATE TABLE IF NOT EXISTS owner_telegram_alert_acceptance (
  test_key text PRIMARY KEY CHECK (test_key ~ '^[a-z0-9_-]{8,70}$'),
  state text NOT NULL CHECK (state IN ('reserved','api_accepted','failed')),
  api_message_id bigint,
  claimed_at timestamptz NOT NULL DEFAULT now(),
  verified_at timestamptz
);
REVOKE ALL ON public.owner_telegram_alert_acceptance FROM PUBLIC;
REVOKE ALL ON public.owner_telegram_alert_acceptance FROM cc985_clients_ro;
