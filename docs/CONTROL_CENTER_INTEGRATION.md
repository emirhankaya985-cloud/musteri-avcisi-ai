# Müşteri Avcısı — existing project integration ownership contract

This is an additive **read-only first phase**, not an unsafe data migration or a new service. The 2026-10-29 owner-dispatched 15 SMTP acceptances are real and must never be treated as 15 inbox deliveries.

| Resource | Current system of record | Allowed integration | Forbidden duplicate action |
|---|---|---|---|
| Prospect research / frozen outgoing recipient claims / legal evidence / Gmail feedback | Müşteri Avcısı `owner_leads`, source private Neon | Count/aggregate/owner report | No new SiteNöbet SMTP sender; never requeue the 15 historic recipients |
| CRM archive and authorized uptime / SSL monitors | İşletmePilot `business_leads`, `monitors` and checks, independent Neon | Fixed public health GET; later authenticated read-only dashboard with verified organization mapping | No guessed customer joins, no second outbound mail job |
| Google Business Profile location IDs, reviews and AI reply drafts | `yorum-pilot.ai` `business_locations`, `reviews_cache`, `ai_drafts`, independent Neon | Fixed public `/healthz` GET; later authorized per-organization API adapter | No duplicate draft engine; no Google reply publication |
| Owner notification + daily reporting | Existing Müşteri Avcısı Telegram owner channel | Append source-labeled HTTP readiness to existing daily summary; no new Telegram bot | No second daily report sender or duplicate notification |

## Verified safety gates

- Source GitHub workflows for hourly scan, owner catch-up and verified batch all explicitly set `AUTO_MAIL_ENABLED: 'false'`. The verified batch approval flag is disabled. Telegram poll uses `OWNER_APPROVED_MAIL_ENABLED: 'false'`.
- Only the existing Müşteri Avcısı database remains responsible for outbound claims. SiteNöbet default SMTP sender is retired in `backend/app/business_mail.py`, with the pipeline checking the same default sender before any live mail action. Never switch `BUSINESS_SINGLE_SENDER` as a workaround.
- An ordinary HTTP 200 indicates **HTTP only**, not authorized CRM access, site monitor success, review API approval, OAuth, or Google publication.
- `yorum-pilot.ai` PR #1 remains draft until server-side token encryption readiness, production database migration and API/owner authorization are separately confirmed. Existing `0002_telegram` production migration must not be confused with isolated `0003_google_oauth` tests.
- Current existing production databases are not changed by the read-only controller. Neither archive CRM nor review tables are copied across projects. SiteNöbet must operate only on user-authorized domains.

## Recovery and production promotion

1. Preserve all three current Neon databases and their original owners. Only the YorumPilot snapshot `snap-wandering-term-bappqwqd` was independently listed on 2026-11-02; no Neon snapshots were found for the other two projects. **Do not migrate these databases until a zero-cost, verified recovery point exists**.
2. Confirm Render workspace and verify the existing two services per project, auth and environment-key presence (never print secret values).
3. Confirm organization IDs and GBP location identities from authenticated records. Never infer tenant identity from a fuzzy business name.
4. Only then consider authenticated, strictly read-only data adapters and compare counts, with consent/opt-out/SMTP/Telegram receipts immutable.
5. Use old source services for rollback; preserve existing GitHub workflows and Render deployments until the replacement is independently accepted.
6. Keep Google reply publication, independent İşletmePilot SMTP and all new real customer SMTP **off**.

No new paid infrastructure or new deployments are part of this phase.
