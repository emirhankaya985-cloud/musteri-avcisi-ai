"""Record conservative contact eligibility audits in the existing private CRM.

An audit is NOT approval. Only recipient_eligibility.eligible_recipient can
interpret separately verified consent/IYS evidence. Never access SMTP or Telegram.
"""
import os
from .review_private import connect_private_database

POLICY_URL = "https://ticaret.gov.tr/ic-ticaret/ticari-elektronik-iletiler/genel-bilgiler"
IYS_URL = "https://iys.org.tr/iys/yonetmelik"

AUDIT_SQL = """
WITH candidates AS (
  SELECT osm_id,
    CASE
      WHEN lead_data#>>'{marketing_eligibility,opted_out}' = 'true' THEN 'opted_out'
      WHEN lead_data#>>'{_auto_mail,delivery_feedback,state}' = 'failed' THEN 'delivery_failed'
      WHEN lead_data#>>'{_auto_mail,delivery_feedback,state}' = 'delayed' THEN 'delivery_delayed'
      WHEN lead_data->'_auto_mail'->>'state' IN ('accepted','sending','uncertain')
        OR lead_data->'_mail'->>'state' IN ('accepted','sending','uncertain')
        THEN 'previous_contact'
      ELSE 'legal_basis_unverified'
    END AS reason,
    CASE WHEN lead_data->'_auto_mail'->>'state' IN ('accepted','sending','uncertain')
         THEN 'frozen_smtp_history'
         WHEN lead_data#>>'{_auto_mail,delivery_feedback,state}' IS NOT NULL
         THEN 'gmail_dsn_record'
         ELSE 'public_osm_contact_tag' END AS evidence_origin,
    COALESCE(lead_data->>'email_check',
             lead_data#>>'{_auto_mail,email_check}','not_checked') AS address_preflight
  FROM owner_leads
  WHERE length(btrim(coalesce(lead_data#>>'{_auto_mail,recipient}',
            lead_data#>>'{_mail,recipient}',lead_data->>'email',''))) > 0
)
UPDATE owner_leads o SET
 lead_data=jsonb_set(o.lead_data,'{recipient_eligibility_audit}',
   jsonb_build_object(
     'decision','hold','reason',c.reason,'checked_at',now(),
     'evidence_origin',c.evidence_origin,'address_preflight',c.address_preflight,
     'regulatory_basis',%s::text,'iys_reference',%s::text,
     'permission_source','not_verified','automated_send_allowed',false
   ),true),
 updated_at=now()
FROM candidates c
WHERE o.osm_id=c.osm_id
  AND (NOT(o.lead_data ? 'recipient_eligibility_audit')
       OR coalesce(o.lead_data#>>'{recipient_eligibility_audit,reason}','') <> c.reason)
RETURNING o.lead_data#>>'{recipient_eligibility_audit,reason}' AS reason
"""


def run(conn=None, env=None):
    env = os.environ if env is None else env
    owns = conn is None
    conn = conn or connect_private_database(env.get("REVIEW_DATABASE_URL"))
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(789654323)")
                cur.execute(AUDIT_SQL, (POLICY_URL, IYS_URL))
                changed = cur.fetchall()
                cur.execute("SELECT count(*) FILTER (WHERE lead_data ? 'recipient_eligibility_audit'),"
                            "count(*) FILTER (WHERE lead_data ? 'marketing_eligibility') "
                            "FROM owner_leads")
                audits, legal = cur.fetchone()
        # No recipients, domains, company names, or private evidence emitted.
        print(f"RECIPIENT_AUDIT: changed={len(changed)}; audited={int(audits)};"
              f" documented_permission={int(legal)}; business_mail_sent=0")
        return len(changed)
    finally:
        if owns:
            conn.close()


if __name__ == "__main__":
    run()
