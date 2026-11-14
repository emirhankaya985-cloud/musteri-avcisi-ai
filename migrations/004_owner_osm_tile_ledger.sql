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
