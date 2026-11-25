-- Private, resumable administrative-coverage ledger. It stores no business
-- details, source payloads, emails, or credentials. Rows remain pending until
-- a reviewed boundary manifest and successful source receipts are recorded.
CREATE TABLE IF NOT EXISTS owner_province_scan_coverage (
  province_code text PRIMARY KEY CHECK (province_code ~ '^[0-9]{2}$'),
  province_name text NOT NULL,
  initial_phase_target boolean NOT NULL DEFAULT false,
  status text NOT NULL CHECK (status IN ('pending','running','completed','partial','failed')),
  province_state jsonb NOT NULL CHECK (jsonb_typeof(province_state)='object'),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NULL,
  CHECK (province_state->>'code'=province_code),
  CHECK (province_state->>'name'=province_name),
  CHECK (province_state->>'status'=status),
  CHECK ((province_state->>'initial_phase_target')::boolean=initial_phase_target)
);

CREATE INDEX IF NOT EXISTS owner_province_scan_coverage_status_idx
  ON owner_province_scan_coverage(status, initial_phase_target);

REVOKE ALL ON owner_province_scan_coverage FROM PUBLIC;
