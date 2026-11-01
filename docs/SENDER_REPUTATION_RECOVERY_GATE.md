# Sender reputation recovery gate — approval required (2026-11-01)

This is a **proposal, not an enabled runtime bypass**. The production 15% failure circuit remains unchanged.

## Measured baseline
- Historical SMTP acceptances: 15; confirmed final delivery failures: 4; currently delayed: 0. The fourth failure is the later final DSN for a recipient whose server originally refused connections (111); two earlier delay DSNs are preserved as the same message's history.
- Failure ratio: 4 / 15 = 26.67%; the sender is automatically paused.
- To fall strictly below the unchanged 15% threshold with 4 historical failures would require at least 27 genuine total accepted attempts (12 more). The circuit correctly prevents using new unsolicited sends merely to inflate the denominator. A count of SMTP acceptances is not proof of inbox delivery.
- Existing failed recipients are suppressed; NXDOMAIN and relay-denied domains are quarantined; accepted-but-delayed messages are never retried after DATA.

## Recipient legal gate
- Existing 16 addresses: 15 previously contacted, 1 OSM/MX candidate without verified legal evidence; 0 currently eligible.
- Türkiye Ministry of Trade: https://ticaret.gov.tr/ic-ticaret/ticari-elektronik-iletiler/genel-bilgiler
- İYS rules: https://iys.org.tr/iys/yonetmelik
- Under the tacir/esnaf pre-consent exception, registration of the recipient's contact address in İYS and pre-send opt-out status checking still apply. For consumers, verified consent is generally required. MX or a published corporate email is not legal authority.
- A suppression/opt-out, previous claim, recipient bounce or unresolved message uncertainty always wins.

## Recovery prerequisites (not yet met)
1. Source of each failure reviewed; proof linked privately and verified by an authorized sender operator. No deletions or synthetic "success" records.
2. Current sender authentication, domain reputation and delivery diagnostics checked using existing no-cost provider tools; confirm any delivery issue is resolved, not simply that DNS now resolves.
3. At least one *new* recipient has independently documented, current legal permission/merchant verification and IYS record + opt-out check where applicable.
4. Written owner approval for a **separate, narrowly bounded probation policy** after a security review; never change the normal historical 15% threshold or history counters.
5. Synthetic PostgreSQL concurrent-claim, freeze-on-uncertainty, legal-eligibility, quota, domain quarantine and Telegram receipt tests pass; allow no real mail during rehearsal.
6. Only then consider one owner-authorized probation contact at a time, with immediate hard stop on any complaint or new DSN failure, and visible rollback. Do not auto-enable probation based on test success.

## Rollback
- Keep legacy historical rows and immutable send claims.
- Disable the proposed probation switch; the default 15% hard circuit still blocks new sends.
- Maintain hourly scanning, DSN/reply read-only monitoring, Telegram reports and independent CRM history synchronization.
- Revert only added code if needed; never delete the old 15 accepted claims or 4 DSN feedback entries.

**Current decision:** sender remains PAUSED; no live probation or new customer email is authorized.
