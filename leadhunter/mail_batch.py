"""Owner-requested catch-up over existing business candidates, plus five new ones."""
import os
import json
from urllib.request import urlopen
from .automatic_mail import AutoMailStore, check_config, deliver, flush_reports, private_operation
from .review_private import ReviewStore, connect_private_database
from .core import lead_from_osm, bbox_parse, DEFAULT_BBOX, get_osm, select_leads, read_seen
from pathlib import Path


class BacklogStore(AutoMailStore):
    @private_operation
    def backlog(self):
        with self.db.cursor() as cur:
            cur.execute("SELECT osm_id,lead_data FROM owner_leads WHERE status IN ('review','email_pending') "
                        "AND COALESCE(lead_data->'_auto_mail'->>'state','draft') IN ('draft','skipped') "
                        "AND COALESCE(lead_data->'_mail'->>'state','draft') NOT IN ('sending','accepted') "
                        'ORDER BY updated_at LIMIT 201')
            rows=cur.fetchall()
        if len(rows)>200:
            raise RuntimeError('Backlog exceeds explicit catch-up limit')
        return [{**(json.loads(data) if isinstance(data,str) else data),'id':lid} for lid,data in rows]

    @private_operation
    def reopen_unsent(self, lead):
        # Owner approved catch-up. Only untouched/manual drafts or skipped records
        # can be reopened. Any SMTP claim, rejection or hold remains excluded.
        with self.db.cursor() as cur:
            cur.execute("UPDATE owner_leads SET status='review',lead_data=lead_data-'_auto_mail' "
                        "WHERE osm_id=%s AND status IN ('review','email_pending') "
                        "AND COALESCE(lead_data->'_auto_mail'->>'state','draft') IN ('draft','skipped') "
                        "AND COALESCE(lead_data->'_mail'->>'state','draft') NOT IN ('sending','accepted')",
                        (lead['id'],))


def run(env=None, opener=urlopen, output=print):
    env=os.environ if env is None else env
    check_config(env)
    limit = int(env.get("MAIL_BATCH_LIMIT", "15"))
    if not 1 <= limit <= 15:
        raise RuntimeError("Mail catch-up limit must be between 1 and 15")
    token,owner=env.get('TELEGRAM_BOT_TOKEN'),env.get('TELEGRAM_CHAT_ID')
    if not token or not owner or not str(owner).isdigit():
        raise RuntimeError('Private owner Telegram configuration missing')
    connection=connect_private_database(env['REVIEW_DATABASE_URL'])
    try:
        store=BacklogStore(ReviewStore(connection))
        old=store.backlog()
        bbox=bbox_parse(env.get('SCAN_BBOX') or DEFAULT_BBOX)
        try:
            raw=get_osm(bbox,opener)
        except RuntimeError:
            from .osm_direct import get_osm_direct
            raw=get_osm_direct(bbox,seen_ids={lead['id'] for lead in old},opener=opener)
        fresh={lead['id']:lead for row in raw if (lead:=lead_from_osm(row))}
        combined={lead['id']:{**lead,**fresh.get(lead['id'],{})} for lead in old}
        seen=read_seen(Path(env.get('STATE_FILE','data/seen.json')))
        for lead in select_leads(raw,seen,maximum=200):
            combined.setdefault(lead['id'],lead)
        output(f'OWNER_CATCHUP: previous={len(old)}; current_plus_previous={len(combined)}')
        total=0
        while store.pending_reports():
            total+=flush_reports(store,env,opener)
        attempted = 0
        for lead in combined.values():
            from .outreach import valid_recipient
            if not valid_recipient(str(lead.get("email") or "").strip().lower()):
                continue
            if attempted >= limit:
                break
            attempted += 1
            store.reopen_unsent(lead)
            deliver(lead,store,env,opener)
            total+=flush_reports(store,env,opener)
        with connection.cursor() as cur:
            cur.execute("SELECT lead_data->'_auto_mail'->>'state',count(*) FROM owner_leads "
                        "WHERE lead_data ? '_auto_mail' GROUP BY 1")
            counts=dict(cur.fetchall())
        summary='Mail özeti: '+', '.join(f'{k}={v}' for k,v in sorted(counts.items()))
        output(summary)
        from .telegram_buttons import api
        api(token,'sendMessage',{'chat_id':owner,'text':summary+
            '\nSMTP kabulü gelen kutusuna teslim kanıtı değildir. Eksik adresler tahmin edilmedi.'},opener)
        return counts
    except Exception:
        raise RuntimeError('Owner mail catch-up failed; private details redacted') from None
    finally:
        connection.close()


if __name__=='__main__':
    run()
