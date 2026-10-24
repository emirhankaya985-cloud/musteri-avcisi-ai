# Müşteri Avcısı AI — Üretim Doğrulama ve Teslim Raporu

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
