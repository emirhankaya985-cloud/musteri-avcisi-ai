# Özel Telegram karar depolaması

Proje: `musteri-avcisi-ai-review` · Neon Postgres proje ID: `misty-field-02930645` (Frankfurt).

Bu veritabanı **Müşteri Avcısı AI için ayrıdır**, diğer projelerin tablolarıyla paylaşılmaz. Ücretsiz planda açıldı.

## Şema

`owner_leads`: osm_id (PK), lead_data (JSONB), status (review, deferred, email_pending, rejected, email_sent), telegram_message_id, first_seen_at, updated_at, last_presented_at, approved_at, sent_at.

## Çalışma şekli

- GitHub Secrets `REVIEW_DATABASE_URL` tanımlanırsa gerçek işletme Telegram bildirimlerinde ✅ Evet / ❌ Hayır / ⏳ Beklet çıkar.
- Bildirimin `callback_data` alanı yalnızca açık OSM ID'si taşır; özel kişi/iletişim verileri burada bulunmaz.
- Kararlar Neon'un özel veritabanında tutulur; public GitHub sadece zaten görülen OSM ID'lerini kaydeder.
- `Hayır` → rejected ve sonraki listede yok.
- `Beklet` → deferred. Sonraki taramada, yeni adaylardan önce tekrar; yeniden Beklet aynı döngüyü sürdürür.
- `Evet` → email_pending. **Hiçbir e-posta gönderilmez**; Gmail/uygunluk entegrasyonu son adım olarak kapalı.
- Yetkisiz sohbet, başka kullanıcı, eski veya uygunsuz message ID hiçbir kararı değiştiremez.
- DB yoksa veya bağlanamazsa yeni gerçek butonlar açılamaz; secret yoksa eski Telegram bildirim sistemi çalışır.

## Kalan tek güvenli altyapı bağlantısı

1. GitHub 985 public depo → Settings → Secrets and variables → Actions → `New repository secret`.
2. Adı `REVIEW_DATABASE_URL`. Değeri **Neon proje konsolundan alınan SSL zorunlu pooled PostgreSQL bağlantı URL'si**.
3. **Bu URL'yi sohbet, issue, PR veya GitHub koduna yazma.** `sslmode=require` parametresini tut.
4. GitHub Actions'da iki workflow'un sadece runtime env üzerinden kullanılır; sırf test için canlı digest'i tekrar tekrar çalıştırma.

Main dalına alınan bu değişiklik kendi başına canlı digest başlatmaz. Bu Secret olmadan 3 butonlu gerçek üretim akışına `PASS` denilemez. Kod offline test edilse bile gerçek DB erişimi/Telegram karar geçişi canlı doğrulama ister.


## Gerçek Neon kararı için geçici işlemsel kabul testi

`leadhunter/review_smoke.py` gerçek özel PostgreSQL bağlantısında üç test işletmesiyle Evet/Hayır/Beklet geçişlerini, yanlış Telegram mesaj kimliğinin reddini, reddedilen kaydın yeniden etkinleştirilememesini ve ertelenen kaydın öne alınmasını kontrol eder. Bu üç kayıt tek açık PostgreSQL transaction içinde sınanır ve kasıtlı rollback uygulanır; kalıcı CRM/test kaydı bırakılmaz. **Gerçek Telegram veya Gmail mesajı gönderilmez.**

Bu doğrulama yalnızca `telegram-buttons-inbox.yml` workflow'unun güvenli push veya manuel tetiklenmesi sırasında gerçekleşir; 15 dakikalık normal callback taramalarında tekrar çalışmaz. Logda `PASS: Private Neon YES/NO/LATER` görülmeden gerçek veritabanı karar entegrasyonunu doğrulanmış sayma.
