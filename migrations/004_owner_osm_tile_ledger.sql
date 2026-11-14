-- Additive, private 402-tile progress mirror. No contact, lead name,
-- email, credentials, HTTP response or customer data in this table.
-- The original versioned GitHub tile ledger remains the resumable scan cursor.
CREATE TABLE IF NOT EXISTS owner_osm_tile_ledger (
  region text NOT NULL CHECK (region ~ '^pilot_[1-8]_of_8$'),
  tile_index integer NOT NULL CHECK (tile_index >= 0),
  state text NOT NULL CHECK (state IN ('pending','confirmed','retry','blocked')),
  reason text NULL CHECK (reason IN ('unverified_source_failure','provider_refusal',
    'timeout','dns','tls','connection','network','http_5xx','http_other',
    'response_oversize','response_invalid','provider_remark')),
  last_observed_run_id text NULL CHECK (last_observed_run_id ~ '^[0-9]{6,24}$'),
  updated_at timestamptz NULL,
  PRIMARY KEY (region,tile_index),
  CHECK (state IN ('retry','blocked') OR reason IS NULL)
);
CREATE INDEX IF NOT EXISTS owner_osm_tile_ledger_state_idx
  ON owner_osm_tile_ledger(state);
-- Rollback: stop the mirror writer first, retain this ledger for evidence.

-- Owner-only aggregated view. No individual business names, emails, SMTP
-- message identifiers, recipient information or raw source responses.
-- Do not grant access to PUBLIC. Grant SELECT only to a dedicated Control
-- Center reader after the central service and database role exist.
CREATE OR REPLACE VIEW control_center_musteri_v1 WITH (security_barrier=true) AS
SELECT
  (SELECT count(*) FROM owner_leads) AS leads_total,
  (SELECT count(*) FROM owner_leads WHERE status='review') AS leads_in_review,
  (SELECT count(*) FROM owner_leads WHERE status='email_sent') AS smtp_acceptance_rows,
  (SELECT count(*) FROM owner_leads
   WHERE lead_data#>>'{_auto_mail,delivery_feedback,state}'='failed') AS observed_delivery_failures,
  (SELECT count(*) FROM owner_leads
   WHERE lead_data#>>'{_auto_mail,reply_feedback,state}'='sender_matched_reply') AS matched_replies,
  (SELECT count(*) FROM owner_scan_run_metrics) AS scan_metric_runs,
  (SELECT max(created_at) FROM owner_scan_run_metrics) AS last_recorded_scan_at,
  (SELECT max(created_at) FROM owner_mail_watch_runs) AS last_mail_watch_at,
  (SELECT coalesce(sum(new_registered),0) FROM owner_scan_run_metrics
   WHERE report_day = (now() AT TIME ZONE 'Europe/Istanbul')::date) AS new_today,
  (SELECT coalesce(jsonb_object_agg(category,n),'{}'::jsonb)
   FROM (SELECT coalesce(lead_data->>'category','unclassified') AS category,
         count(*) AS n FROM owner_leads GROUP BY 1) s) AS by_sector,
  (SELECT coalesce(jsonb_object_agg(region,details),'{}'::jsonb)
   FROM (SELECT region, jsonb_build_object(
           'confirmed',count(*) FILTER (WHERE state='confirmed'),
           'pending',count(*) FILTER (WHERE state='pending'),
           'retry',count(*) FILTER (WHERE state='retry'),
           'blocked',count(*) FILTER (WHERE state='blocked'),
           'total',count(*),
           'last_updated_at',max(updated_at)
         ) AS details FROM owner_osm_tile_ledger GROUP BY region) t) AS by_region,
  (SELECT count(*) FROM owner_osm_tile_ledger WHERE state='confirmed') AS confirmed_tiles,
  (SELECT count(*) FROM owner_osm_tile_ledger) AS total_tiles,
  date_trunc('hour',now()) +
      CASE WHEN extract(minute FROM now()) < 13 THEN interval '13 minutes'
      ELSE interval '73 minutes' END AS next_scheduled_target_utc,
  now() AS snapshot_at;
