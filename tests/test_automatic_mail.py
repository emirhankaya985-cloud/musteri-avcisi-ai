import io
import json
import unittest
from unittest.mock import MagicMock, patch
from leadhunter.automatic_mail import AutoMailStore, check_config, deliver, flush_reports, report_text


class MemoryStore:
    def __init__(self, recipient='business@example.invalid'):
        self.record={'state':'draft','recipient':recipient,'id':'a'*24,
                     'subject':'Örnek konu','body':'Merhaba <Örnek>\nİşletmeye özel tam mail.'}
        self.claims=0
        self.notified=False
        self.log=[]
    def prepare(self,*args):
        return self.record
    def claim(self,*args):
        if self.record['state']!='draft':
            return None
        self.record['state']='sending'; self.claims+=1; self.log.append('committed_claim')
        return self.record
    def finish(self,lid,state):
        self.record['state']=state;self.log.append(state)
    def pending_reports(self):
        return [] if self.notified else [('node/1',{'name':'Örnek <işletme>','_auto_mail':self.record})]
    def reported(self,*args):
        self.notified=True


class AutomaticMailTests(unittest.TestCase):
    def setUp(self):
        self.env={'MAIL_DRAFT_MODE':'ai','AUTO_MAIL_ENABLED':'true','REVIEW_DATABASE_URL':'postgresql://fixture/?sslmode=require',
                  'GMAIL_SENDER_ADDRESS':'sender@gmail.com','GMAIL_APP_PASSWORD':'abcdefghijklmnop',
                  'MAIL_AI_API_KEY':'fixture','MAIL_AI_MODEL':'fixture','MAIL_AI_URL':'https://example.invalid',
                  'TELEGRAM_BOT_TOKEN':'fixture','TELEGRAM_CHAT_ID':'123'}

    def test_configuration_must_be_complete_before_network(self):
        check_config(self.env)
        for key in ('MAIL_AI_API_KEY','REVIEW_DATABASE_URL','GMAIL_APP_PASSWORD'):
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                check_config({**self.env,key:''})

    def test_one_mail_without_callback_then_exact_private_report(self):
        store=MemoryStore(); calls=[]
        def mail(record,env):
            self.assertEqual(store.log,['committed_claim'])
            calls.append(dict(record))
        deliver({'id':'node/1'},store,self.env,None,mail)
        self.assertEqual(store.record['state'],'accepted')
        def opener(req,timeout):
            payload=json.loads(req.data)
            self.assertEqual(payload['chat_id'],'123')
            self.assertIn(calls[0]['body'],payload['text'])
            self.assertIn('business@example.invalid',payload['text'])
            self.assertNotIn('reply_markup',payload)
            return io.BytesIO(b'{"ok":true,"result":{"message_id":7}}')
        self.assertEqual(flush_reports(store,self.env,opener),1)
        deliver({'id':'node/1'},store,self.env,None,mail)
        self.assertEqual(len(calls),1)
        self.assertEqual(flush_reports(store,self.env,opener),0)

    def test_failed_telegram_report_does_not_resend_mail(self):
        store=MemoryStore();mail=MagicMock()
        deliver({'id':'node/1'},store,self.env,None,mail)
        with self.assertRaises(RuntimeError):
            flush_reports(store,self.env,lambda *a,**k:io.BytesIO(b'{"ok":false}'))
        self.assertFalse(store.notified)
        deliver({'id':'node/1'},store,self.env,None,mail)
        self.assertEqual(mail.call_count,1)
        self.assertEqual(flush_reports(store,self.env,lambda *a,**k:io.BytesIO(
            b'{"ok":true,"result":{"message_id":8}}')),1)

    def test_unknown_smtp_result_never_retries(self):
        store=MemoryStore();mail=MagicMock(side_effect=RuntimeError('uncertain'))
        deliver({'id':'node/1'},store,self.env,None,mail)
        deliver({'id':'node/1'},store,self.env,None,mail)
        self.assertEqual(mail.call_count,1)
        self.assertEqual(store.record['state'],'uncertain')
        self.assertIn('Sonuç belirsiz',report_text({},store.record))

    def test_invalid_recipient_skipped_without_ai(self):
        db=MagicMock();cur=db.cursor.return_value.__enter__.return_value
        store=AutoMailStore(MagicMock(db=db))
        store.load=MagicMock(side_effect=[({'name':'Örnek'},'review'),
                                          ({'_auto_mail':{'state':'skipped'}},'review')])
        with patch('leadhunter.automatic_mail.draft_mail') as ai:
            self.assertEqual(store.prepare({'id':'node/1','email':'invalid'},self.env,None)['state'],'skipped')
            ai.assert_not_called()
        self.assertIn('jsonb_set',cur.execute.call_args.args[0])

    def test_completed_and_declined_businesses_are_not_selected(self):
        store=AutoMailStore(MagicMock())
        for state in ('accepted','uncertain','sending','skipped','duplicate'):
            store.load=MagicMock(return_value=({'_auto_mail':{'state':state}},'review'))
            self.assertFalse(store.actionable('node/1'))
        for status in ('rejected','deferred','email_sent','email_pending'):
            store.load=MagicMock(return_value=({},status))
            self.assertFalse(store.actionable('node/1'))

    def test_recipient_lock_and_duplicate_claim_never_sends(self):
        db=MagicMock();cur=db.cursor.return_value.__enter__.return_value
        record=MemoryStore().record
        cur.fetchone.side_effect=[({'_auto_mail':record},'review'),('node/2',)]
        store=AutoMailStore(MagicMock(db=db))
        self.assertIsNone(store.claim('node/1'))
        queries=[call.args[0] for call in cur.execute.call_args_list]
        self.assertIn('pg_advisory_xact_lock',queries[0])
        self.assertIn('FOR UPDATE',queries[1])
        self.assertEqual(json.loads(cur.execute.call_args.args[1][0])['state'],'duplicate')
        db.transaction.return_value.__exit__.assert_called_once()

    def test_plain_text_report_keeps_html_characters_without_parse_mode(self):
        store=MemoryStore();store.record['state']='accepted'
        def opener(req,timeout):
            value=json.loads(req.data)
            self.assertNotIn('parse_mode',value)
            self.assertIn('Örnek <işletme>',value['text'])
            return io.BytesIO(b'{"ok":true,"result":{"message_id":1}}')
        flush_reports(store,self.env,opener)

    def test_restart_after_claim_reports_uncertainty_without_resend(self):
        store=MemoryStore();store.record['state']='sending'
        mail=MagicMock()
        deliver({'id':'node/1'},store,self.env,None,mail)
        mail.assert_not_called()
        self.assertIn('Sonuç belirsiz',report_text({},store.record))

class AutomaticScanTests(unittest.TestCase):
    def test_owner_receives_unsent_draft_in_hourly_opportunity_not_smtp(self):
        import tempfile
        from pathlib import Path
        from leadhunter.core import live
        payloads=[]
        rows=[{'type':'node','id':801,'tags':{
            'name':'Synthetic Test Salon','shop':'hairdresser'}}]
        def fake_network(req,timeout):
            if 'api.telegram.org' in req.full_url:
                data=json.loads(req.data)
                payloads.append(data)
                return io.BytesIO(b'{"ok":true,"result":{"message_id":95}}')
            self.assertIn('/interpreter',req.full_url)
            return io.BytesIO(json.dumps({'elements':rows}).encode())
        with tempfile.TemporaryDirectory() as tmp:
            env={'AUTO_MAIL_ENABLED':'false','MAIL_PREVIEW_IN_TELEGRAM':'true',
                 'TELEGRAM_BOT_TOKEN':'test-only', 'TELEGRAM_CHAT_ID':'123',
                 'STATE_FILE':str(Path(tmp)/'seen.json')}
            self.assertEqual(live(env, fake_network,lambda *_:None),1)
        self.assertEqual(len(payloads),1)
        self.assertIn('GÖNDERİLMEMİŞ e-posta taslağı',payloads[0]['text'])
        self.assertIn('Synthetic Test Salon',payloads[0]['text'])
        self.assertIn('Otomatik SMTP kapalı',payloads[0]['text'])
        self.assertLessEqual(len(payloads[0]['text']),4096)

    def test_auto_scan_missing_config_never_contacts_any_service(self):
        from leadhunter.core import live
        with self.assertRaises(RuntimeError):
            live({'AUTO_MAIL_ENABLED':'true'},lambda *a,**k:self.fail('unexpected network'))

    def test_auto_scan_limits_businesses_and_has_no_approval_buttons(self):
        import tempfile
        from pathlib import Path
        from leadhunter.core import live
        env=AutomaticMailTests();env.setUp()
        rows=[{'type':'node','id':i,'tags':{'name':f'Synthetic {i}','shop':'hairdresser',
              'email':f'business{i}@example.invalid'}} for i in range(10)]
        review=MagicMock();review.statuses.return_value={}
        auto=MagicMock();auto.actionable.return_value=True
        def opener(req,timeout):
            self.assertNotIn('telegram',req.full_url)
            return io.BytesIO(json.dumps({'elements':rows}).encode())
        with tempfile.TemporaryDirectory() as tmp, patch(
            'leadhunter.review_private.connect_private_database'),patch(
            'leadhunter.review_private.ReviewStore',return_value=review),patch(
            'leadhunter.automatic_mail.AutoMailStore',return_value=auto),patch(
            'leadhunter.automatic_mail.deliver') as deliver_mock,patch(
            'leadhunter.automatic_mail.flush_reports',side_effect=[0,1,1,1,1,1]):
            self.assertEqual(live({**env.env,'STATE_FILE':str(Path(tmp)/'seen.json')},
                                  opener,lambda *_:None),5)
            self.assertEqual(deliver_mock.call_count,5)
            self.assertEqual(json.loads((Path(tmp)/'seen.json').read_text())['seen_ids'],
                             [f'node/{i}' for i in range(5)])
            review.presented.assert_not_called()
