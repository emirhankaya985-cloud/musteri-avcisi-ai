# Müşteri Avcısı AI

Kadıköy pilot alanında OSM işletme kayıtlarını inceler; uygun yeni adaylara sahibin daha önce yetkilendirdiği kapsamda bir tanışma e-postası gönderir ve sonucu sahibinin özel Telegram sohbetine tam metinle raporlar. Mevcut web sitesi veya otomasyon ihtiyacı kesin olarak varsayılmaz.

## Otonom akış

- Hafta içi **10:23 TRT**, yedek **11:53 TRT**: `Telegram Lead Digest`.
- Önce bekleyen özel Telegram mail raporları kurtarılır. Bu adım SMTP kullanmaz; OSM erişimine bağlı değildir. Rapor hatası veya 100 kayıttan büyük kalan kuyruk yeni taramayı durdurur.
- Her taramada en fazla **5** uygun aday işlenir. Reddedilmiş/bekletilmiş, gönderilmiş veya SMTP sonucu belirsiz kayıtlar otomatik tekrar gönderilmez.
- Varsayılan `MAIL_DRAFT_MODE=template`: AI anahtarı gerektirmez. AI modu isteğe bağlıdır.
- Yalnızca kaynakta yayımlanmış geçerli adresler kullanılır; alıcı adresi tahmin edilmez.
- SMTP'den önce özel veritabanına gönderim talebi kaydedilir. İşletme kimliği ve alıcı adresi kontrolü PostgreSQL kilidi altında yapılır. Otomatik takip maili yoktur.
- SMTP kabulü **gelen kutusuna teslim değildir**. Alıcı, konu, tam gövde ve sonuç Telegram'a aktarılır; her parça API makbuzuyla doğrulanır. Telegram hatası maili yeniden göndermeyi gerektirmez.
- Eski rapor kurtarması ve yeni tarama ayrı adımlardır. `Telegram mail sonuç raporu` sayacı SMTP kabul veya yeni işletme sayısı değildir.

Ayrı `Owner Verified Business Mail Batch`, yalnızca açık owner dispatch ile özel `OWNER_MAIL_BATCH_JSON` secret'ındaki en fazla 15 araştırılmış kaydı işler. Günlük tarama bu batch'i kendiliğinden tekrar çalıştırmaz. Ayrıntılar: [mail ayarları](docs/OWNER_APPROVED_MAIL.md).

## Kurulum ve özel veriler

Repository Secrets: `GMAIL_SENDER_ADDRESS`, `GMAIL_APP_PASSWORD`, `REVIEW_DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Postgres SSL zorunludur. Şema ve opsiyonel karar butonları: [özel review kurulumu](docs/PRIVATE_REVIEW_SETUP.md). Web kimlikleri için [migration](migrations/001_verified_website_leads.sql) gerekir.

Alıcılar, mail gövdeleri ve gönderim geçmişi özel veritabanında kalır. Public dosyalara yalnızca OSM kimlikleri ve günlük tarih yazılır. Telegram kabulünden sonra veritabanı işaretlemesi yapılamazsa bildirim tekrarlanabilir; mail tekrarı kapalıdır. Secrets ve gerçek müşteri verileri loglara/artifact'lara eklenmez.

## Doğrulama ve sınırlar

```bash
python tools/codex_acceptance.py
```

Offline testler sentetik veri ve mock servisler kullanır. CI ayrıca geçici PostgreSQL üzerinde aynı işletme, aynı alıcıya eşzamanlı claim ve belirsiz gönderim sonrası tekrar engelini sınar; gerçek işletmelere mesaj göndermez.

30 Ekim 2026 kanıtları:

- [Güncel main offline CI: 150 test başarılı](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40918211203).
- [Gerçek schedule](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/41025477031) ve [yedek schedule](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/41034390631): başarılı; ikisi de 20 eski kayıt, 0 yeni aday, 0 bildirim.
- [29 Ekim özel batch](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40917655884): 15 yeni SMTP kabulü, 0 belirsiz; tam metin raporlama yolu başarıyla tamamlandı. Gelen kutusu teslimi kanıtlanmadı.

GitHub schedule gecikebilir/atlanabilir; dakik çalışma garantisi yoktur. Sonraki gerçek başarılı `schedule` olayı ve canlı Telegram gönderimi ayrı kanıtlarla değerlendirilir. Yeni rapor kurtarma adımının canlı sonucu henüz gözlemlenmedi. Dar örneklemde sıfır yeni aday normal olabilir; sistem yeni müşteri veya satış garantilemez.

Üç butonlu inbox yalnızca sahibin kararlarını işler. Gmail owner-only test yalnızca sahibine gider. `demo-site/index.html` statik örnektir; gerçek rezervasyon veya ödeme hizmeti değildir. Ek ücretli hizmet/abonelik oluşturulmaz.

Kaynak: [OpenStreetMap contributors, ODbL](https://www.openstreetmap.org/copyright).
