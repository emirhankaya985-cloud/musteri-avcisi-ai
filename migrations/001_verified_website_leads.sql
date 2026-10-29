-- Retain strict source identity validation while admitting researched websites.
-- Run as one atomic ALTER; no contact data or sending state is modified.
ALTER TABLE public.owner_leads
    DROP CONSTRAINT owner_leads_osm_id_check,
    ADD CONSTRAINT owner_leads_osm_id_check CHECK (
        osm_id ~ '^(node|way|relation)/[0-9]+$'
        OR osm_id ~ '^website/[a-f0-9]{24}$'
    );
