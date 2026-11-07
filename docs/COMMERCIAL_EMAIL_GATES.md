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
- Cron job `AUTO_MAIL_ENABLED: 'false'` olarak kalır.
- Hiçbir dokümantasyon, test, API sağlık sonucu veya kullanıcıya
  gönderilmiş Telegram taslağı e-posta gönderim izni oluşturmaz.

Yetkili, kanıtlı alıcı kaydı bulunmadan, İYS/ret doğrulaması yapılmadan ve
gönderici itibar devresi düzeltilmeden SMTP etkinleştirilmez. SMTP kabulü
alıcı posta kutusuna teslim kanıtı değildir; Gmail DSN ve kesin eşleşmiş
yanıtlar ayrı kaydedilir. Uygun alıcı bulunmadığında doğru sonuç **0 gönderim**dir.
