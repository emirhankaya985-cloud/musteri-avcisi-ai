# Müşteri Avcısı — canlı hukuki ve kaynak kullanım engelleri (14.11.2026)

Bu belge otomatik pazarlama gönderimi için **izin belgesi veya hukuki görüş değildir**. Mevcut kural: `AUTO_MAIL_ENABLED=false`. GitHub secret, Neon, SMTP claim, alıcı geçmişi veya teslimat kayıtları silinmez.

## Gmail — gerçek 15 gönderimin son kontrolü
- Bağlı Gmail Gönderilenler klasöründeki 15 e-posta alıcı + konu + tam gövde ile private Neon'daki 15 frozen SMTP kabul kaydına ayrı ayrı eşleşti. 15 Gmail API message ID ve 15 thread ID yalnızca private Neon'da kayıtlıdır.
- **4 kesin DSN hatası:** 1 `dns_nxdomain` (alıcı alan adı çözümlenemiyor), 1 `mailbox_missing` (SMTP 550/no such user), 1 `relay_denied` (SMTP 554/5.7.1), 1 `connection_refused` (iki gecikme DSN'sinden sonra 01.11.2026 tarihinde kesin başarısız).
- Önceki 15 kabul gelen kutusuna 15 teslim anlamına gelmez. **11 teslim doğrulanmadı**; eşleşen doğrulanmış müşteri yanıtı 0.
- Göndericiye ait 4/15 = %26,67 kesin teslimat hatası, mevcut %15 itibar sigortası nedeniyle otomatik akışı durdurur. Hata geçmişini silerek veya bu adreslere yeniden e-posta atarak oranı düşürme.
- Gmail OAuth izni, mevcut GitHub IMAP app-password ve ChatGPT Gmail bağlantısından ayrıdır; yalnızca erişim gördük diye üretim secret'larının aynı OAuth durumunda olduğunu varsayma.
- Adres engelleri: NXDOMAIN, mailbox_missing, relay_denied ve final connection_refused kayıtları tekrar pazarlama gönderimi için engellidir.

## Türkiye — İYS ve KVKK
- Ticaret Bakanlığı: https://www.ticaret.gov.tr/ic-ticaret/ticari-elektronik-iletiler/genel-bilgiler
- Bakanlığın açıkladığı tacir/esnaf istisnasında önceden onay gerekmeyebilir; **istisnanın gerçekten uygulanabilirliği doğrulanmalıdır**. Yönetmelik 6/6'ya göre ilgili adresin İYS kaydı ve gönderimden önce ret durumunun kontrolü gerekir: https://www.lexpera.com.tr/mevzuat/yonetmelikler/ticari-iletisim-ve-ticari-elektronik-iletiler-hakkinda-yonetmelik
- Tüketici/istisna dışı alıcıda geçerli ileti izni gerekir. Ticari e-posta göndererek izin talep etme. Her alıcıya ret mekanizması, gönderen kimliği ve zorunlu kayıt yükümlülükleri ayrı doğrulanır.
- KVKK, kişisel verinin yalnızca internette görünmesini otomatik ve sınırsız pazarlama izni olarak kabul ettirmez; işleme şartı, belirli amaç, ölçülülük ve hakların korunması gerekir. Örnek Kurul kararı: https://www.kvkk.gov.tr/Icerik/7292/2022-31
- Mevcut private Neon denetimi: 24 iletişim adayı, 24 belgelemeli risk-denetimi, **0 doğrulanmış gönderim dayanağı**. Kodun gönderim yetkisi kapalı kalacaktır.

## Gmail sağlayıcı yükümlülükleri
- Google gönderici gereklilikleri: https://support.google.com/mail/answer/81126
- Tüm göndericilerde SPF **veya** DKIM, TLS ve doğru tanımlama asgari gereklilikler arasındadır. Yüksek hacimli Gmail alanlarına gönderim için SPF **ve** DKIM **ve** DMARC, uygun abonelikten çıkma mekanizmaları gibi ek yükümlülükler vardır. Sender domain'in gerçek DNS/Google Postmaster durumunu kontrol etmeden `PASS` raporlama.
- Bu çalışma SPF/DKIM/DMARC DNS kaydını veya alan adı sahipliğini değiştirmemiştir; dört DSN'de doğrudan giderilebilir bir sender authentication hatası **doğrulanmadı**.

## OpenStreetMap / Overpass işletim sınırı
- Kamuya açık global Overpass kaynağının düzenli işler için tavsiyesi genellikle 100 sorgu ve 10 MB veri/gün altında kalmak; paralel yük ve 429/406 bypass yapılmaması ve ticari kullanım için kendi sunucusu veya ücretli kaynak seçilmesidir: https://wiki.openstreetmap.org/wiki/Overpass_API
- Maliyet hedefi 0 TL olduğundan agresif/parallel API tarama açma; 402 parçayı şimdi tamamlandı gösterme. Mevcut tek sağlayıcı/ziyaret ve iki küçük parça sınırını koru, bekleyen parçalara ait durumları private Neon'da izlet.
- Hacimli gelecekteki taramalar için resmi veri dökümleri ve ODbL atıf/lisans yükümlülüğü ayrı değerlendirilmelidir. Kaynak sağlayıcının koşulları geçerli olmadan otomatik yeni veri kaynağı kurma.

## Kullanıcı onayı gerektiren noktalar
1. Ticari alıcı statüsü/İYS kontrolü/ret geçmişi ve gerektiğinde ileti izni, yetkili bir işlem sahibi tarafından doğrulanmalı.
2. Gönderici hesabı, alan adı ve itibar toparlanması denetlenmeli; 4 DSN nedenine uygun adres bastırmaları sürmeli.
3. Bunlar tamamlanmadan ve ayrı açık kullanıcı onayı verilmeden pazarlama SMTP'si açılmaz.
4. 985 AI Control Center'ın gerçek deposu ve yetkili servis kimliği paylaşılmadan private Neon rolü `NOLOGIN` kalır, panel bağlı sayılmaz.
