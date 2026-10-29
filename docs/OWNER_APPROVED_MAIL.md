## Son istek: API olmadan şimdi gönderim

29 Ekim 2026: Kullanıcı AI/API bağlantısını sonraya bıraktı ve önceki+güncel adaylara şimdi mail istedi. `MAIL_DRAFT_MODE=template` varsayılandır; sektör ve işletme adına göre hazırlanmış konu/tam gövde kullanılır. AI çağrısı veya anahtarı gerekmez. Daha sonra `MAIL_DRAFT_MODE=ai` seçilirse AI ayarları zorunludur.

`Owner Requested Mail Catch-up` iş akışı mevcut Gmail secrets ile önce sahibine gerçek bir SMTP test maili gönderir; başarısızsa işletmelere geçmez. Ardından özel kayıttaki eski review/email_pending adaylarını güncel OSM verisiyle eşleyip, en fazla 5 yeni adayı ekler. Reddedilmiş/bekletilmiş/sent/SMTP sonucu belirsiz kayıtlar korunur. İşletme e-postaları tahmin edilmez. Kaynağı olmayanlar atlanır ve özel Telegram raporuna yazılır. İş akışı yalnızca workflow_dispatch veya execute-outreach.yml değişikliğini içeren `[run-owner-outreach-20261029]` işaretli owner-requested commit ile çalışır. Bu marker sıradan kod push'larında yoktur.

Önceki aşağıdaki AI-zorunlu açıklamaları yalnızca ai moduna aittir. Günlük tarama saatleri korunur ve hazır metinlerle çalışır.

# Otomatik işletme e-postası — 29 Ekim 2026

Kullanıcı doğrudan gönderim ve sonrasında Telegram'da tam metin/sonuç istedi; önceki tekil Telegram onayı bu otomatik yol için kaldırıldı.

Üretim digest workflow'u `AUTO_MAIL_ENABLED=true` ile çalışır. Mevcut hafta içi 10:23 TRT ve 11:53 TRT yedek saatleri değişmedi. Push iş fırsatı taraması veya işletme e-postası başlatmaz. Her taramada en fazla beş aday işlenir. Eski reddedilmiş/bekletilmiş kayıtlar otomatik işlenmez. Eski onay bekleyen kayıtlar da otomatik toplu kuyruğa alınmaz.

- OSM kaydındaki `contact:email` veya `email` kullanılır; adres tahmin edilmez. Kaynağa kaydedilmiş adresin güncel olduğu garanti edilmez.
- Eksik/geçersiz adres atlanır ve Telegram'a bildirilir. Aynı OSM işletmesi veya aynı alıcı adresi tekrar gönderilmez. Otomatik takip maili yoktur.
- AI işletme adı, sektör ve site kaydıyla Türkçe tam konu/metin üretir. Fiyat/referans/sonuç uydurmaması ve doğrulanmamış eksiklik iddiasında bulunmaması istenir. Her mailin kalitesi canlı AI denemesiyle ayrıca incelenmelidir.
- Kayıt, gönderim sonucu ve tam metin sadece özel Postgres `owner_leads.lead_data._auto_mail` alanındadır. Public depoda yalnızca OSM kimlikleri tutulur. Şema değişikliği yoktur.
- Alıcı tekrar kontrolü advisory transaction lock ile seri yapılır. Gönderim talebi SMTP'den önce kalıcılaştırılır. SMTP sonucu belirsiz veya işlem çökerse otomatik tekrar yapılmaz; durum Telegram'a belirsiz olarak bildirilir.
- SMTP kabulü gelen kutusuna teslim kanıtı değildir. Başarılı kabul sonrası işletme/alıcı/konu/gövde Telegram'a aynen raporlanır. Telegram hatası maili tekrar göndermez; sonraki çalışmada özel kayıttaki bildirim tekrar denenir. Telegram kabul edip veritabanı işaretlemesi yapılamazsa bildirim tekrarı mümkün, mail tekrarı kapalıdır.

## Runtime ayarları

GitHub Secrets: mevcut `GMAIL_SENDER_ADDRESS`, `GMAIL_APP_PASSWORD`, `REVIEW_DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` ve AI için `MAIL_AI_API_KEY` veya `NVIDIA_API_KEY`.

GitHub Variables ile model/endpoint değiştirilebilir: `MAIL_AI_MODEL`, `MAIL_AI_URL`. Bu ayarlar yoksa NVIDIA `nvidia/nemotron-3.5-super-vl-120b-a12b` ve `https://integrate.api.nvidia.com/v1/chat/completions` kullanılır. Anahtar olmadan ücretsiz dahil hiçbir AI çağrısı yapılmaz. Ücretli servis/abonelik oluşturulmadı; sağlayıcıdaki ücretsiz kota/kullanılabilirlik ayrıca kontrol edilmelidir. Zorunlu ayarlar eksikse işletme gönderiminden önce açık hata verilir.

Devre dışı bırakmak için workflow'daki `AUTO_MAIL_ENABLED` false yapılır. Eski ayrı onaylı mail kodu mevcuttur, fakat üretim otomatik digest için kullanılmaz.

## Doğrulama

`python tools/codex_acceptance.py`: 135 offline test. AI, SMTP ve Telegram testleri mock kullanır; gerçek işletmelere test maili gönderilmedi. Üretim Postgres concurrency testi, canlı AI çağrısı ve gerçek otomatik işletme maili henüz kanıtlanmadı. Uzak CI sonucu teslim raporunda ayrı belirtilir.
