"""Owner-only scheduled scanner with one conservative same-day delivery guard.

A second daily schedule is a best-effort retry for GitHub delayed/dropped cron.
The public state records only a YYYY-MM-DD date, never private CRM or mail data.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ALERT = (
    "🔴 Müşteri Avcısı AI — HATA\n"
    "Bugünkü işletme taraması tamamlanamadı. Kaynak/API veya bağlantı "
    "hatası olabilir. Yeni müşteri bildirimi doğrulanmadı.\n"
    "Gönderim ayrıntıları özel kayıtlardan kontrol edilmeli; tekrar göndermeyin.\n"
    "GitHub Actions: https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions"
)


def current_day():
    return datetime.now(ZoneInfo("Europe/Istanbul")).date().isoformat()


def run(env=None, handler=None, sender=None, output=print, today=None):
    from .core import live, send_telegram
    env = os.environ if env is None else env
    day = current_day() if today is None else today
    guard = env.get("DIGEST_DAILY_GUARD", "").lower() == "true"
    state = Path(env.get("DIGEST_DAY_STATE_FILE", "data/last_digest_day.json"))
    if guard and state.exists():
        try:
            current = json.loads(state.read_text(encoding="utf-8"))
            if current == {"last_sent_date": day}:
                output("Daily owner scan already delivered messages today; backup slot skipped")
                return 0
        except (ValueError, OSError):
            raise RuntimeError("Corrupt daily delivery guard; refusing repeated send") from None
    handler = live if handler is None else handler
    sender = send_telegram if sender is None else sender
    try:
        sent = handler(env=env, output=output)
    except Exception:
        token, chat_id = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
        if token and chat_id:
            try:
                sender(ALERT, token, chat_id)
                output("Owner scan failure alert: Telegram delivery accepted")
            except Exception:
                output("Owner scan failure alert failed; details redacted")
        raise
    if guard and sent > 0:
        state.parent.mkdir(parents=True, exist_ok=True)
        tmp = state.with_suffix(".tmp")
        tmp.write_text(json.dumps({"last_sent_date": day}) + "\n", encoding="utf-8")
        tmp.replace(state)
    return sent


if __name__ == "__main__":
    run()
