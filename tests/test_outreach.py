import io
import json
import unittest
from unittest.mock import patch, MagicMock
from leadhunter.outreach import draft_mail, send_mail, handle_mail_callback, MailStore, valid_recipient


class OutreachTests(unittest.TestCase):
    def setUp(self):
        self.env = {'MAIL_AI_API_KEY':'fixture','MAIL_AI_MODEL':'fixture',
                    'MAIL_AI_URL':'https://ai.example.invalid/v1/chat/completions',
                    'OWNER_APPROVED_MAIL_ENABLED':'true',
                    'GMAIL_SENDER_ADDRESS':'synthetic.sender@gmail.com',
                    'GMAIL_APP_PASSWORD':'abcdefghijklmnop'}
        self.draft = {'id':'a'*24,'recipient':'owner@example.invalid',
                      'subject':'Örnek teklif','body':'Merhaba,\nÖrnek metin.'}

    def test_ai_only_receives_public_context(self):
        def opener(req,timeout):
            data = json.loads(req.data)
            self.assertNotIn('private@example.invalid',str(data))
            self.assertIn('subject',str(data))
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(
                {'subject':'Kişisel teklif','body':'Merhaba Örnek İşletme'})}}]}).encode())
        self.assertEqual(draft_mail({'name':'Örnek İşletme','email':'private@example.invalid'},
                                   self.env,opener)['subject'],'Kişisel teklif')

    def test_missing_ai_fails_closed(self):
        with self.assertRaises(RuntimeError):
            draft_mail({'name':'Örnek'}, {},lambda *a,**k:self.fail('network'))

    def test_header_injection_rejected(self):
        def opener(*a,**k):
            return io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(
                {'subject':'X\nBcc: injected','body':'Body'})}}]}).encode())
        with self.assertRaises(RuntimeError):
            draft_mail({'name':'Örnek'},self.env,opener)
        for value in ('a@example.invalid\nBcc:x@example.invalid','a@example.invalid,b@example.invalid',''):
            self.assertFalse(valid_recipient(value))

    def test_smtp_single_recipient_and_exact_reviewed_body(self):
        smtp = MagicMock()
        smtp.__enter__.return_value.send_message.return_value = {}
        send_mail(self.draft,self.env,lambda *a,**k:smtp)
        call = smtp.__enter__.return_value.send_message.call_args
        self.assertEqual(call.kwargs['to_addrs'],['owner@example.invalid'])
        self.assertEqual(call.args[0].get_content().strip(),self.draft['body'])

    def test_temporary_rcpt_450_retries_once_before_data(self):
        import smtplib
        smtp = MagicMock()
        smtp.__enter__.return_value.send_message.side_effect = [
            smtplib.SMTPRecipientsRefused(
                {'owner@example.invalid': (450, b'temporary refusal')}),
            {},
        ]
        send_mail(self.draft, self.env, lambda *a, **k:smtp)
        self.assertEqual(smtp.__enter__.return_value.send_message.call_count, 2)

    def test_permanent_rcpt_550_never_retries(self):
        import smtplib
        smtp = MagicMock()
        smtp.__enter__.return_value.send_message.side_effect = (
            smtplib.SMTPRecipientsRefused(
                {'owner@example.invalid': (550, b'no such user')}))
        with self.assertRaises(RuntimeError):
            send_mail(self.draft, self.env, lambda *a, **k:smtp)
        self.assertEqual(smtp.__enter__.return_value.send_message.call_count, 1)

    def test_ambiguous_smtp_timeout_never_retries(self):
        smtp = MagicMock()
        smtp.__enter__.return_value.send_message.side_effect = TimeoutError('synthetic')
        with self.assertRaisesRegex(RuntimeError, 'uncertain'):
            send_mail(self.draft, self.env, lambda *a, **k:smtp)
        self.assertEqual(smtp.__enter__.return_value.send_message.call_count, 1)

    def test_disabled_mail_never_connects(self):
        with self.assertRaises(RuntimeError):
            send_mail(self.draft,{},lambda *a,**k:self.fail('SMTP'))

    def test_claimed_mail_never_sends_again(self):
        review=MagicMock()
        review.db.cursor.return_value.__enter__.return_value.fetchone.return_value=None
        with patch('leadhunter.outreach.send_mail') as send:
            self.assertEqual(MailStore(review).send('node/1',2,'a'*24,self.env),'already_claimed')
            send.assert_not_called()

    def test_uncertain_delivery_is_not_released_for_retry(self):
        review=MagicMock()
        store=MailStore(review)
        with patch.object(store,'_claim',return_value={**self.draft,'state':'sending'}):
            with patch('leadhunter.outreach.send_mail',side_effect=RuntimeError('redacted')) as send:
                self.assertEqual(store.send('node/1',2,'a'*24,self.env),'uncertain')
                self.assertEqual(send.call_count,1)
        # The committed claim remains sending and is never reset to draft.
        review.db.cursor.assert_not_called()

    def test_manual_mail_requires_atomic_claim_and_eligibility(self):
        review=MagicMock()
        store=MailStore(review)
        for refusal in ('not_eligible','paused','duplicate'):
            with self.subTest(refusal=refusal):
                with patch.object(store,'_claim',return_value=refusal):
                    with patch('leadhunter.outreach.send_mail') as send:
                        self.assertEqual(store.send('node/1',2,'a'*24,self.env),refusal)
                        send.assert_not_called()


    def test_foreign_callback_rejected_without_database(self):
        review=MagicMock()
        update={'callback_query':{'from':{'id':999},'data':'mail:v1:node/1:'+('a'*24),
                                 'message':{'message_id':1,'chat':{'id':123,'type':'private'}}}}
        self.assertFalse(handle_mail_callback(update,'fixture','123',review,self.env))
        review.decide.assert_not_called()

    def test_preview_never_sends_and_binds_send_to_frozen_id(self):
        review=MagicMock();review.decide.return_value='email_pending'
        update={'callback_query':{'id':'q','from':{'id':123},'data':'lead:v1:yes:node/1',
                'message':{'message_id':7,'chat':{'id':123,'type':'private'}}}}
        calls=[]
        def opener(req,timeout):
            calls.append(json.loads(req.data))
            return io.BytesIO(b'{"ok":true,"result":true}')
        with patch('leadhunter.outreach.MailStore') as store,patch('leadhunter.outreach.send_mail') as send:
            store.return_value.prepare.return_value={**self.draft,'state':'draft'}
            self.assertTrue(handle_mail_callback(update,'fixture','123',review,self.env,opener))
            send.assert_not_called()
        self.assertIn(self.draft['body'],calls[0]['text'])
        self.assertEqual(calls[0]['reply_markup']['inline_keyboard'][0][0]['callback_data'],
                         'mail:v1:node/1:'+('a'*24))
