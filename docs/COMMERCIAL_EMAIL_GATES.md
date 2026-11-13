# Ticari elektronik ileti güvenlik kapısı — 7 Kasım 2026

Bu doküman hukuki görüş değildir. Müşteri Avcısı'nın mevcut otomatik
gönderim hattında neden **kapalı** kaldığını ve hangi kayıtlarla açılabileceğini
operasyonel olarak açıklar.

Resmî kaynaklar:
- Ticaret Bakanlığı, ticari elektronik iletiler, genel bilgiler:
  https://ticaret.gov.tr/ic-ticaret/ticari-elektronik-iletiler/genel-bilgiler
- Ticaret Bakanlığı, İYS:
  https://ticaret.gov.tr/ic-ticaret/ticari-elektronik-iletiler/ileti-yonetim-sistemi-iys
- Ticaret Bakanlığı, elektronik ticaret SSS:
  https://ticaret.gov.tr/ic-ticaret/sikca-sorulan-sorular/elektronik-ticaret

Tacir/esnaf alıcılara gönderilen ticari iletiler için genel ön onay istisnası
vardır. Bu durum **OSM işletme etiketiyle otomatik ispatlanamaz**. İYS'ye
kayıt ve alıcının ret hakkını kullanıp kullanmadığının doğrulanması,
hizmet sağlayıcı kimlik/iletişim/ret bilgilerinin doğru iletide bulunması
ve ilgili kayıtların saklanması ayrıca gerekir. Gerçek kişi iletişim
bilgileri için diğer uygulanabilir veri koruma hükümleri de değerlendirilir.

Şu an:
- OSM / MX kaydı gönderim izni değildir.
- Özel PostgreSQL'de bu alıcıya ait doğrulanmış, güncel uygunluk kayıtları
  yoksa `eligible_recipient` false döndürür.
- Gönderim geçmişi `sending` / `uncertain` / `accepted` ise aynı
  alıcıya kesinlikle yeniden otomatik mail gönderilmez.
- Gmail DSN `failed` / `delayed` ise kayıt tekrar gönderime kapalıdır.
- Eski yüksek bounce oranı gönderici itibar korumasını tetikler.
- 13 Kasım 2026 owner talimatıyla saatlik `lead-digest` iş akışındaki genel `AUTO_MAIL_ENABLED` anahtarı açıldı. Bu anahtar tek başına alıcı izni değildir: her gönderimde özel Postgres kaydı için `eligible_recipient` kontrolü zorunludur; güncel, doğrulanmış izin/İYS kaydı olmayan adres gönderilmez. Günlük adet kotası owner talimatıyla kaldırıldı; her alıcı için doğrulanmış güncel izin/İYS, ret, mükerrerlik ve gönderici-itibar kontrolleri korunur. İş akışı, Gmail gönderici adresi/uygulama parolası ve özel Postgres bağlantısını yalnızca GitHub Actions secret'larından runtime'a aktarır; değerleri loglamaz. Bu secret'lardan biri eksik/geçersizse tarama ve Telegram raporu devam eder, otomatik e-posta kapalı kalır. OSM/MX adresi tek başına gönderim izni sayılmaz.
- Hiçbir dokümantasyon, test, API sağlık sonucu veya kullanıcıya
  gönderilmiş Telegram taslağı e-posta gönderim izni oluşturmaz.

Genel otomatik gönderim anahtarı açık olsa da her alıcı için özel kayıttaki
güncel uygunluk, ret/İYS, mükerrerlik ve itibar kontrolleri SMTP çağrısından önce
çalışır. Bu kontroller geçmeyen alıcıya gönderim yapılmaz. SMTP kabulü alıcı
posta kutusuna teslim kanıtı değildir; Gmail DSN ve kesin eşleşmiş yanıtlar
ayrı kaydedilir. Uygun alıcı bulunmadığında doğru sonuç **0 gönderim**dir.
