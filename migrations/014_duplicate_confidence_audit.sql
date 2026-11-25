-- Add evidence scoring and append-only review history without changing any
-- owner_leads records, existing human decisions, or source data.
ALTER TABLE public.owner_duplicate_review_pairs
    ADD COLUMN IF NOT EXISTS confidence_score smallint
        CHECK (confidence_score BETWEEN 0 AND 100),
    ADD COLUMN IF NOT EXISTS confidence_details jsonb NOT NULL DEFAULT '{}'::jsonb
        CHECK (jsonb_typeof(confidence_details) = 'object');

CREATE TABLE IF NOT EXISTS public.owner_duplicate_review_audit (
    audit_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lead_a text NOT NULL,
    lead_b text NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'candidate_detected','decision_changed','evidence_refreshed')),
    old_review_state text,
    new_review_state text NOT NULL CHECK (new_review_state IN (
        'needs_review','not_duplicate','confirmed_duplicate')),
    old_evidence text[],
    new_evidence text[] NOT NULL,
    old_confidence_score smallint CHECK (old_confidence_score BETWEEN 0 AND 100),
    new_confidence_score smallint CHECK (new_confidence_score BETWEEN 0 AND 100),
    old_confidence_details jsonb,
    new_confidence_details jsonb NOT NULL
        CHECK (jsonb_typeof(new_confidence_details) = 'object'),
    actor text NOT NULL DEFAULT current_user,
    application_name text NOT NULL DEFAULT coalesce(
        nullif(current_setting('application_name',true),''),'unspecified'),
    observed_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (lead_a,lead_b)
        REFERENCES public.owner_duplicate_review_pairs (lead_a,lead_b)
);

CREATE INDEX IF NOT EXISTS owner_duplicate_review_audit_pair_time_idx
    ON public.owner_duplicate_review_audit (lead_a,lead_b,observed_at);

CREATE OR REPLACE FUNCTION public.audit_owner_duplicate_review_pair()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public AS $$
DECLARE
    event_name text;
BEGIN
    IF TG_OP = 'INSERT' THEN
        event_name := 'candidate_detected';
        INSERT INTO public.owner_duplicate_review_audit (
            lead_a,lead_b,event_type,new_review_state,new_evidence,
            new_confidence_score,new_confidence_details,actor)
        VALUES (NEW.lead_a,NEW.lead_b,event_name,NEW.review_state,NEW.evidence,
                NEW.confidence_score,NEW.confidence_details,session_user);
        RETURN NEW;
    END IF;

    IF NEW.review_state IS DISTINCT FROM OLD.review_state THEN
        event_name := 'decision_changed';
    ELSIF NEW.evidence IS DISTINCT FROM OLD.evidence
       OR NEW.confidence_score IS DISTINCT FROM OLD.confidence_score
       OR NEW.confidence_details IS DISTINCT FROM OLD.confidence_details THEN
        event_name := 'evidence_refreshed';
    ELSE
        RETURN NEW;
    END IF;

    INSERT INTO public.owner_duplicate_review_audit (
        lead_a,lead_b,event_type,old_review_state,new_review_state,
        old_evidence,new_evidence,old_confidence_score,new_confidence_score,
        old_confidence_details,new_confidence_details,actor)
    VALUES (NEW.lead_a,NEW.lead_b,event_name,OLD.review_state,NEW.review_state,
            OLD.evidence,NEW.evidence,OLD.confidence_score,NEW.confidence_score,
            OLD.confidence_details,NEW.confidence_details,session_user);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS owner_duplicate_review_audit_trg
    ON public.owner_duplicate_review_pairs;
CREATE TRIGGER owner_duplicate_review_audit_trg
AFTER INSERT OR UPDATE ON public.owner_duplicate_review_pairs
FOR EACH ROW EXECUTE FUNCTION public.audit_owner_duplicate_review_pair();

REVOKE ALL ON FUNCTION public.audit_owner_duplicate_review_pair() FROM PUBLIC;
REVOKE ALL ON public.owner_duplicate_review_audit FROM PUBLIC;
REVOKE ALL ON SEQUENCE public.owner_duplicate_review_audit_audit_id_seq FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='cc985_clients_ro') THEN
        EXECUTE 'REVOKE ALL ON public.owner_duplicate_review_audit FROM cc985_clients_ro';
        EXECUTE 'REVOKE ALL ON SEQUENCE public.owner_duplicate_review_audit_audit_id_seq FROM cc985_clients_ro';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='control_center_musteri_reader') THEN
        EXECUTE 'REVOKE ALL ON public.owner_duplicate_review_audit FROM control_center_musteri_reader';
        EXECUTE 'REVOKE ALL ON SEQUENCE public.owner_duplicate_review_audit_audit_id_seq FROM control_center_musteri_reader';
    END IF;
END $$;
