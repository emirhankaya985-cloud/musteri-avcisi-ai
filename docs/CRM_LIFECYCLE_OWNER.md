# Sahip Telegram'ından CRM satış aşaması güncelleme

Özel Telegram sahibine açık `/crm` komutu mevcut CRM yaşam döngüsü geçişlerini
işletme kaydı için kaydeder. Bu işlem yalnız `REVIEW_DATABASE_URL` ile erişilen
özel Neon'da olay geçmişi yazar; e-posta veya Telegram işletme mesajı göndermez.

```text
/crm node/12345678 researched osm://node/12345678 resmi-site-incelendi
```

Biçim: `/crm <osm_id> <stage> <evidence_ref> <short_reason>`. İlk aşama
`new_discovered` kaydı sistem tarafından oluşturulmuş olmalıdır. Sonraki aşama
mevcut izinli geçiş tablosuna uymalıdır; örneğin `new_discovered` → `researched`
→ `need_verified`. CRM yaşam döngüsündeki `communication_eligible` kendi başına
ticari e-posta izni vermez. Pazarlama uygunluğu ve gönderici itibar kapıları
ayrı çalışır.

Gerekçe ve referans özel CRM'de tutulur. Telegram/Actions loglarında sadece
`crm` komut adı ve API makbuzu görünür; tam komut metni loglanmaz. İYS
belgesi, e-posta adresi veya kişisel veriyi kanıt referansına koyma.
