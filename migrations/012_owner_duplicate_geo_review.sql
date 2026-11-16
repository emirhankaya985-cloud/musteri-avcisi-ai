-- Private one-off, single-request public OSM node position verification.
-- This is identity REVIEW evidence only, never a merge/delete of CRM rows.
CREATE TABLE IF NOT EXISTS owner_duplicate_geo_evidence (
    lead_a text NOT NULL REFERENCES owner_leads(osm_id),
    lead_b text NOT NULL REFERENCES owner_leads(osm_id),
    distance_m numeric(12,2) CHECK (distance_m >= 0),
    location_band text NOT NULL
        CHECK (location_band IN ('co_located','nearby','separated','unverified')),
    source text NOT NULL DEFAULT 'OSM_0.6_nodes_bulk_single_query'
        CHECK (source = 'OSM_0.6_nodes_bulk_single_query'),
    github_run_id text NOT NULL CHECK (github_run_id ~ '^[0-9]{6,24}$'),
    observed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (lead_a,lead_b),
    FOREIGN KEY (lead_a,lead_b)
        REFERENCES owner_duplicate_review_pairs (lead_a,lead_b)
);
REVOKE ALL ON public.owner_duplicate_geo_evidence FROM PUBLIC;
REVOKE ALL ON public.owner_duplicate_geo_evidence FROM cc985_clients_ro;

CREATE OR REPLACE VIEW control_center_musteri_geo_review_v1
WITH (security_barrier=true) AS
SELECT count(*) AS observed_pairs,
       count(*) FILTER (WHERE location_band='co_located') AS co_located_pairs,
       count(*) FILTER (WHERE location_band='nearby') AS nearby_pairs,
       count(*) FILTER (WHERE location_band='separated') AS separated_pairs,
       count(*) FILTER (WHERE location_band='unverified') AS unverified_pairs,
       max(observed_at) AS last_position_review_at
FROM owner_duplicate_geo_evidence;
REVOKE ALL ON public.control_center_musteri_geo_review_v1 FROM PUBLIC;
GRANT SELECT ON public.control_center_musteri_geo_review_v1 TO
    cc985_clients_ro, control_center_musteri_reader;
