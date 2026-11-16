-- Additive post-coverage source observations. Do not modify or rewind the
-- original 402-cell success ledger; no business mail, no auto customer merge.
CREATE TABLE IF NOT EXISTS owner_osm_incremental_runs (
  snapshot_sha256 text PRIMARY KEY CHECK (snapshot_sha256 ~ '^[a-f0-9]{64}$'),
  source_data_at timestamptz NOT NULL UNIQUE,
  github_run_id text NOT NULL CHECK (github_run_id ~ '^[0-9]{6,24}$'),
  candidate_count integer NOT NULL CHECK(candidate_count>=0),
  newly_registered integer NOT NULL CHECK(newly_registered>=0),
  changed_existing integer NOT NULL CHECK(changed_existing>=0),
  verified_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS owner_osm_incremental_changes (
  osm_id text PRIMARY KEY REFERENCES owner_leads(osm_id),
  snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[a-f0-9]{64}$'),
  source_data_at timestamptz NOT NULL,
  fields_changed text[] NOT NULL CHECK(fields_changed <@ ARRAY[
    'name','category','website','phone','email','address']::text[]),
  proposed_lead jsonb NOT NULL,
  review_state text NOT NULL DEFAULT 'needs_review'
    CHECK (review_state IN ('needs_review','not_an_update','owner_accepted')),
  observed_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW control_center_musteri_incremental_v1
WITH (security_barrier=true) AS
SELECT
  (SELECT count(*) FROM owner_osm_incremental_runs) AS successful_incremental_runs,
  (SELECT sum(newly_registered) FROM owner_osm_incremental_runs) AS new_leads_from_incremental,
  (SELECT max(source_data_at) FROM owner_osm_incremental_runs) AS last_incremental_source_at,
  (SELECT max(verified_at) FROM owner_osm_incremental_runs) AS last_incremental_verified_at,
  (SELECT count(*) FROM owner_osm_incremental_changes
      WHERE review_state='needs_review') AS changed_businesses_need_review,
  (SELECT max(source_data_at) FROM owner_osm_tile_snapshot_provenance) AS initial_source_at;

REVOKE ALL ON control_center_musteri_incremental_v1 FROM PUBLIC;
GRANT SELECT ON control_center_musteri_incremental_v1 TO control_center_musteri_reader;
GRANT SELECT ON control_center_musteri_incremental_v1 TO cc985_clients_ro;
