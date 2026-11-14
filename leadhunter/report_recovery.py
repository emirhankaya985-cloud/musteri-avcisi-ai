"""Retry private owner reports independently of OSM. Never send business mail."""
import os
from urllib.request import urlopen
from .automatic_mail import AutoMailStore, flush_reports
from .review_private import ReviewStore, connect_private_database


def run(env=None, output=print):
    env = os.environ if env is None else env
    if env.get('OWNER_MAIL_REPORT_NOTICES') != 'false' and (
            not env.get('TELEGRAM_BOT_TOKEN') or
            not str(env.get('TELEGRAM_CHAT_ID', '')).isdigit()):
        raise RuntimeError('Owner report credentials missing or invalid')
    db = connect_private_database(env.get('REVIEW_DATABASE_URL'))
    count = 0
    try:
        store = AutoMailStore(ReviewStore(db))
        if env.get("OWNER_MAIL_REPORT_NOTICES") == "false":
            # Audit-only mode: old SMTP records and unsent Telegram receipts
            # remain immutable. Do not block live research on message backlog.
            pending = len(store.pending_reports())
            output("OWNER_REPORT_RECOVERY: mode=crm_only; pending=" +
                   str(pending) + "; telegram_sent=0; business_mail_sent=0")
            return 0
        # Bounded drain; successful reports are persisted, never SMTP-retried.
        for _ in range(20):
            batch = flush_reports(store, env, urlopen)
            count += batch
            if batch == 0:
                break
        if store.pending_reports():
            raise RuntimeError('Owner report backlog remains; new scan blocked')
    finally:
        db.close()
    output(f'OWNER_REPORT_RECOVERY: confirmed={count}; business_mail_sent=0')
    return count


if __name__ == '__main__':
    run()
