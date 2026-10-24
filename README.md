# 🎯 Müşteri Avcısı AI — Public Telegram Lead Hunter

**Dağıtım:** [emirhankaya985-cloud/musteri-avcisi-ai](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai) — kaynak private repodan **izin listeli yeni Git geçmişiyle** aktarıldı. Eski Git geçmişi ve müşteri CRM kayıtları aktarılmadı.

## Ne yapar?

- Kadıköy'deki küçük bir pilot alanda OpenStreetMap verilerinde işletme kayıtlarını inceler.
- Her çalıştırmada en fazla **5 yeni işletme** için **yalnızca hesabın sahibine** Telegram fırsat mesajı gönderir.
- OSM'de eksik web sitesi kaydı, gerçek dünyada sitenin kesin yokluğu demek değildir.
- 🔴 **WEB SİTESİ FIRSATI:** OSM kaydında web adresi yoksa sektörüne uygun site fikri gösterir. Bu **doğrulanmış web sitesi eksikliği değildir**; önce kontrol et.
- 🟢 **OTOMASYON FIRSATI:** OSM'de web adresi kayıtlıysa iş koluna göre randevu/talep otomasyonu fikri gösterir. İşletmenin bu çözüme ihtiyaç duyduğu **kanıtlanmış değildir**.
- Her işletme için **isim, sektör, website kaydı, telefon ve adres bilgisine göre** gerekçe, öneri ve manuel iletişim taslağı kişiselleştirilir. Otomatik satış mesajı gönderilmez.

- `data/seen.json` yalnızca herkese açık OSM nesne kimliklerini tutar; başarılı Telegram gönderiminden sonra güncellenir.
- **Potansiyel müşteriye otomatik e-posta, DM veya başka ileti göndermez.** Mesajdaki teklif yalnızca kullanıcı tarafından manuel değerlendirilecek bir taslaktır.

## Çalıştırma

```bash
python -m unittest discover -s tests -v
python -m leadhunter demo
```

Demo `dist/telegram-demo.txt` dosyasını üretir. Sentetik örnekler kullanır; gerçek mesaj yollamaz.

## GitHub Actions kurulumu — yeni hesapta gerekli

1. [Hedef depo Actions Secrets](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/settings/secrets/actions) bölümüne yalnızca **Repository secrets** olarak şu ikisini tanımla:
   - `TELEGRAM_BOT_TOKEN` — Telegram BotFather bot tokenı
   - `TELEGRAM_CHAT_ID` — sadece kendi özel Telegram sohbetinin sayısal chat ID'si
2. Telegram botuna özel sohbetten `/start` veya `/chatid` gönderdiğinden emin ol. ID'yi bulmak için kodda `tools/get_chat_id.py` bulunur; bunu kendi cihazında çalıştırabilirsin. **Chat ID'yi public Actions loglarına yazma.**
3. [Offline Tests](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/workflows/ci.yml) başarılı olmalı.
4. [Telegram Lead Digest](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/workflows/lead-digest.yml) → `Run workflow` ile canlı test yapabilirsin. İş akışı değiştiğinde `main` push'u da tek seferlik canlı smoke testini tetikler.

### Zamanlama

`23 7 * * 1-5` = **Pazartesi–Cuma 07:23 UTC / 10:23 Türkiye saati (UTC+3)**. GitHub zamanlanmış çalıştırmaları gecikebilir veya zaman zaman atlayabilir. Bir sonraki gerçek `schedule` tetiklemesi başarıyla sonuçlanmadan otomatik yayın doğrulandı demeyin.

İsteğe bağlı `SCAN_BBOX` repository variable'ı yalnızca küçük pilot alanlar için ayarlanabilir; varsayılan `40.982,29.015,41.008,29.055`.

## Güvenlik

- Bu public depoda eski Git geçmişi, `.env`, gerçek müşteri e-postaları, CRM kayıtları, SMTP / Gmail gönderim kodu veya token bulunmamalı.
- GitHub Secrets eski hesaptan otomatik taşınmaz; yeni public depoda ayrıca tanımlanması gerekir.
- Kodun `contents: write` izni yalnızca başarılı Telegram gönderimlerinin kamuya açık OSM kimliklerini kaydetmek için kullanılır.
- Telegram başarısızsa iş akışı kırmızı görünür; başarısız adım başarı olarak kabul edilmez.
- Demo web sitesi `demo-site/index.html` dosyasında; ödeme/gerçek rezervasyon backend'i içermez.
- OSM kayıtlarını manuel kontrol et; izinsiz ticari ileti göndermeyi otomatikleştirme.

Veri kaynağı: [© OpenStreetMap contributors, ODbL](https://www.openstreetmap.org/copyright).
