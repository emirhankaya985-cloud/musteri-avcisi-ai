"""Owner-review Neon integration smoke: reversible and entirely internal.

Exercises real PostgreSQL transactions for YES / NO / LATER, but deliberately
rolls back every synthetic change. Sends NO Telegram, email, or business DM.
Uses the private database URL from GitHub Actions secrets only.
"""
import os

from .review_private import ReviewStore, connect_private_database
from .review_flow import prioritized_leads

# Deliberately outside normal current OSM ID ranges, never displayed to users.
TEST_IDS = (
    "node/999999999999991",
    "way/999999999999992",
    "relation/999999999999993",
)
TEST_MESSAGE = 9999999999


class _RollbackOnPurpose(Exception):
    """Raised inside a transaction so its test-only writes cannot commit."""


def _fixture(lead_id):
    return {
        "id": lead_id,
        "name": "SYNTHETIC REVIEW TEST - NOT A REAL BUSINESS",
        "category": "Kuaför/berber",
        "website": "",
        "phone": "",
        "address": "",
        "score": 75,
    }


def verify(conn):
    """Read-only schema check plus guaranteed rollback for temporary test rows."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.owner_leads') IS NOT NULL")
        if cur.fetchone() != (True,):
            raise RuntimeError("Private review table is missing")
        cur.execute("SELECT osm_id FROM owner_leads WHERE osm_id = ANY(%s)",
                    (list(TEST_IDS),))
        if cur.fetchall():
            raise RuntimeError("Synthetic test ID already present; refusing to modify it")

    store = ReviewStore(conn)
    choices = ("yes", "no", "later")
    expected = ("email_pending", "rejected", "deferred")
    try:
        # psycopg autocommit=True allows explicit outer transaction; each nested
        # ReviewStore transaction becomes a SAVEPOINT. Throw on purpose to rollback.
        with conn.transaction():
            for lead_id, action, result in zip(TEST_IDS, choices, expected):
                store.register(_fixture(lead_id))
                store.presented(lead_id, TEST_MESSAGE)
                if store.decide(lead_id, TEST_MESSAGE + 1, action) is not None:
                    raise RuntimeError("Stale Telegram message unexpectedly accepted")
                if store.decide(lead_id, TEST_MESSAGE, action) != result:
                    raise RuntimeError("Wrong owner decision transition")
                with conn.cursor() as cur:
                    cur.execute("SELECT status FROM owner_leads WHERE osm_id=%s",
                                (lead_id,))
                    if cur.fetchone() != (result,):
                        raise RuntimeError("Owner decision was not persisted transactionally")
            held = prioritized_leads(
                store.statuses(), [], deferred_fallback=store.deferred(), maximum=5)
            if not held or held[0]["id"] != TEST_IDS[2]:
                raise RuntimeError("Deferred lead is not first in next scan")
            if store.decide(TEST_IDS[2], TEST_MESSAGE, "later") != "deferred":
                raise RuntimeError("Repeat defer is broken")
            if store.decide(TEST_IDS[1], TEST_MESSAGE, "yes") != "rejected":
                raise RuntimeError("Rejected lead could be reapproved")
            raise _RollbackOnPurpose()
    except _RollbackOnPurpose:
        pass

    # Confirm test records do not persist after the explicit rollback.
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM owner_leads WHERE osm_id = ANY(%s)",
                    (list(TEST_IDS),))
        if cur.fetchone() != (0,):
            raise RuntimeError("Synthetic test rows survived rollback")
    return True


def run(env=None, connector=None, output=print):
    env = os.environ if env is None else env
    url = env.get("REVIEW_DATABASE_URL")
    if not url:
        raise RuntimeError("REVIEW_DATABASE_URL not configured; no review test")
    open_database = connect_private_database if connector is None else connector
    try:
        conn = open_database(url)
    except Exception:
        raise RuntimeError("Private Neon smoke could not connect; credentials redacted") from None
    try:
        if verify(conn) is not True:
            raise RuntimeError("Private Neon smoke verification incomplete")
    except Exception:
        raise RuntimeError("Private Neon smoke failed; credentials redacted") from None
    finally:
        conn.close()
    output("PASS: Private Neon YES/NO/LATER + deferred priority; temporary records rolled back; no emails or Telegram sent")
    return True


if __name__ == "__main__":
    run()
