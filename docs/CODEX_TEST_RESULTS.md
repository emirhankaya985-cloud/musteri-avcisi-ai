# 26 Ekim 2026 — Doğrudan OSM API kurtarması ve gerçek Telegram teslimatı

**KABUL: KOD/CI PASS; GERÇEK SAHİBE TELEGRAM TESLİMATI + NEON KAYDI PASS; ÜÇ BUTONDAN SAHİP TIKLAMASI UNVERIFIED; GMAIL BEKLİYOR.**

- **Üretim commit:** `c2f5c3daa1f8bbbdd1e9936a8cce793e0f793989` (PR #16).
- **Son ana dal CI:** [Offline Tests #40343666382](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40343666382) — **115/115 PASS**.
- **Bağımsız, ücretsiz API kanıtı:** [OSM Main API probe #40342859590](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40342859590) — küçük harita sorgusunda 2.665 öğe; public listeden 3/3 mevcut işletme kimliği doğru okundu.
- **Gerçek sahibi Telegram teslimatı:** [Owner-Only Live Acceptance #40343666406](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40343666406) — **SUCCESS**. Log: `Kaynak: doğrudan OSM API (sınırlı örneklem)`, `OSM tarama: 20 ham kayıt; 20 geçerli; 20 önce görülmüş; 0 yeni aday`, `Gönderilen yeni fırsat: 5`. Bu beş işletme eski public OSM kimliklerinden yeniden butonlu incelemeye alınmıştır; sıfır yeni keşfi beş yeni müşteri olarak göstermeyin.
- **Neon canlı doğrulama:** `owner_leads` statü `review` sayısı **5**, bunların **5/5** tanesinde `telegram_message_id` kayıtlı. Özel gerçek işletme detayları public repoda veya bu raporda yoktur.
- **Önceki dış kaynak arızası:** [Owner-Only #40289987173](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40289987173) Overpass `unavailable` ile FAIL olmuş ve Telegram'a genel hata bildirimi kabul edilmiştir. Artık Overpass başarısız olursa düşük hacimli resmi OSM 0.6 JSON okuma API yedeği kullanılabilir.
- **Yedek kaynak kapsamı:** mevcut public görülen OSM ID'leri ve en fazla iki adet 0.005 × 0.005 derecelik döşeme; Kadıköy kutusunun **tam** taraması değildir. © OpenStreetMap contributors / ODbL, https://www.openstreetmap.org/copyright .
- **Gerçek buton kabul boşluğu:** Sahibin Telegram'da ✅ Evet / ❌ Hayır / ⏳ Beklet eyleminin özel Neon veritabanına canlı yazılması hâlâ **UNVERIFIED**. Bunun bağımsız kod + Neon transaction rollback testi [#40281670003](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40281670003) PASS.
- **Günlük cron:** 10:23 ve 11:53 TRT konfigüre edildi. 26 Ekim gerçek `schedule` olayları #40290452442 ve #40299449157 FAIL (Overpass kaynakları); yeni yedek API kodu henüz `schedule` kaynaklı bir run ile doğrulanmadı. `push` kaynaklı owner-only kabul, schedule kanıtı değildir.
- **Gmail:** owner-to-self testi ve gerçek Gmail bağlantısı en son yapılacak. İşletmelere e-posta veya DM **gönderilmedi**.

## Önceki raporlar (tarihsel)

# 26 Ekim 2026 — Canlı tarama kusuru ve düzeltme kabulü

**KARAR: PARTIAL.** Kod PASS; Neon test PASS; gerçek OSM keşfi şu anda FAIL (dış kaynaklar erişilemiyor); gerçek işletme buton tıklaması UNVERIFIED; Gmail kullanıcı isteğiyle EN SON.

- Doğrulanan kod SHA: `661f0672da3a27b4ce407b118914555a2ba7348d`.
- **105/105 test PASS:** [main CI #40289987122](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40289987122).
- **Gerçek canlı tarama FAIL:** [Owner-Only Acceptance #40289987173](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40289987173). Log `RuntimeError: Overpass instances unavailable; no leads sent`. `Owner scan failure alert: Telegram delivery accepted` kanıtı var. Gerçek işletme bildirimi 0; hiçbir müşteri iletişimi/e-posta gönderilmedi.
- **Kök neden:** [OSM endpoint compare #40288959691](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40288959691) iki küresel sunucudan TimeoutError, İsviçreye özel aynadan boş sonuç, dördüncü sunucudan HTTPError verdi. [Ek küresel aynalar #40289332351](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40289332351) HTTP/bağlantı/zaman aşımı hataları verdi. Eski kod bölgesel İsviçre aynasının 0 kaydını yanlışlıkla başarı sayıyordu.
- **Düzeltme:** İsviçre bölgesel aynası kaldırıldı, yalnız global kaynakları dener. HTTP 401/403/429 sorunları tüm kaynakları denemeyi engellemez. Geçmiş OSM kimliklerinin olduğu pilot kutu beklenmedik biçimde boş dönerse **FAIL** olur. Kaynak hatası sahibin Telegram sohbetine güvenli hata bildirimiyle raporlanır.
- **Zamanlama:** 10:23 TRT hafta içi birincil kaldı; 11:53 TRT ek kurtarma slotu konfigüre edildi. Aynı gün fırsat teslim edildiğinde yalnız tarih içeren `data/last_digest_day.json` tekrar teslimi engeller. Bu yeni yedek cronun gerçek tetiklenmesi **UNVERIFIED**; ücretsiz GitHub cron/dış OSM hizmetleri %100 SLA sağlamaz.
- **Neon:** Önceki [gerçek transactional kabul #40281670003](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40281670003) Evet/Hayır/Beklet, öncelik ve rollback için PASS. Son kontrol `owner_leads` satırları 0; gerçek işletme kararı henüz kaydedilmedi.
- **Gmail:** Devre dışı; yalnız owner-to-self test kodu hazırlanmış, aktif alıcıya gönderim yapılmadı.

## Tarihsel raporlar

# 26 Ekim 2026 — Güncel teknik kabul

**Ürün kararı: PARTIAL** (Gmail bilinçli olarak son aşamaya bırakıldı ve gerçek işletme Telegram tıklaması henüz gözlenmedi). **Kod + CI + Neon işlemsel Evet/Hayır/Beklet testi: PASS.**

- **Doğrulanan kod commit:** `06132c0e94d883997f566ade5fd21db8cbafa30d` (PR #8 ve PR #9 merge).
- **95/95 çevrimdışı kabul testi:** [Offline Tests #40282042045](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40282042045) — SUCCESS, `main` dalı.
- **Gerçek özel Neon işlemsel doğrulaması:** [Telegram Three-Button Inbox #40281670003](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40281670003) — SUCCESS; log: `PASS: Private Neon YES/NO/LATER + deferred priority; temporary records rolled back; no emails or Telegram sent`. Geçici üç test satırı bilinçli rollback ile kaldırıldı, tablodaki kayıt sayısı son kontrolde **0**.
- **GitHub Secrets:** `REVIEW_DATABASE_URL` runtime'da bulundu ve gerçek Neon SSL bağlantısı kullanılarak işlemler başarıyla yürütüldü. Gizli bağlantı adresi kaydedilmedi veya raporlanmadı.
- **Telegram kararları:** ✅ Evet → `email_pending` (email göndermez); ❌ Hayır → `rejected`; ⏳ Beklet → `deferred` ve sonraki taramada ilk sırada. Gecikmiş/yanlış mesaj ID'si reddediliyor. Eski `data/seen.json` içindeki işletmeler karar tablosunda yoksa yeni butonlarla en fazla bir defa yeniden incelemeye alınabilir; öncelik bekletilen → yeni → geçmiş.
- **Gerçek işletme Telegram bildirimi:** GÜNCEL SÜRÜMDE HENÜZ GÖZLENMEDİ. 26 Ekim saat 10:23 TRT zamanlanmış `Telegram Lead Digest` sonucuna ve en az bir gerçek buton etkileşimine bakılarak ayrı doğrulanmalıdır. 15 dakikalık callback job'ının success olması gerçek fırsat mesajı kanıtı değildir.
- **E-posta:** Gmail bağlantısı ve gerçek owner-to-self SMTP testi bilinçli olarak bekletiliyor; işletmelere hiçbir e-posta / soğuk iletişim gönderilmedi.
- **Kurallar:** Public GitHub'da yalnızca herkese açık OSM kimlikleri tutulabilir; özel kararlar ve işletme kayıtları Neon'da kalır. Özel Secret, CRM veya mesaj geçmişi repoya yazılmamalı. Günlük cron ve sınırlı sahibi Telegram mesajları korunuyor.

## Önceki raporlar (tarihsel)

# 25 Ekim 2026 — Üç butonlu gerçek işletme karar sistemi

**Güncel ürün kararı: PARTIAL.** Kod/CI PASS; Neon veritabanı oluşturma ve boş şema kontrolü PASS; gerçek işletme callback'lerinin Neon üzerinde canlı uçtan uca çalışması **UNVERIFIED** (GitHub Secret henüz yapılandırılmadı); Gmail müşteri gönderimi **KAPALI**. Bu bölüm eski 24 Ekim canlı tarama kanıtını geçersiz kılmaz.

- **main SHA:** `a818ff2f4750495a9b1856fd9de9c97a976b53ef`.
- **Offline acceptance:** 87/87 PASS, [CI #40223759121](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40223759121), completed success.
- **Telegram callback inbox:** [#40223759123](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40223759123), completed success; no live decisions processed in this run.
- **Neon:** private separate project `misty-field-02930645`, `owner_leads` table created; non-sensitive SELECT count returned 0 total/deferred/rejected. Credentials not logged or stored in public source.
- **New UX:** concise 🟣 website / 🔵 automation alerts; ✅ Evet sets `email_pending` without sending mail, ❌ Hayır sets `rejected`, ⏳ Beklet sets `deferred` and causes it to be prioritized in the next scan, including repeated holds.
- **Activation gate:** GitHub Actions repo secret `REVIEW_DATABASE_URL` is **NOT VERIFIED CONFIGURED**, since connected GitHub API cannot manage secret values. Without the secret, existing owner-only short Telegram alerts continue but actual lead-specific decision buttons are not enabled.
- **Runtime:** no extra live customer scan was triggered by changes; weekday 10:23 TRT schedule retained. No marketing emails or messages to businesses have been sent.
- **Gmail:** code prepared previously, but actual Gmail account credentials and owner-to-self SMTP test are pending; leave email as the final integration stage.

## Prior 24 Ekim 2026 verification report (historical)

**Güncelleme:** 24 Ekim 2026, Türkiye saati  
**Proje:** https://github.com/emirhankaya985-cloud/musteri-avcisi-ai  
**Uygulayıcı kararı:** **PARTIAL** — offline test ve gerçek canlı Telegram keşfi **PASS**; gerçek GitHub `schedule` tetiklemesi **UNVERIFIED**.

> Bu rapor GitHub Actions üzerinde gerçekleşen işlerin kanıtlarını gösterir. Kullanıcı proje sahibi, ChatGPT kodu uygulayan çalışan, Codex bağımsız teknik yönetici ve son kabul denetçisidir. `push` kaynaklı canlı çalışma, `schedule` kanıtı değildir.

## Doğrulanmış commitler

- **Canlı iş akışı kaynak commit:** `dc2b85f94cecab12f8f6e1214e34e93c482786b1`. Bu sürüm yeni Overpass failover düzeltmesini ve yalnızca Secret varlığını kontrol eden workflow adımını içerir.
- **Canlı iş sonrası state commit:** `f350253fec93dab28044fccdfbeb8516545ddb2b` (`data/seen.json` güncellendi). Raporun kaydedilmesi bundan sonra ayrı dokümantasyon commiti oluşturur.
- Önceki yönetici kabulüne esas `7d8f8f457d903fdf5962cf4811c420c5943ed17a` 46/46 PASS idi.

## Nihai kanıt tablosu

| Kontrol | Durum | Doğrudan kanıt |
| --- | --- | --- |
| Offline kabul testleri | **PASS** | [#40071332679](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40071332679), 46/46 başarılı, güncel canlı workflow kaynak commitinde |
| 🔴 premium web sitesi / 🟢 otomasyon sınıflandırması | **PASS (offline)** | 46/46 offline kabul, canlı workflow demo adımı başarılı |
| Overpass boş yanıt/failover düzeltmesi | **PASS (canlı keşif)** | [Telegram Lead Digest #40071332670](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/40071332670), `event=push`, `success` |
| Ham OSM kayıtları | **65** | Aynı canlı workflow logları |
| Geçerli kayıt / elenen / tekrar | **52 / 13 / 0** | Aynı canlı workflow logları |
| Önceden görülen / yeni aday | **15 / 37** | Aynı canlı workflow logları |
| Sahibin Telegram sohbetine yeni gönderim | **5** | `Gönderilen yeni fırsat: 5`; canlı iş başarılı ve pozitif `message_id` zorunlu |
| Tekrar önleme state güncellemesi | **PASS** | `data/seen.json` yalnızca OSM kimlikleriyle 15'ten 20'ye yükseldi; commit `f350253f...` |
| Telegram repository secrets çalışma ortamında var | **PASS (runtime presence)** | Canlı workflow içindeki `Verify owner Telegram secrets are configured (presence only)` adımı başarılı; değerler yazdırılmadı |
| Secret metadata yetkili GitHub API ile listelendi | **NOT VERIFIED** | Mevcut GitHub bağlantısı secrets metadata endpointini sunmuyor; runtime kontrolü buna eşdeğer değildir |
| Gerçek pazartesi-cuma saat 10:23 `event=schedule` | **UNVERIFIED** | `23 7 * * 1-5` yapılandırılmış; 24 Ekim 2026 Cumartesi itibarıyla schedule tetiklenmesi yok |
| Public depo gizliliği | **PASS (görülebilen tracked dosyalar ve offline testler)** | CI ve yalnızca kamuya açık `seen_ids` listesi |
| İşletmelere otomatik pazarlama iletisi | **YOK** | Canlı işlem yalnızca sahibin Telegram sohbetine iletir; işletme erişimi yalnızca manuel |

## Açık üretim kapısı: schedule

- Bir sonraki uygun tarih: **26 Ekim 2026 Pazartesi**, hedef **10:23 Europe/Istanbul (07:23 UTC)**. GitHub'ın gecikmesi veya atlaması mümkündür.
- Gerçek `event=schedule` çalışmasında run ID, tetiklenme saati, kullanılan HEAD commit, sonuç, OSM sayaçları ve gönderilen yeni fırsat sayısı ayrıca doğrulanmalıdır.
- Kullanıcı için 26 Ekim saat 11:00 civarında (esnek teslim) **tek seferlik otomatik kontrol** oluşturuldu. Kontrol `schedule` yoksa `UNVERIFIED` raporlayacak; başka bir canlı iş tetiklemeyecek.
- `workflow_dispatch` veya `push` tetiklemeleri, zamanlama kanıtı olarak gösterilmemelidir.

## Güvenlik ve sınırlar

- Secret değerleri okunmadı, loglanmadı veya repository'ye yazılmadı. Kullanılan isimler `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` ve isteğe bağlı `SCAN_BBOX` repository variable'ıdır.
- `data/seen.json` yalnızca kamuya açık OSM node/way/relation kimlikleri içerir.
- Tarama, OSM kaydında web sitesi olmadığı için işletmenin kesinlikle sitesi olmadığını iddia etmez; otomasyon ihtiyacını da kanıtlanmış saymaz.
- İşletmelere otomatik e-posta, mesaj, DM veya SMS gönderilmez.
- Windows üzerindeki yerel Git push kimlik doğrulaması bu teslim kapsamında değiştirilmedi; public depoya bağlı 985 hesabının GitHub üzerinden push yetkisi doğrulandı.

**Codex için kısa sonuç:** 46/46 offline PASS, güncel düzeltmenin ilk canlı OSM denemesi PASS, 65 ham OSM kaydı ve 5 sahibine Telegram bildirimi, tekrar state'i 20 OSM ID, secrets runtime varlığı PASS; yalnızca gerçek `schedule` kanıtı ve doğrudan secret metadata okuması bekleniyor. Son kabul kararı Codex'e aittir.
