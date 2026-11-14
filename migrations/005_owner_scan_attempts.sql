-- Additive run-level evidence. Only bounded operational metadata; no
-- recipient, business, SMTP credential, raw URL or raw HTTP response.
CREATE TABLE IF NOT EXISTS owner_scan_attempts (
    scan_run_id text PRIMARY KEY CHECK (scan_run_id ~ '^[0-9]{6,24}$'),
    region text CHECK (region ~ '^pilot_[1-8]_of_8$'),
    outcome text NOT NULL CHECK (outcome IN ('success','partial','failure','skipped','cancelled')),
    source_reason text NOT NULL CHECK (source_reason IN (
        'none','unverified','timeout','dns','tls','connection','network',
        'http_5xx','http_other','response_oversize','response_invalid',
        'provider_remark','provider_refusal')),
    source_http_status integer CHECK (source_http_status IN (400,401,403,406,429)),
    provider_index integer CHECK (provider_index BETWEEN 0 AND 2),
    confirmed_before integer CHECK (confirmed_before BETWEEN 0 AND 54),
    confirmed_after integer CHECK (confirmed_after BETWEEN 0 AND 54),
    CHECK (confirmed_after IS NULL OR confirmed_before IS NULL OR
           confirmed_after >= confirmed_before),
    CHECK (source_http_status IS NULL OR source_reason='provider_refusal'),
    mirror_outcome text NOT NULL CHECK (mirror_outcome IN
        ('success','failure','skipped','cancelled')),
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS owner_scan_attempts_time_idx
    ON owner_scan_attempts (recorded_at DESC);

-- Separate read-only panel contract; no change to existing Task 3 schemas.
CREATE OR REPLACE VIEW control_center_musteri_runs_v1
WITH (security_barrier=true) AS
SELECT scan_run_id,region,outcome,source_reason,source_http_status,
       provider_index,confirmed_before,confirmed_after,
       CASE WHEN confirmed_after IS NOT NULL AND confirmed_before IS NOT NULL
            THEN confirmed_after-confirmed_before END AS confirmed_new,
       mirror_outcome,recorded_at
FROM owner_scan_attempts;

CREATE OR REPLACE VIEW control_center_musteri_provider_v1
WITH (security_barrier=true) AS
SELECT provider_index,count(*) AS recorded_visits,
       count(*) FILTER (WHERE outcome IN ('success','partial')) AS accepted_visits,
       count(*) FILTER (WHERE source_reason='http_5xx') AS http_5xx_visits,
       count(*) FILTER (WHERE source_reason='timeout') AS timeout_visits,
       count(*) FILTER (WHERE source_reason='provider_refusal') AS refusal_visits,
       max(recorded_at) AS last_observed_at
FROM owner_scan_attempts
WHERE provider_index IS NOT NULL
GROUP BY provider_index;

-- An existing NOLOGIN reader is intentionally not given owner table access.
REVOKE ALL ON control_center_musteri_runs_v1 FROM PUBLIC;
REVOKE ALL ON control_center_musteri_provider_v1 FROM PUBLIC;
GRANT SELECT ON control_center_musteri_runs_v1 TO control_center_musteri_reader;
GRANT SELECT ON control_center_musteri_provider_v1 TO control_center_musteri_reader;
