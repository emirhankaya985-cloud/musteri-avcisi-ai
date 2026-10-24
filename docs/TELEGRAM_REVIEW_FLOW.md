# Müşteri Avcısı AI — Telegram karar akışı

Bu dosya iş kurallarını tarif eder; gerçek işletmelere e-posta gönderme henüz etkin değildir.

✅ Evet → email_pending (tekil e-posta için onay). Gerçek alıcı, gönderici hesabı ve yasal uygunluk doğrulanmadan gönderim yok. Başarılı sağlayıcı onayı sonrası email_sent; ikinci tıklama yeni e-posta üretmez.

❌ Hayır → rejected. Sonraki fırsat listelerine alınmaz.

⏳ Beklet → deferred. Gelecek taramalarda yeni fırsatlardan önce gösterilir; tekrar Beklet edilirse sonraki taramada yine üstte. E-posta gönderilmez.

## Üretim sınırı

leadhunter/review_flow.py sadece side-effect-free kural motorudur. Mevcut Telegram inline butonlar hâlâ sentetik demo içindir. Özel kalıcı kayıt, gerçek callback entegrasyonu ve gerçek gönderici henüz bağlı değildir.

Public GitHub deposuna müşteri iletişim verileri, özel karar kayıtları, onaylar, e-posta adresleri ve gönderim geçmişi yazılmamalıdır. data/seen.json yalnızca OSM açık ID'lerini tutar.

Mail gönderimi e-posta adresi doğrulaması, bağlanmış hesap ve ticari ileti uygunluk denetiminden sonra tekil yapılmalı; otomatik tekrar ve toplu spam yapılmamalıdır.
