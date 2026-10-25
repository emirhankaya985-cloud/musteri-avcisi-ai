"""Side-effect-free Telegram review message formatter and secure callback parser."""
import html
import re

PATTERN = re.compile(r"lead:v1:(yes|no|later):((?:node|way|relation)/[0-9]+)\Z")
BUTTONS = (("✅ Evet", "yes"), ("❌ Hayır", "no"), ("⏳ Beklet", "later"))


def button_markup(lead_id):
    if not re.fullmatch(r"(?:node|way|relation)/[0-9]+", lead_id):
        raise ValueError("Invalid OSM identifier")
    return {"inline_keyboard": [[{"text": title,
                                 "callback_data": f"lead:v1:{action}:{lead_id}"}
                                for title, action in BUTTONS]]}


def parse_callback(data):
    match = PATTERN.fullmatch(data) if isinstance(data, str) else None
    return (match.group(2), match.group(1)) if match else None


def compact_telegram(lead):
    from .core import recommend
    esc = html.escape
    rec = recommend(lead)
    website = rec["focus"] == "website"
    title = "🟣 WEB SİTESİ FIRSATI" if website else "🔵 OTOMASYON FIRSATI"
    lines = [
        f"<b>{title}</b> | {min(max(int(lead['score']), 0), 100)}/100",
        f"🏪 <b>{esc(str(lead['name']))}</b>",
        "💡 " + esc(rec["idea"]),
    ]
    if lead.get("phone"):
        lines.append("☎️ " + esc(str(lead["phone"])))
    if lead.get("address"):
        lines.append("📍 " + esc(str(lead["address"])))
    lines += [
        f"🗺️ <a href=\"https://www.openstreetmap.org/{esc(lead['id'])}\">OSM kaydı</a>",
        "ℹ️ OSM verisi; gerçek ihtiyaç ayrıca doğrulanmalı.",
    ]
    return "\n".join(lines)
