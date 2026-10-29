"""Owner-dispatched batch of externally researched public business contacts.

The batch is supplied as a GitHub Secret, never repository content or an artifact.
All history and mail contents stay in the existing private database.
"""
import hashlib
import json
import os
from urllib.parse import urlsplit
from urllib.request import urlopen
from .automatic_mail import AutoMailStore, check_config, deliver, flush_reports
from .outreach import valid_recipient
from .review_private import ReviewStore, connect_private_database
from .telegram_buttons import api
from .gmail_selftest import sender_credentials


def parse_batch(raw):
    rows = json.loads(raw)
    if not isinstance(rows, list) or not 1 <= len(rows) <= 15:
        raise ValueError('Owner batch must contain between 1 and 15 contacts')
    result, recipients, hosts = [], set(), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid researched business')
        name = row.get('name', '')
        recipient = str(row.get('email', '')).strip().lower()
        website = row.get('website', '')
        source = row.get('email_source', '')
        category = row.get('category', '')
        site, evidence = urlsplit(website), urlsplit(source)
        host = (site.hostname or '').lower().removeprefix('www.')
        evidence_host = (evidence.hostname or '').lower().removeprefix('www.')
        if (not isinstance(name, str) or not 1 <= len(name) <= 100
                or any(c in name for c in '\r\n\x00')
                or not valid_recipient(recipient)
                or site.scheme != 'https' or evidence.scheme != 'https'
                or not host or host != evidence_host
                or site.username or site.password or evidence.username or evidence.password
                or site.port not in (None,443) or evidence.port not in (None,443)
                or category not in ('Oto yıkama','Kuaför/berber','Güzellik salonu')
                or row.get('source_verified') is not True
                or recipient in recipients or host in hosts):
            raise ValueError('Invalid or duplicate researched business contact')
        recipients.add(recipient)
        hosts.add(host)
        result.append({'id':'website/'+hashlib.sha256(host.encode()).hexdigest()[:24],
                       'name':name,'email':recipient,'website':website,
                       'email_source':source,'category':category,
                       'source_verified':True})
    return result


def run(env=None, opener=urlopen, output=print):
    env = os.environ if env is None else env
    check_config(env)
    if env.get('OWNER_VERIFIED_BATCH_APPROVED') != 'YES_SEND_UP_TO_15':
        raise RuntimeError('Owner-dispatched verified batch is not enabled')
    try:
        leads = parse_batch(env.get('OWNER_MAIL_BATCH_JSON', ''))
    except Exception:
        raise RuntimeError('Private owner batch invalid; no mail sent') from None
    if not env.get('TELEGRAM_BOT_TOKEN') or not str(env.get('TELEGRAM_CHAT_ID','')).isdigit():
        raise RuntimeError('Owner private reporting is not configured')
    sender, _ = sender_credentials(env)
    db = connect_private_database(env['REVIEW_DATABASE_URL'])
    counts = {'accepted_new':0,'already_accepted':0,'uncertain':0,'blocked':0}
    receipts = []
    try:
        store = AutoMailStore(ReviewStore(db))
        while store.pending_reports():
            flush_reports(store,env,opener)
        for lead in leads:
            before = store.load(lead['id'])
            if before and before[0].get('_auto_mail',{}).get('state') == 'accepted':
                counts['already_accepted'] += 1
                continue
            # Rejected/held/uncertain records remain protected by AutoMailStore.
            deliver(lead,store,env,opener)
            after = store.load(lead['id'])
            record = after[0].get('_auto_mail',{}) if after else {}
            state = record.get('state')
            if state == 'accepted':
                counts['accepted_new'] += 1
                receipts.append(lead['name']+' — '+record['recipient']+'\nMessage-ID: <'+record['id']+'@'+sender.split('@')[1]+'>')
            elif state in ('sending','uncertain'):
                counts['uncertain'] += 1
            else:
                counts['blocked'] += 1
            flush_reports(store,env,opener)
        summary = 'VERIFIED_BATCH: requested='+str(len(leads))+'; '+', '.join(f'{k}={v}' for k,v in counts.items())
        output(summary)
        text = 'Doğrulanmış işletme mail özeti\n'+summary+'\n\n'+'\n\n'.join(receipts)+'\n\nSMTP kabulüdür; gelen kutusuna teslim doğrulanmadı.'
        for start in range(0,len(text),3000):
            api(env['TELEGRAM_BOT_TOKEN'],'sendMessage',{'chat_id':env['TELEGRAM_CHAT_ID'],'text':text[start:start+3000]},opener)
        return counts
    except Exception:
        raise RuntimeError('Verified business mail batch failed; private details redacted; inspect private history before retry') from None
    finally:
        db.close()


if __name__ == '__main__':
    run()
