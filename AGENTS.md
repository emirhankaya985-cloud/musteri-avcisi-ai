# Codex instructions — Müşteri Avcısı AI

This repository is **public**. Read `docs/CODEX_TEST_HANDOFF.md` before editing or testing.

## Goal
Research a small OSM business sample and send **only the owner's private Telegram chat** up to five new opportunities per run. Classify missing OSM website metadata as 🔴 proposed premium website lead; recorded website metadata as 🟢 proposed automation lead. These are research hypotheses, **not verified business needs**. Produce tailored, **unsent** outreach drafts for optional manual review.

## Boundaries (mandatory)
- Never send marketing email, SMS, Telegram DM, WhatsApp or any cold outreach to businesses. No bulk sending or automated follow-ups.
- Never copy credentials, personal/customer contact lists, CRM data, recipient approvals, sent-mail history, or source repo Git history into this repository.
- Use `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, and optional private `REVIEW_DATABASE_URL` only as GitHub Actions **repository secrets** for the owner's digest and review. A separate Gmail owner-only smoke uses independent Gmail Secrets and never performs business outreach. Do not print or request secret values in issues, prompts, logs or public files.
- Never write production customer data to `data/seen.json`: public OSM object IDs only.
- Do not trigger `Telegram Lead Digest` repeatedly merely to validate code; a live run sends messages to the owner and mutates `data/seen.json`.
- Do not claim site is hosted, emails are sent, customers contacted, cron fired on time, or paid conversions happened without evidence.
- Do not silently alter production scheduling (weekdays 10:23 Europe/Istanbul = 07:23 UTC), secret names, public repository visibility, or the no-auto-outreach policy.
- Do not merge regressions or leave failed CI; if repo policies require a PR, use a branch/PR and verify it.

## Offline validation — first
From the repository root with Python 3.12+:

```bash
python tools/codex_acceptance.py
```

This runs syntax checks, every `unittest`, and a **synthetic demo** that cannot send real Telegram or contact clients. For direct debugging:

```bash
python -m unittest discover -s tests -v
python -m leadhunter demo
```

The demo is written to `dist/telegram-demo.txt` (gitignored).

## Acceptance and proof
- 🔴 missing OSM site → sector-specific premium website idea, no definitive site-absence claim.
- 🟢 recorded OSM site → sector-specific automation idea, not unverified “has no automation” claim.
- Three sectors tested, escaping of HTML, maximum five, seen-ID deduplication, partial-failure state semantics, redacted Telegram HTTP errors, Overpass fallback.
- Source data and private Secrets never included in public files.
- Existing demo-site is local **static demo only**, not an actual hosted or accepting-reservations business site.
- GitHub Actions `Offline Tests` completes **success** for the current head; confirm by direct run URL, not a screenshot or commit comment.
- `Telegram Lead Digest` can succeed with **0 new opportunities**; count is not a failure. Offline passes do not prove the current live job or scheduled event ran.
- Inspect workflows for `cron: '23 7 * * 1-5'` and confirm a real `schedule` event on an actual Monday–Friday run before claiming the scheduled delivery verified.

## Handoff response
Provide a short Turkish report with exact commit SHA, test counts, CI run links and outcomes, whether a real live digest was run and how many **new** leads were delivered, and explicit PASS / PARTIAL / FAIL for offline, live and scheduling separately. Finish with a plain-language explanation of what the system does.
