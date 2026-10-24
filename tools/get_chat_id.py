"""Connect the owner's private Telegram chat without printing the bot token."""
import getpass
import json
import os
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def select_chat(updates):
    """Use a single explicit private /chatid request; fall back to /start."""
    requested = set()
    started = set()
    for update in updates:
        msg = update.get('message') or {}
        chat = msg.get('chat') or {}
        if chat.get('type') != 'private' or not isinstance(chat.get('id'), int):
            continue
        command = (msg.get('text') or '').split(maxsplit=1)
        if not command:
            continue
        cmd = command[0].lower().split('@', 1)[0]
        if cmd == '/chatid':
            requested.add(chat['id'])
        elif cmd == '/start':
            started.add(chat['id'])
    pool = requested if requested else started
    return next(iter(pool)) if len(pool) == 1 else None


def api(token, method, payload=None):
    url = f'https://api.telegram.org/bot{token}/{method}'
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'User-Agent': 'MusteriAvcisiAI/0.2'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    try:
        with urlopen(Request(url, data=data, headers=headers, method='POST' if data else 'GET'),
                     timeout=20) as response:
            result = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f'Telegram API HTTP {exc.code}; credentials redacted') from None
    except URLError:
        raise RuntimeError('Telegram API connection failed; credentials redacted') from None
    if not result.get('ok'):
        raise RuntimeError('Telegram API yanıtı başarısız')
    return result['result']


def main():
    token = (os.environ.get('TELEGRAM_BOT_TOKEN')
             or getpass.getpass('Telegram Bot Token (gizli): ')).strip()
    if not token:
        raise SystemExit('TELEGRAM_BOT_TOKEN eksik; GitHub Actions secret kontrol edilmeli')
    bot = api(token, 'getMe')
    print('Bağlanılan bot kullanıcı adı: @' + bot.get('username', '(unknown)'))
    updates = api(token, 'getUpdates')
    chat_id = select_chat(updates)
    if chat_id is None:
        private_count = sum(
            1 for u in updates
            if (u.get('message') or {}).get('chat', {}).get('type') == 'private'
        )
        print(f'Tanı: {len(updates)} alınan güncelleme, {private_count} özel sohbet mesajı.')
        raise SystemExit(
            'Chat ID bulunamadı. Yukarıdaki @kullanıcı adına sahip bota Telegram içinde '
            '/chatid mesajını GÖNDER; sonra Actions iş akışını yeniden çalıştır. '
            'Birden çok özel hesap /chatid gönderdiyse otomatik seçim yapılmaz. '
            'Başka bir servis getUpdates isteklerini tüketiyorsa o servis durdurulmalıdır.'
        )
    api(token, 'sendMessage', {
        'chat_id': chat_id,
        'text': '✅ Müşteri Avcısı AI: Telegram bağlantı testi başarılı!'
    })
    print('Telegram Chat ID (TELEGRAM_CHAT_ID secret olarak ekle):', chat_id)
    print('Telegram test mesajı gönderildi.')


if __name__ == '__main__':
    main()
