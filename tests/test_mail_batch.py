import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from leadhunter.automatic_mail import template_mail, compose_mail, check_config
from leadhunter.mail_batch import BacklogStore, run


class TemplateMailTests(unittest.TestCase):
    def test_template_is_personalized_by_business_and_sector(self):
        for category in ('Oto yıkama','Kuaför/berber','Güzellik salonu'):
            lead={'name':'Örnek '+category,'category':category,'website':''}
            mail=template_mail(lead)
            self.assertIn(lead['name'],mail['subject'])
            self.assertIn(lead['name'],mail['body'])
            self.assertIn('Faultline Studio',mail['body'])
            self.assertNotIn('web siteniz yok',mail['body'])
            self.assertNotIn('TL',mail['body'])
            self.assertLess(len(mail['body']),2200)

    def test_existing_site_receives_automation_instead_of_website_pitch(self):
        mail=template_mail({'name':'Örnek','category':'Kuaför/berber','website':'https://example.invalid'})
        self.assertIn('randevu',mail['subject'])
        self.assertNotIn('web sitesi hazırlayabilirim',mail['body'])

    def test_template_mode_does_not_use_ai_or_require_key(self):
        env={'AUTO_MAIL_ENABLED':'true','REVIEW_DATABASE_URL':'fixture',
             'GMAIL_SENDER_ADDRESS':'fixture@gmail.com','GMAIL_APP_PASSWORD':'abcdefghijklmnop'}
        check_config(env)
        with patch('leadhunter.automatic_mail.draft_mail') as ai:
            self.assertIn('body',compose_mail({'name':'Örnek'},env,None))
            ai.assert_not_called()

    def test_subject_cannot_inject_headers(self):
        mail=template_mail({'name':'Örnek\nBcc: unknown@example.invalid\r\n'})
        self.assertNotIn('\n',mail['subject'])
        self.assertNotIn('\r',mail['subject'])

    def test_backlog_excludes_sent_rejected_held_or_claimed(self):
        db=MagicMock();cur=db.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[]
        self.assertEqual(BacklogStore(MagicMock(db=db)).backlog(),[])
        sql=cur.execute.call_args.args[0]
        self.assertIn("status IN ('review','email_pending')",sql)
        self.assertIn("NOT IN ('sending','accepted')",sql)
        self.assertIn("IN ('draft','skipped')",sql)

    def test_backlog_reopen_never_resets_smtp_claim(self):
        db=MagicMock()
        BacklogStore(MagicMock(db=db)).reopen_unsent({'id':'node/1'})
        sql=db.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
        self.assertIn("IN ('draft','skipped')",sql)
        self.assertIn("NOT IN ('sending','accepted')",sql)

    def test_catchup_refreshes_previous_business_and_delivers_without_ai(self):
        db=MagicMock();cur=db.cursor.return_value.__enter__.return_value
        cur.fetchall.return_value=[('accepted',1)]
        store=MagicMock();store.backlog.return_value=[{'id':'node/1','name':'Previous','category':'Kuaför/berber'}]
        store.pending_reports.return_value=[]
        raw=[{'type':'node','id':1,'tags':{'name':'Previous','shop':'hairdresser','email':'previous@example.invalid'}}]
        def opener(req,timeout):
            if 'telegram' in req.full_url:
                return io.BytesIO(b'{"ok":true,"result":true}')
            raise AssertionError('No extra network')
        with tempfile.TemporaryDirectory() as tmp, patch(
            'leadhunter.mail_batch.connect_private_database',return_value=db),patch(
            'leadhunter.mail_batch.BacklogStore',return_value=store),patch(
            'leadhunter.mail_batch.get_osm',return_value=raw),patch(
            'leadhunter.mail_batch.deliver') as send,patch(
            'leadhunter.mail_batch.flush_reports',return_value=1):
            env={'AUTO_MAIL_ENABLED':'true','MAIL_DRAFT_MODE':'template','REVIEW_DATABASE_URL':'fixture',
                 'GMAIL_SENDER_ADDRESS':'fixture@gmail.com','GMAIL_APP_PASSWORD':'abcdefghijklmnop',
                 'TELEGRAM_BOT_TOKEN':'fixture','TELEGRAM_CHAT_ID':'123','STATE_FILE':str(Path(tmp)/'seen.json')}
            self.assertEqual(run(env,opener,lambda *_:None),{'accepted':1})
            self.assertEqual(send.call_count,1)
            self.assertEqual(send.call_args.args[0]['email'],'previous@example.invalid')
        db.close.assert_called_once()
