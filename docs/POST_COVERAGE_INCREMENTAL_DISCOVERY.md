## First coverage versus continuing OSM business discovery (2026-11-16)

Historical milestone: **402/402** small cells confirmed against a real,
checksum-verified one-time Geofabrik OSM snapshot. Its source timestamp was
**2026-11-15T21:22:28Z** (00:22:28 Istanbul time on November 16). This
historical milestone is never reset, re-queried by hourly Overpass, or counted
as 402 new live API reads.

The independent `OSM Incremental Business Discovery (Private, No Outreach)`
workflow in `.github/workflows/osm-incremental-discovery.yml` checks the last
verified source timestamp before any external download. It uses a minimum
three-day interval and Monday/Thursday UTC scheduling. Only when due does it
retrieve one free Geofabrik country PBF with verified checksum and embedded
source timestamp, then clip existing Istanbul pilot geography as a **single
source-level differential comparison**, not 402 tile scan requests. New OSM
node/way/relation IDs go into existing private Neon `owner_leads`; changed
attributes of existing IDs are staged for manual review, without overwriting
historical contact eligibility or mail/owner decisions. Deleted or missing
OSM entries are **not** automatically deleted from CRM. Each source snapshot
is recorded with digest and timestamp in
`owner_osm_incremental_runs`; comparisons of the same source date are
idempotently skipped. Official OSM data attribution and provider terms apply.

The hourly `Telegram Lead Digest` workflow remains active and independently
records its successful **no-query source skip** as `skipped` in private
`owner_scan_attempts`. Its private CRM duplicate review, Neon mirror and
Gmail watcher remain alive and do not require public Overpass queries. The
read-only freshness watcher now examines real hourly attempt receipts and
OSM source age **separately**; a fresh no-query hourly heartbeat is not proof
that new businesses were checked that same hour. Source data older than ten
days is flagged stale until the next successful incremental refresh.

Panel contract: `control_center_musteri_incremental_v1` has
`successful_incremental_runs`, `new_leads_from_incremental`,
`last_incremental_source_at`, `last_incremental_verified_at`,
`changed_businesses_need_review`, `initial_source_at`. A NULL source
date means genuinely unverified, not zero freshness. The new private
candidate-change table is not granted to a panel role, only the aggregate view.

**No marketing SMTP or routine Telegram**; all source and database checks
fail closed on missing proof. Until a genuinely newer downloaded source is
processed, no new OSM discoveries are claimed from this incremental channel.
