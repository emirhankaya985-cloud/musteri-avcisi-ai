-- Non-destructive private company identity review. Never automatically merge,
-- delete, suppress or modify historical owner_leads or accepted email claims.
CREATE TABLE IF NOT EXISTS owner_duplicate_review_pairs (
    lead_a text NOT NULL REFERENCES owner_leads(osm_id),
    lead_b text NOT NULL REFERENCES owner_leads(osm_id),
    evidence text[] NOT NULL CHECK (
        evidence <@ ARRAY['same_first_party_domain','same_phone',
                          'same_name_address','same_name_category_review']::text[]),
    review_state text NOT NULL DEFAULT 'needs_review'
        CHECK (review_state IN ('needs_review','not_duplicate','confirmed_duplicate')),
    first_detected_at timestamptz NOT NULL DEFAULT now(),
    last_observed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (lead_a,lead_b),
    CHECK (lead_a<lead_b)
);
CREATE INDEX IF NOT EXISTS owner_duplicate_review_pairs_state_idx
    ON owner_duplicate_review_pairs(review_state);

CREATE OR REPLACE VIEW control_center_musteri_duplicate_review_v1
WITH (security_barrier=true) AS
SELECT count(*) FILTER (WHERE review_state='needs_review') AS review_needed_pairs,
       count(*) FILTER (WHERE review_state='not_duplicate') AS dismissed_pairs,
       count(*) FILTER (WHERE review_state='confirmed_duplicate') AS confirmed_duplicate_pairs,
       max(last_observed_at) AS last_duplicate_audit_at
FROM owner_duplicate_review_pairs;

REVOKE ALL ON control_center_musteri_duplicate_review_v1 FROM PUBLIC;
GRANT SELECT ON control_center_musteri_duplicate_review_v1 TO control_center_musteri_reader;
