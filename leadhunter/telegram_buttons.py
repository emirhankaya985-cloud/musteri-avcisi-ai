"""Owner-only Telegram inline button demo: no marketing emails or business DMs."""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

HEADER = "🧪 Müşteri Avcısı AI — Buton Testi"
OPTIONS = {"demo:v1:yes": "✅ EVET", "demo:v1:no": "❌ HAYIR",
           "demo:v1:later": "⏳ BEKLET"}


def api(token, method, payload, opener=urlopen):
    req = Request(f"https://api.telegram.org/bot{token}/{method}",
                  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                  headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener(req, timeout=30) as response:
            value = json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Telegram API HTTP {exc.code}; credentials redacted") from None
    except (URLError, OSError, TimeoutError, ValueError):
        raise RuntimeError("Telegram API failure; credentials redacted") from None
    if not isinstance(value, dict) or not value.get("ok"):
        raise RuntimeError("Telegram API response failed; credentials redacted")
    return value.get("result")


def credentials(env):
    token, chat_id = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id or not str(chat_id).lstrip("-").isdigit():
        raise RuntimeError("Owner Telegram secrets missing or invalid")
    return token, str(chat_id)


def send_test(env=None, opener=urlopen, output=print):
    env = os.environ if env is None else env
    token, chat_id = credentials(env)
    buttons = [{"text": label.title(), "callback_data": key}
               for key, label in OPTIONS.items()]
    result = api(token, "sendMessage", {
        "chat_id": chat_id,
        "text": HEADER + "\n\n🟣 ÖRNEK Premium Web\n"
        "🏪 Test Kuaförü (gerçek işletme değil)\n"
        "💡 Site + galeri + randevu\n\n"
        "Bir karar seç:\n"
        "Bu yalnızca denemedir. Müşteriye mesaj veya e-posta gönderilmez.",
        "reply_markup": {"inline_keyboard": [buttons]},
        "disable_web_page_preview": True,
    }, opener=opener)
    if not isinstance(result, dict) or type(result.get("message_id")) is not int \
            or result["message_id"] <= 0:
        raise RuntimeError("Telegram test message was not confirmed")
    output("Three-button owner demo delivered (1 message, no business contact)")


def process_update(update, token, owner, opener=urlopen):
    callback = update.get("callback_query") or {}
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    user = callback.get("from") or {}
    key = callback.get("data")
    valid = (key in OPTIONS and chat.get("type") == "private"
             and str(chat.get("id")) == owner
             and str(user.get("id")) == owner
             and type(message.get("message_id")) is int
             and isinstance(message.get("text"), str)
             and message["text"].startswith(HEADER)
             and isinstance(callback.get("id"), str))
    if not valid:
        return False
    # Only a synthetic demo can be edited. After editing, no buttons remain.
    base = message["text"].split("\n\n📌 SEÇİM:", 1)[0]
    api(token, "editMessageText", {
        "chat_id": owner, "message_id": message["message_id"],
        "text": base + "\n\n📌 SEÇİM: " + OPTIONS[key] +
                "\n✅ Demo kararı kaydedildi. Hiçbir e-posta gönderilmedi.",
        "reply_markup": {"inline_keyboard": []},
    }, opener=opener)
    api(token, "answerCallbackQuery", {
        "callback_query_id": callback["id"], "text": "Seçim alındı (demo).",
    }, opener=opener)
    return True


def poll(env=None, opener=urlopen, output=print):
    env = os.environ if env is None else env
    token, owner = credentials(env)
    state = Path(env.get("CALLBACK_OFFSET_FILE", "data/telegram_demo_offset.json"))
    previous = json.loads(state.read_text(encoding="utf-8")) if state.exists() else {"next_offset": 0}
    offset = previous.get("next_offset")
    if type(offset) is not int or offset < 0:
        raise RuntimeError("Invalid Telegram callback offset")
    webhook = api(token, "getWebhookInfo", {}, opener=opener)
    if not isinstance(webhook, dict) or webhook.get("url"):
        raise RuntimeError("Webhook configured; cannot use getUpdates polling")
    updates = api(token, "getUpdates", {
        "offset": offset, "limit": 100, "timeout": 0,
        "allowed_updates": ["callback_query"],
    }, opener=opener)
    if not isinstance(updates, list):
        raise RuntimeError("Invalid Telegram updates")
    count = 0
    for update in updates:
        uid = update.get("update_id") if isinstance(update, dict) else None
        if type(uid) is not int or uid < offset:
            continue
        if process_update(update, token, owner, opener=opener):
            count += 1
        offset = max(offset, uid + 1)
    # Public repo stores only a numeric cursor; never chats, personal data or choices.
    if offset != previous["next_offset"]:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"next_offset": offset}) + "\n", encoding="utf-8")
    output(f"Owner demo button selections processed: {count}")
    return count


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["send-test", "poll"])
    if parser.parse_args().command == "send-test":
        send_test()
    else:
        poll()
