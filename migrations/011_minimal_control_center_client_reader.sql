-- Narrow central panel's existing SELECT-only connector role. It already
-- has the aggregate view grants necessary for 390 leads/402 coverage/freshness,
-- but raw company-change evidence should not be exposed to dashboard queries.
-- No business records or application state are changed.
REVOKE SELECT ON public.owner_osm_incremental_changes,
                 public.owner_duplicate_review_pairs
FROM cc985_clients_ro;
GRANT SELECT ON public.control_center_musteri_incremental_v1,
                public.control_center_musteri_duplicate_review_v1,
                public.control_center_musteri_snapshot_v1,
                public.control_center_musteri_runs_v1,
                public.control_center_musteri_provider_v1,
                public.control_center_musteri_v1
TO cc985_clients_ro;
