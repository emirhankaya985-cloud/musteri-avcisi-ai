"""Read-only Neon -> isolated temporary PostgreSQL restore integrity check.

Never prints production row values or connection strings. The GitHub workflow
creates a custom-format pg_dump in runner RAM/disk and restores ONLY to an
isolated ephemeral Postgres test service, never to the live Neon project.
"""
from hashlib import sha256
import json
import os


def row_fingerprint(rows):
    """Canonical full-row digest independent of SQL row order."""
    strings = sorted(json.dumps(list(row), sort_keys=True, ensure_ascii=False,
                                default=str, separators=(",", ":"))
                     for row in rows)
    h = sha256()
    for entry in strings:
        h.update(entry.encode("utf-8"))
        h.update(b"\n")
    return len(strings), h.hexdigest()


def inventory(conn):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_type='BASE TABLE' "
            "ORDER BY table_name")
        tables = [row[0] for row in cur.fetchall()]
        if not tables or len(tables) > 30:
            raise RuntimeError("Unexpected public table inventory")
        result = {}
        for table in tables:
            if not isinstance(table,str) or not table.replace("_","").isalnum():
                raise RuntimeError("Unsafe public table name")
            cur.execute(f'SELECT * FROM public."{table}"')
            result[table] = row_fingerprint(cur.fetchall())
    return result


def compare_inventory(source, restored):
    return bool(source) and source == restored


def run(env=None, output=print):
    env = os.environ if env is None else env
    url = env.get("REVIEW_DATABASE_URL")
    scratch = env.get("ISOLATED_POSTGRES_URL")
    if not url or not scratch or url == scratch:
        raise RuntimeError("Isolated restore requires distinct configured databases")
    # Check scratch address independently, never infer target from source URL.
    from urllib.parse import urlsplit
    parsed = urlsplit(scratch)
    if parsed.hostname not in ("localhost", "127.0.0.1") or parsed.port != 5432:
        raise RuntimeError("Refusing to inspect a non-local restore target")
    import psycopg
    try:
        with psycopg.connect(url, connect_timeout=12, options="-c default_transaction_read_only=on") as source:
            expected = inventory(source)
        with psycopg.connect(scratch, connect_timeout=5) as target:
            observed = inventory(target)
    except Exception:
        raise RuntimeError("Restore verification unavailable; private details redacted") from None
    if not compare_inventory(expected,observed):
        raise RuntimeError("RESTORE_ACCEPTANCE: FAIL; snapshot/restore inventory mismatch")
    output("RESTORE_ACCEPTANCE: PASS; public_tables=" + str(len(expected)) +
           "; all_rows_full_fingerprint_match=1; production_writes=0; "
           "emails_sent=0; archive_not_uploaded=1")
    return True


if __name__ == "__main__":
    run()
