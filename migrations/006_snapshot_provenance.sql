-- Private, additive evidence: confirmed per-tile coverage from a real,
-- checksum-verified Geofabrik OpenStreetMap country snapshot.
-- Do not expose individual customer contact data or historical sent records.
CREATE TABLE IF NOT EXISTS owner_osm_tile_snapshot_provenance (
    region text NOT NULL CHECK (region ~ '^pilot_[1-8]_of_8$'),
    tile_index integer NOT NULL CHECK (tile_index BETWEEN 0 AND 53),
    snapshot_sha256 text NOT NULL CHECK (snapshot_sha256 ~ '^[a-f0-9]{64}$'),
    source_data_at timestamptz NOT NULL,
    candidate_count integer NOT NULL CHECK (candidate_count >= 0),
    inserted_count integer NOT NULL CHECK (inserted_count >= 0),
    run_id text NOT NULL CHECK (run_id ~ '^[0-9]{6,24}$'),
    verified_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (region,tile_index),
    FOREIGN KEY (region,tile_index)
       REFERENCES owner_osm_tile_ledger(region,tile_index)
);

CREATE OR REPLACE VIEW control_center_musteri_snapshot_v1
WITH (security_barrier=true) AS
SELECT count(*) AS snapshot_confirmed_tiles,
       min(source_data_at) AS oldest_snapshot_data_at,
       max(source_data_at) AS newest_snapshot_data_at,
       count(DISTINCT snapshot_sha256) AS distinct_source_files,
       max(verified_at) AS last_snapshot_verified_at,
       coalesce(sum(inserted_count),0) AS new_private_crm_records
FROM owner_osm_tile_snapshot_provenance;

REVOKE ALL ON control_center_musteri_snapshot_v1 FROM PUBLIC;
GRANT SELECT ON control_center_musteri_snapshot_v1 TO control_center_musteri_reader;
