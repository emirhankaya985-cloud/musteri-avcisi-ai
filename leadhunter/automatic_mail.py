"""Bounded direct outreach explicitly requested by the owner on 2026-10-29.

All recipient addresses, frozen content and delivery state remain private.
SMTP acceptance is not evidence of inbox delivery. Never retry uncertain mail.
"""
import hashlib
import html
import json
from functools import wraps
from .outreach import draft_mail, send_mail, valid_recipient
from .gmail_selftest import sender_credentials


def check_config(env):
    if env.get('AUTO_MAIL_ENABLED') != 'true':
        raise RuntimeError('Automatic mail is disabled')
    if not env.get('REVIEW_DATABASE_URL'):
        raise RuntimeError('Automatic mail requires private storage')
    sender_credentials(env)
    mode = env.get('MAIL_DRAFT_MODE', 'template')
    if mode not in ('template', 'ai'):
        raise RuntimeError('Invalid mail draft mode')
    if mode == 'ai':
        if not all(env.get(k) for k in ('MAIL_AI_API_KEY','MAIL_AI_MODEL','MAIL_AI_URL')):
            raise RuntimeError('AI mail configuration missing; no business email sent')
        if not env['MAIL_AI_URL'].startswith('https://'):
            raise RuntimeError('AI mail endpoint must use HTTPS')


def template_mail(lead):
    from .core import recommend
    name = ' '.join(str(lead.get('name') or 'İşletmeniz').split())[:100]
    rec = recommend(lead)
    if rec['focus'] == 'website':
        subject = f'{name} için web sitesi tasarım önerisi'
        proposal = (f"{name} için {rec['premium_scope']} içeren, işletmenizin kimliğine "
                    'uygun bir web sitesi hazırlayabilirim. Ziyaretçilerin hizmetlerinizi '
                    'inceleyip size kolayca ulaşabileceği sade bir yapı düşünüyorum.')
    else:
        subject = f'{name} için randevu ve talep takibi önerisi'
        proposal = (f"{name} için değerlendirilebilecek bir çalışma: {rec['idea']}. "
                    'Önce mevcut işleyişinizi öğrenip yalnızca ihtiyaç duyduğunuz '
                    'adımlara uygun bir çözüm hazırlamak isterim.')
    return {'subject':subject,'body':
            f'Merhaba {name} ekibi,\n\n'
            'Ben Emirhan Kaya. Faultline Studio adıyla web geliştirme ve iş süreçlerini '
            'kolaylaştıran yazılım çözümleri üzerine çalışıyorum.\n\n'
            + proposal + '\n\n'
            'İlginizi çekerse size özel kısa bir örnek hazırlayıp paylaşabilirim. '
            'Böyle bir çalışmayı değerlendirmek ister misiniz?\n\n'
            'Bu konuda tekrar iletişim kurulmasını istemiyorsanız yanıtınızda '
            'belirtmeniz yeterli.\n\n'
            'İyi çalışmalar,\nEmirhan Kaya\nFaultline Studio'}


def compose_mail(lead, env, opener):
    if env.get('MAIL_DRAFT_MODE', 'template') == 'ai':
        return draft_mail(lead, env, opener)
    return template_mail(lead)


def report_text(lead, record):
    esc = lambda value: html.escape(str(value))
    state = record['state']
    label = {'accepted':'✅ Gmail SMTP kabul etti; gelen kutusu teslimi doğrulanmadı.',
             'sending':'⚠️ Sonuç belirsiz; otomatik tekrar kapalı. Gönderilenler kontrol edilmeli.',
             'uncertain':'⚠️ Sonuç belirsiz; otomatik tekrar kapalı. Gönderilenler kontrol edilmeli.',
             'skipped':'⏭️ Mail atlanmış: geçerli e-posta adresi bulunamadı.',
             'duplicate':'⏭️ Aynı alıcı daha önce işlendi; tekrar mail atılmadı.'}[state]
    lines = ['<b>Müşteri Avcısı AI — Mail sonucu</b>',
             '🏪 '+esc(lead.get('name','İşletme')),label]
    if record.get('recipient'):
        lines.append('Alıcı: '+esc(record['recipient']))
    if record.get('subject'):
        lines.extend(['Konu: '+esc(record['subject']), '\n'+esc(record['body'])])
    return '\n'.join(lines)


def private_operation(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except Exception:
            raise RuntimeError('Private automatic mail operation failed; details redacted') from None
    return wrapped


class AutoMailStore:
    def __init__(self, review):
        self.db = review.db

    @private_operation
    def load(self, lead_id):
        with self.db.cursor() as cur:
            cur.execute('SELECT lead_data,status FROM owner_leads WHERE osm_id=%s',(lead_id,))
            row = cur.fetchone()
        if not row:
            return None
        data = json.loads(row[0]) if isinstance(row[0],str) else row[0]
        return data, row[1]

    @private_operation
    def actionable(self, lead_id):
        existing = self.load(lead_id)
        if not existing:
            return True
        data,status = existing
        if status != 'review':
            return False
        return (data.get('_auto_mail', {}).get('state', 'draft') == 'draft'
                and data.get('_mail', {}).get('state') not in ('sending','accepted'))

    @private_operation
    def prepare(self, lead, env, opener):
        # Private registration is immutable once a mail record exists.
        with self.db.cursor() as cur:
            cur.execute("INSERT INTO owner_leads (osm_id,lead_data,status) VALUES (%s,%s::jsonb,'review') "
                        'ON CONFLICT (osm_id) DO NOTHING',(lead['id'],json.dumps(lead)))
        data,status = self.load(lead['id'])
        if status in ('rejected','deferred','email_sent'):
            return None
        if data.get('_auto_mail'):
            return data['_auto_mail']
        recipient = str(lead.get('email') or '').strip().lower()
        if valid_recipient(recipient):
            record = compose_mail(lead,env,opener)
            record.update(recipient=recipient,state='draft')
        else:
            record = {'state':'skipped'}
        record['id'] = hashlib.sha256(('automatic:'+lead['id']).encode()).hexdigest()[:24]
        with self.db.cursor() as cur:
            cur.execute("UPDATE owner_leads SET lead_data=jsonb_set(lead_data,'{_auto_mail}',%s::jsonb) "
                        "WHERE osm_id=%s AND status='review' AND NOT (lead_data ? '_auto_mail')",
                        (json.dumps(record),lead['id']))
        data,status = self.load(lead['id'])
        return data.get('_auto_mail')

    @private_operation
    def claim(self, lead_id):
        # Serialize recipient comparison + claiming across concurrent workers.
        with self.db.transaction():
            with self.db.cursor() as cur:
                cur.execute('SELECT pg_advisory_xact_lock(789654321)')
                cur.execute('SELECT lead_data,status FROM owner_leads WHERE osm_id=%s FOR UPDATE',(lead_id,))
                row = cur.fetchone()
                if not row:
                    return None
                data = json.loads(row[0]) if isinstance(row[0],str) else row[0]
                record = data.get('_auto_mail') or {}
                if row[1] != 'review' or record.get('state') != 'draft':
                    return None
                recipient = record['recipient']
                cur.execute("SELECT osm_id FROM owner_leads WHERE osm_id<>%s AND ("
                            "(lower(lead_data->'_auto_mail'->>'recipient')=%s AND "
                            "lead_data->'_auto_mail'->>'state' IN ('sending','accepted','uncertain')) OR "
                            "(lower(lead_data->'_mail'->>'recipient')=%s AND "
                            "lead_data->'_mail'->>'state' IN ('sending','accepted'))) LIMIT 1",
                            (lead_id,recipient,recipient))
                record['state'] = 'duplicate' if cur.fetchone() else 'sending'
                cur.execute("UPDATE owner_leads SET lead_data=jsonb_set(lead_data,'{_auto_mail}',%s::jsonb),"
                            'updated_at=now() WHERE osm_id=%s',(json.dumps(record),lead_id))
        # Caller may use SMTP only AFTER the claim transaction commits.
        return record if record['state']=='sending' else None

    @private_operation
    def finish(self, lead_id, state):
        with self.db.cursor() as cur:
            cur.execute("UPDATE owner_leads SET lead_data=jsonb_set(lead_data,'{_auto_mail,state}',%s::jsonb), "
                        "status=CASE WHEN %s='accepted' THEN 'email_sent' ELSE status END,updated_at=now() "
                        "WHERE osm_id=%s AND lead_data->'_auto_mail'->>'state'='sending'",
                        (json.dumps(state),state,lead_id))

    @private_operation
    def pending_reports(self):
        with self.db.cursor() as cur:
            cur.execute("SELECT osm_id,lead_data FROM owner_leads WHERE "
                        "lead_data->'_auto_mail'->>'state' IN ('accepted','uncertain','sending','skipped','duplicate') "
                        "AND NOT (lead_data->'_auto_mail' ? 'telegram_reported') ORDER BY updated_at LIMIT 5")
            rows = cur.fetchall()
        return [(lid,json.loads(data) if isinstance(data,str) else data) for lid,data in rows]

    @private_operation
    def reported(self, lead_id, message_id):
        with self.db.cursor() as cur:
            cur.execute("UPDATE owner_leads SET lead_data=jsonb_set(lead_data,'{_auto_mail,telegram_reported}',%s::jsonb) "
                        'WHERE osm_id=%s',(json.dumps(message_id),lead_id))


def deliver(lead, store, env, opener, mail_sender=send_mail):
    record = store.prepare(lead,env,opener)
    if not record or record['state'] != 'draft':
        return
    record = store.claim(lead['id'])
    if not record:
        return
    try:
        mail_sender(record,{**env,'OWNER_APPROVED_MAIL_ENABLED':'true'})
    except RuntimeError:
        store.finish(lead['id'],'uncertain')
        return
    store.finish(lead['id'],'accepted')


def flush_reports(store, env, opener):
    count = 0
    for lead_id,lead in store.pending_reports():
        text = report_text(lead,lead['_auto_mail'])
        # Split after HTML escaping so even long names/text preserve full content.
        # HTML messages are sent in short plain-text-compatible chunks below.
        import html as html_module
        plain = html_module.unescape(text.replace('<b>','').replace('</b>',''))
        from .telegram_buttons import api
        last_id = None
        for start in range(0,len(plain),3000):
            result = api(env['TELEGRAM_BOT_TOKEN'],'sendMessage',{
                'chat_id':env['TELEGRAM_CHAT_ID'],'text':plain[start:start+3000],
                'disable_web_page_preview':True},opener)
            if not isinstance(result,dict) or type(result.get('message_id')) is not int:
                raise RuntimeError('Automatic mail report delivery not confirmed')
            last_id = result['message_id']
        store.reported(lead_id,last_id)
        count += 1
    return count
