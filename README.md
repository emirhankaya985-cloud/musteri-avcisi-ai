# Müşteri Avcısı AI — Public Telegram sürümü

Bu **temiz Git geçmişli** sürüm, OpenStreetMap'teki işletmeleri tarayıp
sahibine Telegram üzerinden en fazla 5 yeni fırsat gönderir.
İşletmelere otomatik mesaj veya e-posta göndermez.

## Kurulum
1. Yeni GitHub hesabında **boş public** `musteri-avcisi-ai` deposu oluştur.
2. Bu ZIP'in içeriğini yeni deponun `main` dalına, **yeni Git geçmişiyle** yükle.
3. Settings → Secrets and variables → Actions → Repository secrets kısmında
   `TELEGRAM_BOT_TOKEN` ve `TELEGRAM_CHAT_ID` ekle. Gizli değerleri koda yazma.
4. Actions → `Offline Tests` başarılı olduktan sonra
   Actions → `Telegram Lead Digest` → `Run workflow` ile canlı test yap.
5. Sonraki zamanlanmış kontrol hafta içi 10:23 Türkiye saati.

### Veri/gizlilik
`data/seen.json` yalnızca OpenStreetMap nesne kimliklerini tutar.
Gmail otomasyonu, müşteri adresleri, izin kanıtları ve eski Git geçmişi
bu pakete **dahil değildir**. Gmail'in güvenli çalışması için ayrı özel
veritabanı ve tekrar-gönderim koruması gerekir.
GitHub Secrets eski depodan otomatik aktarılmaz; yeni hesapta yeniden ekle.
