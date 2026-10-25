# Gmail altyapısı — güvenli, ücretsiz, yalnızca kendine test

## Mevcut kapsam

- Gmail SMTP (`smtp.gmail.com:465`, doğrulamalı TLS/SSL) ve Python standard library kullanılır; ücretli API veya servis gerektirmez.
- Otomatik gönderim varsayılan **KAPALI**. GitHub workflow yalnızca `workflow_dispatch` ile çağrılabilir; kod push'u veya tarama tetiklemez.
- Normal seçenek `send_to_myself=false` sadece dry-run yapar. İşaretlenirse ve Secrets kuruluysa sadece kendi Gmail adresine **1 test maili** çıkar.
- Kod, gerçek işletme alıcısı kabul ETMEZ. Telegram `Evet` kararını gerçek kişiye otomatik e-postaya bağlamaz. CRM / alıcı / onay / e-posta geçmişi public depoda tutulmaz.

## Hesap açıldıktan sonra kullanıcının yapacağı iki ayar

1. Yeni Gmail hesabında 2 Adımlı Doğrulamayı aç: https://myaccount.google.com/security .
2. Uygulama şifresi erişimi açıksa https://myaccount.google.com/apppasswords adresinden **Müşteri Avcısı AI** isimli uygulama şifresi oluştur. Normal Gmail şifreni kullanma.
3. Sadece https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/settings/secrets/actions bölümündeki Repository secrets kısmına EKLE:
   - `GMAIL_SENDER_ADDRESS`: Oluşturduğun yeni Gmail adresi
   - `GMAIL_APP_PASSWORD`: Google'ın oluşturduğu **16 karakterlik uygulama şifresi**
4. Bana veya Codex'e şifre, uygulama şifresi, iki faktörlü doğrulama kodu yazma; GitHub workflow loglarına asla koyma.
5. https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/workflows/gmail-self-test.yml → `Run workflow` → önce `send_to_myself=false` (dry-run), sonra hazır olduğunda `true` ile **kendine tek mail** testi.

Google bazı hesaplarda, güvenlik anahtarıyla sınırlı 2FA veya Advanced Protection varsa uygulama şifresi sunmayabilir. Bu durumda mevcut korumayı gevşetme: ayrı OAuth tabanlı bağlantı gerekecek.

## Kalan gerçek müşteri akışı

Gerçek Telegram Evet/Hayır/Beklet callback entegrasyonu, özel kalıcı karar veritabanı, doğrulanmış işletme e-postası, uygun ticari ileti koşulları ve tek seferlik idempotent teslimat henüz hazırlanmadı. Bu katman kullanıcıdan bağımsız olarak gerçek müşteriye satış e-postası atamaz.

Testler: `python tools/codex_acceptance.py`; mock SMTP testleri herhangi bir mail göndermez.
