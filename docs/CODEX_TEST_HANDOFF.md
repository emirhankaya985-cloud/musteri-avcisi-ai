# Codex test handoff — Müşteri Avcısı AI

**Repo:** https://github.com/emirhankaya985-cloud/musteri-avcisi-ai
**Branch:** `main` · public · Python 3.12 · stdlib only
**Origin:** clean allowlisted copy from `emirhankaya-AFK/musteri-avcisi-ai` (private). Do not transfer old commits or private files.

## Single-command test

```bash
git status --short
python tools/codex_acceptance.py
```

The acceptance script compiles Python code, executes all offline unit tests, checks tracked-file privacy restrictions when a Git checkout is available, and renders a synthetic two-category premium Telegram digest in a **temporary directory** without network, credentials or client contact.

Optional separate commands:

```bash
python -m unittest discover -s tests -v
python -m leadhunter demo
```

Review the synthetic content in `dist/telegram-demo.txt`. That output is only a sample and must not be mistaken for real OSM discoveries.

## CodeX checks — order and expected behavior

| Gate | Check | Evidence |
| --- | --- | --- |
| 1 | All offline tests pass and no imports need paid dependencies | Command exit code 0; test count |
| 2 | 🔴 website record missing -> premium website scope by category; explicit manual verification | `tests/test_acceptance.py` and existing core tests |
| 3 | 🟢 website record present -> category-specific automation idea | Sample digest + unit tests |
| 4 | Personalized drafts contain correct business name; HTML properly escaped | Unit tests |
| 5 | Owner Telegram only, up to 5, stable de-duplication on re-run | Mock Telegram API + isolated state |
| 6 | Failed send isn't marked seen; partial success is persisted | Mock failure unit test |
| 7 | Overpass timeout/non-success handled without infinite requests | Core + fallback tests |
| 8 | Repository has no `.env`, real recipients/CRM/sent-mail ledgers, embedded tokens, Gmail mailer | Tracked-file scan + Git tree |
| 9 | Demo `demo-site/index.html` opens responsively and is labelled demo; not a live reservation/payment system | Local browser/static audit |
| 10 | `Offline Tests` workflow completes successful for HEAD | GitHub Actions run URL + SHA |
| 11 | `Telegram Lead Digest` real API, if safely/explicitly tested, reports success and delivered count | GitHub Actions log and `data/seen.json` delta |
| 12 | Weekday 10:23 Istanbul scheduler | Cron string **plus** actual `schedule`-triggered run for timing claims |

The run logic is: small Kadıköy OSM search for car washes, hairdressers and beauty salons; select up to five unseen records; send opportunity summaries **only to the user's own Telegram chat**; append public OSM IDs only after successful sends.

**Privacy/security:** No automatic outreach to leads. A sample offer is meant to be read, edited and optionally sent by the owner after checking suitability, permission, and business web presence. OSM `website` tag missing != actual website missing. Site already present != automation need confirmed. Never ship customer email addresses or secrets.

## Historical baseline, not a current claim

- As of 2026-10-24 before this handoff: `Offline Tests` and `Telegram Lead Digest` both reported GitHub `success` for commit `4d77861f74c0cd42f09301c5c7701e04aa4ae791`.
- CI run: https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40065577249
- Live digest run: https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40065577372
- Live digest logged `Gönderilen yeni fırsat: 0`; **not five**, and **not a failed Telegram connection**.
- A previous live scan had sent five owner notifications; later no-new-lead runs are expected.
- No actual `schedule`-event completion was evidenced at handoff, so scheduling execution is **unverified** even though `23 7 * * 1-5` is configured.
- Overpass public servers can time out; that is an external dependency. The scanner tries three sequential instances and must fail visibly when all are unavailable.

## Live workflow limits

There are two GitHub repository secrets: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Check presence through GitHub Settings if necessary, **never retrieve/print secret values**. Live tests should occur only in the repository's own workflow, on the authorized owner account, with no more than one deliberate run per verification. A successful run with zero opportunities proves the scan logic ran, not that any message was delivered.

GitHub workflow: https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/workflows/lead-digest.yml
CI workflow: https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/workflows/ci.yml

## Result format

Write `docs/CODEX_TEST_RESULTS.md` **only after you actually ran tests**. Record HEAD SHA, commands, test count, CI run IDs with success/failure, real live count (or 'not run'), confirmed schedule run IDs (or 'not observed'), risks, fixes, and next actions. Never mark a gate PASS by inference or because of an older run. Do not store Secrets or customer details in the report.
