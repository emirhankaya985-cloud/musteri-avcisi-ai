"""Retry private owner reports independently of OSM. Never send business mail."""
import os
from urllib.request import urlopen
from .automatic_mail import AutoMailStore, flush_reports
from .review_private import ReviewStore, connect_private_database


def run(env=None, output=print):
    env = os.environ if env is None else env
    if not env.get('TELEGRAM_BOT_TOKEN') or not str(env.get('TELEGRAM_CHAT_ID', '')).isdigit():
        raise RuntimeError('Owner report credentials missing or invalid')
    db = connect_private_database(env.get('REVIEW_DATABASE_URL'))
    count = 0
    try:
        store = AutoMailStore(ReviewStore(db))
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
