import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from tools.get_chat_id import api
from tools.get_chat_id import select_chat

def msg(chat_id, text, typ='private'):
    return {'message': {'chat': {'id': chat_id, 'type': typ}, 'text': text}}

class ChatIdTests(unittest.TestCase):
    def test_api_error_redacts_token(self):
        token = 'SUPER_PRIVATE_BOT_TOKEN'
        def fail(req, timeout=None):
            raise HTTPError(req.full_url, 401, 'Unauthorized', {}, None)
        with patch('tools.get_chat_id.urlopen', side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, 'Telegram API HTTP 401') as caught:
                api(token, 'getMe')
        self.assertNotIn(token, str(caught.exception))

    def test_private_chatid(self):
        self.assertEqual(select_chat([msg(42, '/chatid')]), 42)

    def test_start_fallback(self):
        self.assertEqual(select_chat([msg(123, '/start')]), 123)

    def test_prefer_explicit_request(self):
        self.assertEqual(select_chat([msg(123, '/start'), msg(456, '/chatid')]), 456)

    def test_reject_multiple_requesters(self):
        self.assertIsNone(select_chat([msg(1, '/chatid'), msg(2, '/chatid')]))

    def test_skip_group(self):
        self.assertIsNone(select_chat([msg(-3, '/chatid', 'supergroup')]))

    def test_no_private_commands(self):
        self.assertIsNone(select_chat([msg(5, 'hello')]))

    def test_telegram_mention(self):
        self.assertEqual(select_chat([msg(3, '/chatid@TestBot')]), 3)

if __name__ == '__main__':
    unittest.main()
