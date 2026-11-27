# Müşteri Avcısı AI

Kadıköy pilot alanında OSM işletme kayıtlarını inceler ve adayları özel Neon CRM'e kaydeder. Web sitesi/otomasyon sinyalleri doğrulanmış ihtiyaç sayılmaz. Otomatik işletme e-postası ancak hukuki uygunluk, mükerrerlik, günlük kota ve gönderici itibarı kontrolleri geçerse gönderilir; 24 Kasım 2026 itibarıyla gönderici devresi kapalıdır.

## Otonom akış

- **Haftanın 7 günü, saatte bir (yaklaşık XX:13 TRT):** `Telegram Lead Digest`. GitHub cron gecikebilir. Yeni adaylar özel Neon'a kaydedilir; sahibine rutin yeni-lead mesajları kapalıdır. Mevcut 15 SMTP kabulinin 4'ünde teslimat hatası görüldüğü için gerçek işletme gönderimi durdurulmuştur. Alıcı uygunluğu veya ret hakkı varsayılmaz.
- Önce bekleyen özel Telegram mail raporları kurtarılır. Bu adım SMTP kullanmaz; OSM erişimine bağlı değildir. Rapor hatası veya 100 kayıttan büyük kalan kuyruk yeni taramayı durdurur.
- **Butonsuz Telegram:** 1 Kasım 2026 sahibin isteği üzerine yeni fırsat mesajlarında Evet/Hayır/Beklet yoktur. Otomasyon karar beklemeden araştırır ve özel sohbete e-posta taslağı yollar. Eski Telegram callback'leri kapalıdır; eski CRM kayıtları değiştirilmez. Gmail yanıt ve teslimat izlemesi ayrı saatlik görevdir.
- Gerçek otomatik SMTP `leadhunter.automatic_mail` modundadır, ancak 4/15 (%26,7) teslimat hatası %15 gönderici durdurma eşiğini aştığı için PostgreSQL devresi gönderimi engeller. Son denetimde yasal uygunluğu doğrulanmış alıcı ve gönderilebilir aday sayısı 0'dır. Bu nedenle **canlı işletme e-postası gönderilmez**.
- Her taramada en fazla **5** aday değerlendirilir. PostgreSQL günlük en fazla 5 gönderim talebini kilit altında sınırlar; aynı işletme/alıcı ve belirsiz gönderim tekrar denenmez. Geçmiş hata/ret/claim kayıtları silinmez veya yeniden gönderimle gizlenmez.
- Varsayılan `MAIL_DRAFT_MODE=template`: AI anahtarı gerektirmez. AI modu isteğe bağlıdır.
- Yalnızca kaynakta yayımlanmış geçerli adresler kullanılır; alıcı adresi tahmin edilmez.
- **Her gün 23:59 TRT:** GitHub Actions özel Neon CRM'den güncel Excel raporunu ve metrik özetini üretip yalnızca sahibin pozitif, özel Telegram sohbetine gönderir. Workbook Actions artifact'ı veya public depoya yazılmaz; alanı olmayan şehir/WhatsApp/doğrulama bilgileri bilinmiyor olarak kalır.
- SMTP'den önce özel veritabanına gönderim talebi kaydedilir. İşletme kimliği ve alıcı adresi kontrolü PostgreSQL kilidi altında yapılır. Otomatik takip maili yoktur.
- SMTP kabulü **gelen kutusuna teslim değildir**. Alıcı, konu, tam gövde ve sonuç Telegram'a aktarılır; her parça API makbuzuyla doğrulanır. Telegram hatası maili yeniden göndermeyi gerektirmez.
- Eski rapor kurtarması ve yeni tarama ayrı adımlardır. `Telegram mail sonuç raporu` sayacı SMTP kabul veya yeni işletme sayısı değildir.

Ayrı `Owner Verified Business Mail Batch`, yalnızca açık owner dispatch ile özel `OWNER_MAIL_BATCH_JSON` secret'ındaki en fazla 15 araştırılmış kaydı işler. Günlük tarama bu batch'i kendiliğinden tekrar çalıştırmaz. Ayrıntılar: [mail ayarları](docs/OWNER_APPROVED_MAIL.md).

## Kurulum ve özel veriler

Repository Secrets: `GMAIL_SENDER_ADDRESS`, `GMAIL_APP_PASSWORD`, `REVIEW_DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Postgres SSL zorunludur. Şema ve opsiyonel karar butonları: [özel review kurulumu](docs/PRIVATE_REVIEW_SETUP.md). Web kimlikleri için [migration](migrations/001_verified_website_leads.sql) gerekir.

Alıcılar, mail gövdeleri ve gönderim geçmişi özel veritabanında kalır. Public dosyalara yalnızca OSM kimlikleri ve günlük tarih yazılır. Telegram kabulünden sonra veritabanı işaretlemesi yapılamazsa bildirim tekrarlanabilir; mail tekrarı kapalıdır. Secrets ve gerçek müşteri verileri loglara/artifact'lara eklenmez.

İYS uygunluk kanıtını özel Neon CRM'e eşlemek için dosya biçimi ve komut:
[özel İYS kanıtı içe aktarma](docs/IYS_EVIDENCE_IMPORT.md). Bu adım gerçek İYS kontrolünün yerine geçmez ve gönderici itibar kilidini kaldırmaz.

## Doğrulama ve sınırlar

```bash
python tools/codex_acceptance.py
```

Offline testler sentetik veri ve mock servisler kullanır. CI ayrıca geçici PostgreSQL üzerinde aynı işletme, aynı alıcıya eşzamanlı claim ve belirsiz gönderim sonrası tekrar engelini sınar; gerçek işletmelere mesaj göndermez.

30 Ekim 2026 kanıtları:

- [Güncel main offline CI: 150 test başarılı](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40918211203).
- [Eski hafta içi schedule](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/41025477031) ve [yedek schedule](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/41034390631) geçmişte başarılıydı; yeni **saatlik schedule** için ilk gerçek tetikleme ayrıca doğrulanmalıdır.
- [29 Ekim özel batch](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40917655884): 15 yeni SMTP kabulü, 0 belirsiz; tam metin raporlama yolu başarıyla tamamlandı. Gelen kutusu teslimi kanıtlanmadı.

GitHub schedule gecikebilir/atlanabilir; dakik çalışma garantisi yoktur. Gmail teslimat/yanıt kontrolü ayrı saatlik job, Telegram karar işleme ise ayrı 15 dakikalık job'dur. Sonraki gerçek başarılı `schedule` olayı ve canlı Telegram gönderimi ayrı kanıtlarla değerlendirilir. Yeni rapor kurtarma adımının canlı sonucu henüz gözlemlenmedi. Dar örneklemde sıfır yeni aday normal olabilir; sistem yeni müşteri veya satış garantilemez.

Telegram owner komut işleyicisi yalnızca sahibin özel sohbetinde /durum ve /eposta komutlarını işler; yeni fırsatlar için butonlar kapalıdır. Gmail owner-only test yalnızca sahibine gider. `demo-site/index.html` statik örnektir; gerçek rezervasyon veya ödeme hizmeti değildir. Ek ücretli hizmet/abonelik oluşturulmaz.

Kaynak: [OpenStreetMap contributors, ODbL](https://www.openstreetmap.org/copyright).

### Korunmuş otomatik SMTP geçişi (1 Kasım 2026)

Saatlik workflow artık `AUTO_MAIL_ENABLED=true` gönderim talebini taşır; **bu, otomatik olarak gönderim yapılacağı anlamına gelmez.** Gönderimden önce private PostgreSQL içinde şu koşulların tamamı sağlanır:

- Gönderilecek **birebir adres** için kanıt referansı bulunan, güncel ve iptal edilmemiş bir alıcı izin kaydı veya işletmenin tacir/esnaf statüsü + İYS kayıt/ret sonucu doğrulaması. OSM şirket etiketi, genel e-posta ve MX kaydı yeterli değildir.
- Gönderimin daha önce aynı e-posta adresine ya da güçlü biçimde aynı işletmeye yapılmamış olması; ret edilen, belirsiz veya gönderilmiş kayıtların korunması.
- Günlük Türkiye saatine göre en fazla 5 gerçek SMTP claim'i; PostgreSQL advisory lock altında tek işlem.
- En az 10 SMTP kabul kaydında **%15 veya üzeri başarısız teslimat** varsa küresel gönderim durur. Mevcut 15 kabul / 3 başarısız teslimat = %20, bu nedenle **bugün gerçek mail gönderilmeyecek**. Bot yalnızca sahibine yeni fırsat ve gönderilmemiş taslak gösterecektir.

İYS bağlantısı henüz gerçek hayatta yapılmadı; hiçbir müşteri kaydına sahte onay veya ret doğrulaması işlenmedi. Bu engeller çözülmeden SMTP sonucunu başarı olarak raporlama.


## İşletim politikası — 24 Kasım 2026 güncellemesi
- Saatlik taramalar GitHub Actions üzerinde sürer. Yeni adaylar özel Neon CRM'de tutulur; rutin Telegram fırsat ve günlük özet bildirimleri kapalıdır.
- Kullanıcı otomatik e-posta akışını yeniden istedi; workflow anahtarı açık tutulur. Her gönderim yine özel kayıttaki güncel izin/İYS ve ret kontrolünden, mükerrerlik korumasından, 5/gün kotasından ve gönderici itibarı devresinden geçer. OSM/MX kaydı izin kanıtı değildir.
- Mevcut eski teslimat hataları gönderici devresini kapalı tuttuğu sürece **gerçek SMTP gönderimi yapılmaz**. Tarihsel 15 kabul/4 başarısız teslimat kayıtları korunur; oranı düşürmek için deneme gönderimi yapılmaz.
- `migrations/004_owner_osm_tile_ledger.sql` özel Neon'da 402 harita parçasını `confirmed/pending/retry/blocked` şeklinde takip eder. Public tile ledger tekrar başlama kaynağıdır; Neon panelin salt-okunur kopyasıdır.
- `control_center_musteri_v1` toplulaştırılmış veri sözleşmesidir; merkezi panelin ayrı deposu ve canlı Render dağıtımı doğrulanana kadar *entegre edildi* denmez.


## Aday öncelik algoritması — 24 Kasım 2026

Her taramada adaylar **2 → 1 → 3** sırasıyla değerlendirilir:

1. **Kategori 2 — WhatsApp otomasyonu:** Yalnızca güncel, kaynaklı WhatsApp müşteri hizmetleri otomasyonu ihtiyacı doğrulanmışsa.
2. **Kategori 1 — web sitesi:** Yalnızca güncel, kaynaklı web sitesi yokluğu doğrulanmışsa.
3. **Kategori 3 — birleşik çözüm:** Web ve WhatsApp varlığı, gerçek otomasyon ihtiyacı ayrı ayrı kanıtlanmalı; ayrıca altı puan bileşeninin tamamı güncel kanıtla dolu olmalı ve ticari puan en az 75 olmalı.

Eksik OSM etiketi bilinmeyen veridir; yokluğu kanıtlamaz. Eşleşmeyen işletme “araştırma gerekli” olarak kalır. Altı ağırlıklı bileşen (ihtiyaç 30, iletişim doğruluğu 20, hizmet uyumu 20, ticari potansiyel 15, dijital açık 10, güncellik 5) için kanıt yoksa puan uydurulmaz; kapsama ve olası aralık gösterilir. Bu ticari puan, araştırma tamlığı puanından ayrıdır.

Aynı sınıfta daha yüksek kayıt tamlığı (mevcut 0–100 araştırma puanı) önce gelir. Sınıflandırma e-posta izni değildir. Gerçek gönderim için özel kayıttaki güncel izin/İYS ve ret kontrolü, tekrar gönderim koruması, günlük kota ve gönderici itibarı devresi zorunludur. Tarihsel teslimat başarısızlıkları gönderici devresini kapalı tutuyorsa otomatik tarama devam eder, işletmelere SMTP göndermez.
