# Neon recovery policy — zero extra monthly cost

This public repository contains **no customer dump, connection string,
encryption key, SMTP address, Gmail payload or private backup**.

## Current live recovery evidence (2026-11-07)

- The existing Neon project has a `main` branch and a separate durable
  no-compute branch `backup-20261107-verified`, created from the production
  parent at a point in time. It is a same-provider recovery checkpoint,
  **not a permanently exported offline backup**.
- The branch is intentionally created with `no_compute=true`; it must not
  run a new paid compute service or automatically begin writing to production.
- Production full-row integrity was compared across five public PostgreSQL
  tables using an isolated ephemeral Postgres 16 restore:
  `RESTORE_ACCEPTANCE: PASS` (GitHub Actions run 42384899226).
- The weekly `Neon Isolated Restore Acceptance` scheduled workflow performs
  a **read-only** production `pg_dump`, restores only into a disposable
  local PostgreSQL service, compares complete row digests and discards the
  temporary dump. It does NOT update or replace the durable Neon branch.
- On this Neon Free account, the API reports
  `history_retention_seconds=21600` (six hours). This is NOT a long-term
  point-in-time recovery window.
- No automated deletion, paid plan upgrade or unattended creation of
  unlimited backup branches is authorized; never publish private data in
  GitHub artifacts or public commits.

## Recovery and maintenance

Check the no-compute checkpoint exists and is `ready` before relying on it.
To recover, use a separate validated Neon branch or isolated PostgreSQL target,
never overwrite live `main` during a rehearsal. Verify table inventory, exact
row counts, and full-row hashes prior to any switch of application DSNs.

A single saved branch can become stale. Scheduled independent restore drills
are health evidence, not new long-lived backup copies. Any future rotation
must enforce free branch/storage quotas, require safe retention decisions,
and avoid automatic destructive deletion of old recovery points.

The existing SMTP and Google reply safety gates remain disabled; database
backup tests never send customer messages.
