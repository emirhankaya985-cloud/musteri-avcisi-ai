-- Additive fix to the existing read-only, security-barrier Control Center
-- view: new_today must count actual private CRM first_seen_at rows including
-- one-time verified OSM source snapshots, not just hourly scan metrics.
-- Historical scan_metric_runs and last_recorded_scan_at retain their own meaning.
-- Same view fields/types/privileges as migration 004; no customer identities
-- are exposed, and no historical rows are changed.
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
  (SELECT count(*) FROM owner_leads
   WHERE (first_seen_at AT TIME ZONE 'Europe/Istanbul')::date =
         (now() AT TIME ZONE 'Europe/Istanbul')::date) AS new_today,
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
