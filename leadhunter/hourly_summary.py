"""Bounded, private owner-only hourly research summary.

No names, emails, phones, URLs, message bodies or secrets leave this module.
One run attempt may send at most one hourly status; re-run attempts skip.
"""
import re


def eligible_run(env):
    return (
        env.get("OWNER_HOURLY_SUMMARY") == "true"
        and str(env.get("GITHUB_RUN_ATTEMPT") or "1") == "1"
        and bool(re.fullmatch(r"[0-9]{6,24}", str(env.get("GITHUB_RUN_ID") or "")))
    )


def compose(stats, sent, slot, mail=None):
    keys = ("fetched", "eligible", "rejected", "duplicates", "already_seen", "new")
    if any(type(stats.get(key)) is not int or stats[key] < 0 for key in keys):
        raise ValueError("Invalid scan metrics")
    if type(sent) is not int or sent < 0:
        raise ValueError("Invalid owner delivery count")
    label = slot if re.fullmatch(r"pilot_[0-9]+_of_[0-9]+|default|explicit_override", slot) else "unverified"
    status = "📮 Gmail/SMTP geçmişi: doğrulanamadı\n"
    if isinstance(mail, dict) and all(type(mail.get(k)) is int and mail[k] >= 0
                                       for k in ("accepted", "failed", "replied")):
        status = (f"📮 Geçmiş SMTP kabul: {mail['accepted']} | "
                  f"Başarısız teslimat: {mail['failed']} | "
                  f"Eşleşmiş yanıt: {mail['replied']} (teslim kanıtı değil)\n")
    return (
        "📊 Müşteri Avcısı — Saatlik tarama özeti\n"
        f"🔎 Tarama alanı: {label}\n"
        f"📋 Ham kayıt: {stats['fetched']} | Geçerli: {stats['eligible']}\n"
        f"🆕 Yeni OSM kaydı: {stats['new']}\n"
        f"🔁 Önceden görülen: {stats['already_seen']} | Tekrar: {stats['duplicates']}\n"
        f"⏭️ Geçersiz/eksik: {stats['rejected']}\n"
        f"📩 Sahibe yeni fırsat bildirimi: {sent}\n"
        + status +
        "⛔ Müşterilere otomatik SMTP gönderimi: 0\n"
        "ℹ️ Bu tarama bir satış veya alıcı izni kanıtı değildir."
    )
