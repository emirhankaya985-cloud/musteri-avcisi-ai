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



def status_message(env):
    """Public state only; no contact details, tokens, or private CRM content."""
    from .core import read_seen
    seen_path = Path(env.get("STATE_FILE", "data/seen.json"))
    try:
        count = len(read_seen(seen_path))
    except (OSError, ValueError, TypeError):
        count = None
    day_path = Path(env.get("DIGEST_DAY_STATE_FILE", "data/last_digest_day.json"))
    last = "Henüz doğrulanmış gün bilgisi yok"
    try:
        value = json.loads(day_path.read_text(encoding="utf-8"))
        date = value.get("last_sent_date") if isinstance(value, dict) else None
        if (isinstance(date, str) and len(date) == 10
                and date[4] == "-" and date[7] == "-"
                and date.replace("-", "").isdigit()):
            last = date
    except (OSError, ValueError, TypeError):
        pass
    return (
        "🤖 Müşteri Avcısı AI — Telegram durumu\n\n"
        "📬 Sahibe özel fırsat bildirimi ve üç butonlu karar işleme açık.\n"
        "📅 Tarama hedefi: hafta içi 10:23 TRT; 11:53 yedek.\n"
        "🔄 Komut/karar kontrol hedefi: 15 dakikada bir; GitHub gecikebilir.\n"
        f"🗂️ Eski OSM arşivinde görülen kayıt: {count if count is not None else 'okunamadı'}\n"
        f"🗓️ Son günlük rapor işareti: {last}\n"
        "✉️ Bu zamanlanmış fırsat taraması işletmelere otomatik mail göndermez.\n"
        "ℹ️ İşletmePilot'un ayrı CRM veritabanındaki müşteri sayısını bu komut "
        "doğrulamaz; bu botun kendi arşivini gösterir."
    )


def mail_status_message(review_store):
    """Never include customer names, email addresses or content in logs/messages."""
    if review_store is None:
        return "📮 Mail geçmişi: özel veritabanı bağlı değil; doğrulanamadı."
    counts = review_store.mail_summary()
    return (
        "📮 Özel mail geçmişi\n"
        f"🗂️ Toplam aday: {counts['total']}\n"
        f"✅ SMTP kabul kaydı: {counts['accepted']}\n"
        f"⚠️ Belirsiz/devam eden: {counts['uncertain']}\n"
        f"⏭️ Adresi bulunamadığı için atlanan: {counts['skipped']}\n"
        f"🔁 Tekrar engellenen: {counts['duplicate']}\n"
        f"🔴 Gmail başarısız teslimat: {counts.get('failed', 0)}\n"
        f"🟡 Gmail gecikme: {counts.get('delayed', 0)}\n"
        "ℹ️ SMTP kabulü teslim kanıtı değildir. Gmail gelen yanıtları "
        "bu bot tarafından henüz otomatik okunmuyor."
    )


def process_owner_command(update, token, owner, env, opener=urlopen, review_store=None):
    """One existing polling consumer serves owner-only private Telegram commands."""
    import time
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    command = message.get("text")
    if (chat.get("type") != "private"
            or str(chat.get("id")) != owner
            or str(sender.get("id")) != owner
            or sender.get("is_bot") is True
            or not isinstance(command, str)
            or command not in ("/durum", "/eposta", "/yardim", "/start")):
        return False
    timestamp = message.get("date")
    if type(timestamp) is int and abs(time.time() - timestamp) > 3600:
        return False  # never replay a stale buffered command
    if command == "/durum":
        text = status_message(env)
        if review_store is not None:
            text += "\n\n" + mail_status_message(review_store)
    elif command == "/eposta":
        text = mail_status_message(review_store)
    else:
        text = (
            "🤖 Müşteri Avcısı AI — yalnızca sahip Telegram sohbeti\n"
            "🔎 /durum — otomasyon ve tarama durumunu göster.\n"
            "📮 /eposta — özel veritabanındaki eski mail ve atlama sayılarını göster.\n"
            "✅ EVET / ❌ HAYIR / ⏳ BEKLET — fırsat mesajındaki "
            "butonlarla karar ver.\n"
            "ℹ️ Web paneli veya izlenecek site eklemeniz gerekmez.\n"
            "✉️ Bu bot komutları hiçbir işletmeye mail göndermez."
        )
    response = api(token, "sendMessage", {
        "chat_id": owner, "text": text, "disable_web_page_preview": True,
    }, opener=opener)
    if not isinstance(response, dict) or type(response.get("message_id")) is not int \
            or response["message_id"] <= 0:
        raise RuntimeError("Owner command response not confirmed")
    return True


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
    try:
        api(token, "answerCallbackQuery", {
            "callback_query_id": callback["id"], "text": "Seçim alındı (demo).",
        }, opener=opener)
    except RuntimeError:
        # GitHub scheduled polls are delayed; callback query IDs may expire,
        # but the owner's original demo message has already been updated.
        pass
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
    # A broken private DB must not cause live decisions to be irreversibly consumed.
    # Open it before getUpdates; Telegram updates are confirmed only on next offset.
    from .review_private import connect_private_database, ReviewStore
    review_store = None
    review_conn = None
    if env.get("REVIEW_DATABASE_URL"):
        review_conn = connect_private_database(env["REVIEW_DATABASE_URL"])
        review_store = ReviewStore(review_conn)
    count = 0
    try:
        updates = api(token, "getUpdates", {
            "offset": offset, "limit": 100, "timeout": 0,
            "allowed_updates": ["callback_query", "message"],
        }, opener=opener)
        if not isinstance(updates, list):
            raise RuntimeError("Invalid Telegram updates")
        for update in updates:
            uid = update.get("update_id") if isinstance(update, dict) else None
            if type(uid) is not int or uid < offset:
                continue
            handled = process_owner_command(update, token, owner, env, opener=opener, review_store=review_store)
            if not handled:
                handled = process_update(update, token, owner, opener=opener)
            if not handled and review_store and env.get('OWNER_APPROVED_MAIL_ENABLED') == 'true':
                from .outreach import handle_mail_callback
                try:
                    handled = handle_mail_callback(update, token, owner, review_store, env, opener)
                except Exception:
                    raise RuntimeError('Owner mail operation failed; sensitive details redacted') from None
            if not handled and review_store:
                handled = process_review_callback(
                    update, token, owner, review_store, opener=opener)
            if handled:
                count += 1
            offset = max(offset, uid + 1)
    finally:
        if review_conn:
            review_conn.close()
    if offset != previous["next_offset"]:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"next_offset": offset}) + "\n", encoding="utf-8")
    output(f"Owner demo/review button selections processed: {count}")
    return count


def process_review_callback(update, token, owner, store, opener=urlopen):
    from .review_messages import parse_callback
    if not isinstance(update, dict):
        return False
    callback = update.get("callback_query") or {}
    message = callback.get("message") or {}
    chat = message.get("chat") or {}
    sender = callback.get("from") or {}
    parsed = parse_callback(callback.get("data"))
    if not parsed or chat.get("type") != "private" or (
            str(chat.get("id")) != owner or str(sender.get("id")) != owner):
        return False
    message_id = message.get("message_id")
    if type(message_id) is not int or not isinstance(callback.get("id"), str):
        return False
    lead_id, action = parsed
    status = store.decide(lead_id, message_id, action)
    if status is None:
        return False  # unrelated, stale or tampered callback
    labels = {"rejected": "❌ HAYIR — listeden çıkarıldı",
              "deferred": "⏳ BEKLET — sonraki taramada tekrar gösterilecek",
              "email_pending": "✅ EVET — onaylandı; e-posta gönderilmedi",
              "email_sent": "✅ E-posta gönderimi kayıtlı",
              "review": "📌 İnceleme bekliyor"}
    # Telegram returns plain text stripped of HTML tags, so edit as plain text.
    original = message.get("text")
    if not isinstance(original, str):
        original = "Müşteri Avcısı AI"
    text = original.split("\n\n📌 KARAR:", 1)[0]
    api(token, "editMessageText", {
        "chat_id": owner, "message_id": message_id,
        "text": text + "\n\n📌 KARAR: " + labels[status],
        "reply_markup": {"inline_keyboard": []},
    }, opener=opener)
    try:
        api(token, "answerCallbackQuery", {
            "callback_query_id": callback["id"],
            "text": "Karar kaydedildi. " + labels[status],
        }, opener=opener)
    except RuntimeError:
        pass  # GitHub scheduled polls may acknowledge an expired callback ID
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["send-test", "poll"])
    if parser.parse_args().command == "send-test":
        send_test()
    else:
        poll()
