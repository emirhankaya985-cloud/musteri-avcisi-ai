# 985 AI Control Center — Müşteri Avcısı v1 veri sözleşmesi

**Durum:** Kaynak Neon'da hazırlanacak güvenli, tek-satırlı toplulaştırılmış veri modeli. Merkezi panelin ayrı deposu ve Render servisi canlı olarak doğrulanmadan *panel bağlı* denmez. Diğer ajanların kodlarını veya veri kaynaklarını yeniden oluşturma.

## Sahiplik
- Kaynak: private Neon `musteri-avcisi-ai-review`; mevcut `owner_leads`, `owner_scan_run_metrics`, `owner_mail_watch_runs` ve yeni `owner_osm_tile_ledger`.
- Taranan 402 harita parçasının devam etme kaynağı: public `data/osm_tile_progress.json`; Neon tablo yalnızca kalıcı panel okuma modeli. İlerleme önce kaynak cursor'da başarıyla commit edilir.
- Consumer: 985 AI Control Center, **ayrı repo ve ayrı yönetim**, veri aktarımı yalnızca aggregate/read-only. Panel açık olsun/olmasın GitHub cron devam eder.
- Kaynak DB'nin owner/admin connection string'ini istemciye veya ön yüze verme. Ayrı salt-okunur rol ve sunucu-yanı secret kullan.
- `migrations/004_owner_osm_tile_ledger.sql` kaynak DB'ye uygulanır. Rol yetkisi açıkça oluşturulmadan panel bağlantısı kurulmaz.

## Kaynak read-only rolü
Kaynak sahibi ayrı bir `control_center_musteri_reader` LOGIN rolü için **benzersiz parola** üretir; parolayı GitHub veya bu public repoya yazmaz. Bir kez özel yönetim kanalında:

```sql
REVOKE ALL ON public.control_center_musteri_v1 FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO control_center_musteri_reader;
GRANT SELECT ON public.control_center_musteri_v1 TO control_center_musteri_reader;
```

Bu rol için kaynak tablolara doğrudan SELECT, DML veya DDL yetkisi verilmez. Merkez yalnızca sunucu tarafı bağlantısından `SELECT * FROM public.control_center_musteri_v1` yapar. Satır düzeyinde müşteri, alıcı, e-posta gövdesi, token, Message-ID ve yasal izin belgeleri hiçbir zaman bu view'dan verilmez. Talep gelirse hassas geçmiş için ayrı yetkili kaynağa git; bu sözleşmeyi genişletme.

## Alanların doğru anlamı
- `leads_total`, `leads_in_review`, `new_today`, `by_sector`: gerçek private CRM aggregate.
- `smtp_acceptance_rows`: geçmiş kabul satırları; teslim edilmiş e-posta sayısı değildir.
- `observed_delivery_failures` ve `matched_replies`: yalnızca gözlemlenmiş DSN/IMAP sonucu; kalan kabuller *teslim kanıtı yok*.
- `last_recorded_scan_at`: Neon'a metrik commit zamanı; her harita parçasının başarıyla okunduğu anlamına gelmez.
- `confirmed_tiles`, `total_tiles`, `by_region`: public cursor'daki **başarıyla taranan** kesitlerin Neon kopyası. Başarısız HTTP 429/403 kaydı `blocked`, 5xx ve ağ hataları `retry`, hiç denetlenmemiş olanlar `pending`.
- `last_updated_at` ve `snapshot_at`: eşitleme/okuma zamanı. Kaynağın doğruladığı veriyle karıştırma.
- `next_scheduled_target_utc`: GitHub cron hedefi, kesin başlama garantisi yoktur.

## Devreye alma kabulü
1. Kaynak Neon 402 satırı doğrulanır, sekiz bölgenin toplamları kamu ledger'ı ile eşleşir.
2. Read-only rolün yalnızca view erişimi ve hiçbir tabloya yazma yetkisi olmadığı test edilir.
3. Görev 3'ün **mevcut** ayrı merkez kodu bulunup sahibi tarafından yetkilendirildikten sonra salt-okunur adaptör eklenir.
4. Render üzerinden gerçek kimlik doğrulama ve snapshot alanları doğrulanır. Kaynak SMTP/Telegram workflow'larına dokunulmaz.
5. Panel arızasında saatlik scan aksatılmamalıdır. Eksik değer gizlenmez: son doğrulanmış değer, gözlem zamanı ve kaynak hata durumu gösterilir.

Merkez depo/servis bulunmazsa **entegrasyon şeması hazır, panel bağlantısı engelli** olarak raporlanır.

## Gerçek özel Neon hazırlığı (14 Kasım 2026)
- `control_center_musteri_reader` rolü `NOLOGIN` olarak oluşturuldu; view için `SELECT` ve schema için `USAGE` izni verildi. `owner_leads` veya tile tablosunda SELECT/UPDATE yetkisi yok.
- Merkezi uygulama deposu ve sunucu dağıtımı doğrulanmadığından role hiçbir LOGIN hesap bağlanmadı ve parola üretilmedi. Bu, panelin şu anda entegre edildiği anlamına gelmez.
