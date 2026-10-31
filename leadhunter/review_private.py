"""Private review decisions stored in a separate Neon Postgres database.

Only OSM IDs may be committed to public GitHub. Leads and owner decisions stay
in the private database, never in Action logs, artifacts, or public state.
"""
import json
import re

OSM_ID = re.compile(r"(?:node|way|relation)/[0-9]+\Z")


def connect_private_database(url):
    if not isinstance(url, str) or not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("REVIEW_DATABASE_URL is missing or invalid")
    if "sslmode=require" not in url:
        raise RuntimeError("Private review database must require SSL")
    try:
        import psycopg
        return psycopg.connect(url, connect_timeout=15, autocommit=True)
    except Exception:
        # Database exception strings may embed passwords and customer data.
        raise RuntimeError("Private review database connection failed; details redacted") from None


class ReviewStore:
    def __init__(self, connection):
        self.db = connection

    def _read(self, query, params=()):
        try:
            with self.db.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall()
        except Exception:
            raise RuntimeError("Private review database read failed; details redacted") from None

    def mail_summary(self):
        """Private database totals, never return addresses or message bodies."""
        rows = self._read(
            "SELECT count(*), "
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->>'state'='accepted' "
            "OR lead_data->'_mail'->>'state'='accepted'), "
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->>'state' IN ('sending','uncertain') "
            "OR lead_data->'_mail'->>'state' IN ('sending','uncertain')), "
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->>'state'='skipped'), "
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->>'state'='duplicate'), "
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->'delivery_feedback'->>'state'='failed'), "
            "count(*) FILTER (WHERE lead_data->'_auto_mail'->'delivery_feedback'->>'state'='delayed') "
            "FROM owner_leads")
        if not rows:
            raise RuntimeError("Private mail history unavailable")
        total, accepted, uncertain, skipped, duplicate, failed, delayed = rows[0]
        return dict(total=total, accepted=accepted, uncertain=uncertain,
                    skipped=skipped, duplicate=duplicate, failed=failed, delayed=delayed)

    def already_contacted(self, lead):
        """Read old claimed mail identities before displaying a recycled lead."""
        from .mail_tracking import already_contacted
        rows = self._read(
            "SELECT lead_data FROM owner_leads WHERE "
            "lead_data->'_auto_mail'->>'state' IN ('sending','accepted','uncertain') "
            "OR lead_data->'_mail'->>'state' IN ('sending','accepted','uncertain')")
        for (data,) in rows:
            value = json.loads(data) if isinstance(data, str) else data
            if already_contacted(lead, value):
                return True
        return False

    def statuses(self):
        return {lead_id: state for lead_id, state in
                self._read("SELECT osm_id,status FROM owner_leads ORDER BY "
                           "CASE WHEN status='deferred' THEN 0 ELSE 1 END, "
                           "updated_at,osm_id")}

    def deferred(self):
        rows = self._read(
            "SELECT lead_data FROM owner_leads WHERE status='deferred' "
            "ORDER BY updated_at, osm_id")
        return [json.loads(row[0]) if isinstance(row[0], str) else row[0]
                for row in rows]

    def register(self, lead):
        lead_id = lead.get("id")
        if not isinstance(lead_id, str) or not OSM_ID.fullmatch(lead_id):
            raise ValueError("Invalid OSM lead ID")
        try:
            with self.db.transaction():
                with self.db.cursor() as cur:
                    cur.execute(
                        "INSERT INTO owner_leads (osm_id,lead_data,status) "
                        "VALUES (%s, %s::jsonb, 'review') "
                        "ON CONFLICT (osm_id) DO UPDATE SET "
                        "lead_data=EXCLUDED.lead_data,updated_at=now() "
                        "WHERE owner_leads.status IN ('review','deferred') "
                        "AND NOT (owner_leads.lead_data ? '_auto_mail')",
                        (lead_id, json.dumps(lead, ensure_ascii=False)))
        except Exception:
            raise RuntimeError("Private lead registration failed; details redacted") from None

    def presented(self, lead_id, message_id):
        if not OSM_ID.fullmatch(lead_id) or type(message_id) is not int or message_id <= 0:
            raise ValueError("Invalid Telegram presentation")
        try:
            with self.db.transaction():
                with self.db.cursor() as cur:
                    cur.execute(
                        "UPDATE owner_leads SET telegram_message_id=%s,"
                        "last_presented_at=now() WHERE osm_id=%s AND "
                        "status IN ('review','deferred') RETURNING osm_id",
                        (message_id, lead_id))
                    if cur.fetchone() is None:
                        raise ValueError("Lead no longer available for review")
        except ValueError:
            raise
        except Exception:
            raise RuntimeError("Private presentation save failed; details redacted") from None

    def decide(self, lead_id, message_id, action):
        from .review_flow import ACTIONS, decide as transition
        if not OSM_ID.fullmatch(lead_id) or type(message_id) is not int or action not in ACTIONS:
            return None
        try:
            with self.db.transaction():
                with self.db.cursor() as cur:
                    cur.execute(
                        "SELECT status,telegram_message_id FROM owner_leads "
                        "WHERE osm_id=%s FOR UPDATE", (lead_id,))
                    row = cur.fetchone()
                    if not row or row[1] != message_id:
                        return None
                    old_status = row[0]
                    new_status = transition({lead_id: old_status}, lead_id, action)[lead_id]
                    if new_status != old_status:
                        cur.execute(
                            "UPDATE owner_leads SET status=%s, updated_at=now(),"
                            "approved_at=CASE WHEN %s='email_pending' THEN now() "
                            "ELSE approved_at END WHERE osm_id=%s",
                            (new_status, new_status, lead_id))
                    return new_status
        except Exception:
            raise RuntimeError("Private decision transaction failed; details redacted") from None
