-- Private sales lifecycle state and append-only transition history.
-- This is not an email permission table and never changes owner_leads data.
CREATE TABLE IF NOT EXISTS public.owner_lead_lifecycle_state (
    lead_id text PRIMARY KEY REFERENCES public.owner_leads(osm_id),
    current_stage text NOT NULL CHECK (current_stage IN (
        'new_discovered','researched','need_verified','communication_eligible',
        'proposal_prepared','email_sent','replied','meeting_scheduled',
        'offer_made','won','lost','do_not_contact')),
    stage_updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by text NOT NULL DEFAULT current_user
);

CREATE INDEX IF NOT EXISTS owner_lead_lifecycle_stage_updated_idx
    ON public.owner_lead_lifecycle_state(current_stage, stage_updated_at DESC);

CREATE TABLE IF NOT EXISTS public.owner_lead_lifecycle_events (
    event_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_id text NOT NULL REFERENCES public.owner_leads(osm_id),
    idempotency_key text NOT NULL UNIQUE,
    previous_stage text CHECK (previous_stage IS NULL OR previous_stage IN (
        'new_discovered','researched','need_verified','communication_eligible',
        'proposal_prepared','email_sent','replied','meeting_scheduled',
        'offer_made','won','lost','do_not_contact')),
    new_stage text NOT NULL CHECK (new_stage IN (
        'new_discovered','researched','need_verified','communication_eligible',
        'proposal_prepared','email_sent','replied','meeting_scheduled',
        'offer_made','won','lost','do_not_contact')),
    reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 1 AND 500),
    evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(evidence_refs) = 'array'),
    actor text NOT NULL DEFAULT current_user,
    occurred_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS owner_lead_lifecycle_events_lead_time_idx
    ON public.owner_lead_lifecycle_events(lead_id, occurred_at, event_id);

CREATE OR REPLACE FUNCTION public.reject_owner_lead_lifecycle_event_mutation()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
BEGIN
    RAISE EXCEPTION 'owner_lead_lifecycle_events is append-only; UPDATE, DELETE and TRUNCATE are rejected';
END;
$$;

DROP TRIGGER IF EXISTS owner_lead_lifecycle_event_no_update_delete_trg
    ON public.owner_lead_lifecycle_events;
CREATE TRIGGER owner_lead_lifecycle_event_no_update_delete_trg
BEFORE UPDATE OR DELETE ON public.owner_lead_lifecycle_events
FOR EACH ROW EXECUTE FUNCTION public.reject_owner_lead_lifecycle_event_mutation();

DROP TRIGGER IF EXISTS owner_lead_lifecycle_event_no_truncate_trg
    ON public.owner_lead_lifecycle_events;
CREATE TRIGGER owner_lead_lifecycle_event_no_truncate_trg
BEFORE TRUNCATE ON public.owner_lead_lifecycle_events
FOR EACH STATEMENT EXECUTE FUNCTION public.reject_owner_lead_lifecycle_event_mutation();

REVOKE ALL ON FUNCTION public.reject_owner_lead_lifecycle_event_mutation() FROM PUBLIC;
REVOKE ALL ON public.owner_lead_lifecycle_state FROM PUBLIC;
REVOKE ALL ON public.owner_lead_lifecycle_events FROM PUBLIC;
REVOKE ALL ON SEQUENCE public.owner_lead_lifecycle_events_event_id_seq FROM PUBLIC;

COMMENT ON TABLE public.owner_lead_lifecycle_state IS
    'Private current CRM lifecycle stage; communication_eligible is not a send authorization.';
COMMENT ON TABLE public.owner_lead_lifecycle_events IS
    'Private append-only CRM lifecycle history. Public email/contact visibility does not grant send eligibility.';
