# Müşteri Avcısı AI — Görev 6.2 checkpoint

## Görev 6.3 devam notu — 2026-11-26

- Kullanıcı talimatı: **kendisine test e-postası gönderilmesini tekrar etme**. Yukarıdaki 45802729311 self-test'i yalnız tarihsel kayıt olarak tut; bu checkpoint'ten sonraki çalışmalarda self-test veya işletme e-postası gönderilmedi.
- PR #101 sonrası entegrasyon dalı `codex/task-63-automation-integration` açıldı. Eklenen `mail_recovery` denetimi Gmail başarısızlık sınıflarını toplu ve adres göstermeden raporlar; SMTP'ye bağlanmaz, yeniden denemez ve gönderici kilidini açmaz.
- CRM satış aşamaları için 017 migrasyonu, kanıtlı ve idempotent geçiş kaydı ile DNC/ret koruması eklendi. `communication_eligible` pazarlama izni değildir. Normal CRM ve yeni PBF keşif kayıtları, migration mevcutsa yalnız gerçekten yeni CRM satırlarında `new_discovered` olarak başlatılır; eski 412 kayıt geriye dönük doldurulmaz. Günlük Telegram özeti ve XLSX, kalıcı aşama sayılarını ve geçmişi olmayan kayıt sayısını gösterecek şekilde bağlandı.
- PR [#102](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/102) squash-merge edildi (`30cede5`). GitHub CI run [45831506293](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45831506293) offline ve sentetik PostgreSQL kontrollerini geçirdi. Migration run [45831668999](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45831668999) 014–017'yi tek transaction'da uygulayıp doğruladı.
- Günlük owner Telegram + XLSX raporunun migration sonrası canlı koşumu [45831812020](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45831812020) başarılı; Telegram workbook mesajı 336, özet mesajı 337, Neon makbuzu onaylandı, `business_mail_sent=0`. Gmail salt-okunur sonrası denetim [45831626536](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45831626536): 412 CRM, 25 e-posta kaydı, 0 belgelenmiş izin, 15 geçmiş SMTP kabulü, 4 hata, 11 teslimi doğrulanmamış kabul, 0 yanıt; sender paused, sendable=0. Kurtarma özeti `unlock_authorized=0`, `smtp_attempts=0`.
- Yerel doğrulama: `python -m unittest discover -s tests -v` = 426 geçti, 27 atlandı; `python tools/codex_acceptance.py` başarılı; `git diff --check` temiz. Yerel PostgreSQL DSN olmadığı için DB testlerinin bir kısmı atlandı; sentetik PostgreSQL CI geçti.
- Üretimde hâlâ 81 il satırı pending; ulusal/ilçe PBF taraması yok; ntfy yok; geçmiş 412 CRM satırı lifecycle geçmişi olmadan kaldı ve uydurma geçmişle doldurulmadı. Email eligibility=0; sender lock paused. Bu görevde kendine test e-postası veya işletmelere e-posta gönderilmedi.

Güncelleme: 2026-11-25 (Europe/Istanbul)

## Görev 6.3 üretim durumu — 2026-11-26

- PR #98 ve #99 korunarak `main`e alınmıştı. Görev 6.3 sırasında 81 il kapsam satırını Neon'da başlatan insert-only workflow PR [#100](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/100) ile birleştirildi (`08088af`). Üretim run [45804423103](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45804423103): 81/81 il satırı doğrulandı; 81 pending, 0 plan, 0 tarama, 0 CRM yazımı. İlçe manifesti/taraması hâlâ yok.
- Güncel Neon salt-okunur denetimi [45802947224](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45802947224): toplam 412 kayıt, 25 e-posta kaydı, 25 denetlenmiş, 0 belgelenmiş iletişim uygunluğu; 15 geçmiş SMTP kabulü, 4 başarısızlık, 0 gecikmeli bildirim, 0 eşleşen yanıt, 11 kabulün teslim kanıtı eksik. Gönderici kilidi `paused=True`, `sendable=0`.
- Önceki dört başarısızlık sınıfı: DNS NXDOMAIN (1), posta kutusu yok (1), relay denied (1), iki gecikme bildirimi ardından connection refused (1). Sender kimlik doğrulama arızası kanıtlanmadı; geçmiş kayıtlar silinmedi veya bypass edilmedi.
- Sahibine tek test e-postası [45802729311](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45802729311) ile gönderildi; Gmail SMTP 1 iletiyi kabul etti. Gelen kutusuna teslim bağımsız doğrulanmadı. Gmail IMAP salt-okunur watcher [45802947224](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45802947224) başarılı; `business_mail_sent=0`.
- Planlı lead-digest [45759291065](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45759291065) 402/402 eski tile tamamlandığı için `new_public_queries=0` ile atlandı. 402 eski tile kanıtı korunuyor; ayrı sürümlü il/ilçe PBF checkpoint/processor henüz yok. Sonraki freshness kontrolü [45787176561](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45787176561) scan ve Gmail makbuzlarını stale bulmuştu; Gmail watcher sonradan manuel çalıştırıldı, scan cron tazeliği hâlâ düzeltilmedi.
- Son günlük Telegram owner rapor koşumu [45748407617](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45748407617) başarılı. Depoda ntfy entegrasyonu yok. Kalıcı satış aşamaları (teklif/toplantı/kazanıldı/kaybedildi) şeması da bulunmuyor.
- Bu görevde işletmelere e-posta gönderilmedi; ek maliyet oluşturulmadı. İşletmelere gönderim uygunluğu yalnızca CRM/ret/İYS kayıtları ve sender kilidi kanıtla temizlendikten sonra değerlendirilebilir.

## Kurtarılan çalışma ve Git durumu

- Kaynak `main`: `6e6b92c38f030a20ef19ed83977cdd16976feff2` (başlangıç doğrulaması).
- Entegrasyon dalı: `codex/task-v6-integration`; kurtarılan uzman dalları silinmedi.
- Entegrasyon commitleri: `ac1db9d` il defteri modeli; `eb9b4f4` kanıta dayalı puanlama; `76d4b99` sektör sözlüğü; `aa5c6dc` Neon il kapsam migrasyonu; `316b9f8` kapsam başlatma/okuma; `c0a6e8e` kapalı Gmail API taşıyıcısı; `2e05397` mükerrer güven skoru ve audit migrasyonu; `7beb09a` audit değişmezliği testleri; `73bd8d9` workbook snapshot/provenance; `f83ebc6` checkpoint/test fixture; `60b10d0` XLSX mükerrer serialization ve migration CI düzeltmeleri.
- PR [#98](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/98) `main`e squash merge edildi; merge commit `caf9f7b5e6832ed33d351c537f9114f017ce06bd`. Son PR CI [45622005875](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45622005875): offline ve sentetik PostgreSQL işleri başarılı.
- Kaynak ajan dalları/worktree'leri korunuyor; hiçbir worktree silinmedi. QA ajanı kullanım sınırına takıldı, bağımsız son QA tamamlanmadı.
- Main'deki elle tetiklenebilir workflow [45622171552](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45622171552) 014/015/016'yı tek transaction içinde uyguladı; checksum'lar kaydedildi ve şema doğrulaması geçti.

## Tamamlanan ve test edilen

- 81 il için devam ettirilebilir durum modeli (`pending/running/completed/partial/failed`), ilk on şehir listesi ve pilot dışlama mantığı eklendi. Bu bir tarama makbuz defteridir; il sınırı verisi veya faal 81 il tarayıcısı değildir.
- Sektör sözlüğü, kaynak gerektiren ticari puanlama, Gmail API OAuth taşıyıcısı (kapalı; mock testli), mükerrer aday güven skoru/audit migrasyonu ve günlük workbook provenance kodu entegre edildi.
- Workbook üreticisi 12 sekmeyi hedefliyor; aynı tutarlı CRM satırları sayılıyor/hash'leniyor ve dış metinler XLSX string hücresi olarak kaydediliyor. Bu commit sonrası yerel regresyon: `python -m pytest tests -q` = 382 geçti, 23 atlandı. `python tools/codex_acceptance.py` = 405 geçti, 23 atlandı. PostgreSQL DSN yok; DB entegrasyon testleri çalışmadı.
- CI PostgreSQL testinde bulunan yeni hatalar düzeltildi: duplicate query mock şeması `confidence_score`/`confidence_details` kolonlarıyla eşitlendi; XLSX text[] ve tz-aware timestamps normalize edildi; XML geçersiz karakter testi eklendi; 015 tekrarlı uygulanma testini CI workflow'a eklendi.
- Son yerel suite: `python -m pytest tests -q` = 385 geçti, 24 atlandı. Son kabul: 408 geçti, 24 atlandı. PostgreSQL testleri yalnız GitHub Actions'taki sentetik DB ile gerçek çalıştırılabilir.
- Önceki doğal günlük Telegram raporu: Actions run `45543301939`; belge mesajı `325`, özet mesajı `326`; Neon makbuzu doğrulanmıştı. Bu, yeni dalın workbook'u değildir.

## Üretim kanıtı ve sınırlar

- Önceki salt-okunur üretim gözleminde 412 kayıt, 25 e-posta, 387 e-posta eksik, 18 mükerrer inceleme adayı, 0 doğrulanmış yasal gönderim uygunluğu, 15 geçmiş SMTP kabulü, 4 teslimat hatası ve 0 eşleşmiş yanıt görülmüştü. Tarihsel 412 sayısı bu yeni denemeden sonra doğrudan yeniden sorgulanmadı.
- 2026-11-25'te main SHA `6e6b92c` üzerinden elle tetiklenen pilot run [45620335913](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45620335913) başarıyla tamamlandı. Resmî Geofabrik PBF checksum'u doğrulandı; işlenen pilot kaynak kesitinde 397 aday nesne görüldü, 0 yeni CRM kaydı eklendi, 3 mevcut OSM farkı inceleme kuyruğuna yazıldı; tarihsel 402 tile değişmedi; 25 mükerrer çift saptandı, 0 yeni özel inceleme çifti açıldı ve 0 otomatik birleştirme yapıldı. Müşteriye e-posta gönderilmedi. Bu, 81 il taraması değildir.
- 81 il ve 10 şehir üretimde taranmış değildir. İl kapsam defteri yalnızca veri modelidir; sınır manifesti ve il/ilçe bazlı PBF tarayıcı/iş akışı hazır değil.
- Google OAuth kullanıcı onayı/refresh token ve GitHub secret yapılandırması yok. İş e-postası gönderilmedi; pazarlama kapısı kapalı kaldı.
- Neon üretimine 014/015/016 migrasyonları uygulandı ve workflow şemayı doğruladı. Telegram'a yeni rapor gönderilmedi.
- Bağlı Neon hesabında yeni/erişilebilir proje listesi boş döndü; repo `REVIEW_DATABASE_URL` secret'ına bağlı production projesi Neon MCP tarafından bulunamadı. Secret değeri okunmadı. Ancak başarılı pilot GitHub Action'ı repo secret'ı üzerinden veritabanına bağlandı; migrasyon workflow'u bu kanalı kullanacak.
- Tahmini ek maliyet: 0 TL; ücretli servis eklenmedi.

## Kesin sonraki adımlar

1. Lisanslı ve kaynaklı il/ilçe sınır manifesti, streaming PBF partitioner, ilçe checkpoint ve CRM upsert idempotency/duplicate guard CI kanıtları olmadan ulusal tarama başlatma.
2. Gmail yalnızca OAuth consent ve hesap içi GitHub secret yapılandırması tamamlanınca; önce yalnız kullanıcının kendi adresine doğrulanmış self-test yap. İşletme alıcılarına gönderim kapalı kalsın.
3. Yeni workbook/Telegram raporu ve doğal cron makbuzu oluşana kadar geçmiş Run `45543301939` kanıtını yeni sürüme aitmiş gibi sunma.

## Görev 6.3 — Dış işletme iletişim akışı ve araştırma — 2026-11-26

- Dış işletmelere yönelik zamanlanmış iletişim akışı eklendi: önce resmî web sitesi üzerinden günlük en fazla 10 eski CRM kaydı için kaynaklı e-posta araştırması; ardından ayrı akışta en fazla 5 uygun işletme/gün. Araştırma SMTP kullanmaz; adres keşfi hukuki ileti izni sayılmaz.
- Kendine gönderim koruması hem otomatik alıcı claim noktasında hem SMTP öncesi son kapıda hem de sahip onaylı claim yolunda eklendi. Bu görevde self-test veya işletme e-postası gönderilmedi.
- Yalnız güncel ve kaynaklı işletme sinyali varsa hizmet ihtiyacı iddia edilir; aksi durumda taslak keşif sorusu sorar. SMTP kabulü yanıt/teslimat olarak sayılmaz. Yanıt/ret yalnız eşleşen ve yeni lifecycle olaylarını ilerletir; geçmiş 412 işletmeye uydurma aşama atanmaz.
- 2026.11.0 OSM türevi, açıkça resmî olmayan manifest üretildi: 81 il, 973 ilçe; sabitlenmiş kaynak commit ve özet hash doğrulandı. Bu yalnız sınır envanteridir; ilçe geometrisiyle streaming PBF tarayıcı, kalıcı ilçe checkpoint'i ve ulusal tarama hâlâ yok. Eski 402 tile ulusal kapsama kanıtı değildir.
- Ntfy için yalnız opsiyonel, toplulaştırılmış bildirim taşıyıcısı eklendi; ntfy topic/secret yok, gerçek teslimat doğrulanmadı. Telegram günlük raporu PR #102 sonrası canlı teslim edilmişti.
- Bu dalın yerel suite'i: `python -m unittest discover -s tests -v` = 460 geçti, 28 atlandı; `git diff --check` temiz. Üretimdeki son denetimde 0 belgelenmiş alıcı uygunluğu ve gönderici devre kesicisi paused olduğu için gerçek işletme gönderimi şu an 0; kilit açılmadı. Alıcı ön denetimi ve yasal kanıtlar temizlenmeden sistemin gönderdiği söylenemez.

## Görev 6.3 devam kanıtı — 2026-11-26 akşamı

- PR [#104](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/104) ile günlük 10 adreslik SMTP'siz araştırma korunup manuel 10/25/50 işletme partisi eklendi. PR [#105](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/105) ile kaynaklı bulunan adreslerin taslak durumunu yeniden ele alma ve toplu MX engeli raporu eklendi; her iki PR'ın test ve sentetik PostgreSQL CI kontrolleri geçti.
- İlk 10'luk canlı araştırma [45856282377](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45856282377): 10 site, 0 adres, 0 SMTP.
- 50'lik canlı araştırma [45857249195](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45857249195): 20 farklı host araştırıldı; 2 kamuya açık adres bulundu, 18 adres bulunamadı, 11 kayıt host tekilleştirmesi/soğutmasıyla atlandı. SMTP=0. İkinci aynı gün çalışması [45857559419] host soğutması nedeniyle yeni site ziyaret etmedi.
- Mevcut adresleri SMTP'siz yeniden ele alan koşum [45858072245]: araştırılmış iki adresin ikisinde de `no_mx`; dolayısıyla 0 taslak, 2 MX engeli; SMTP=0. Kamuya açık adres, çalışır posta kutusu veya ileti izni anlamına gelmiyor.
- Son suite: 461 geçti, 28 yerel DB testi atlandı; PR CI sentetik PostgreSQL testleri geçti. Gerçek işletme e-postası veya kendine test e-postası gönderilmedi.
- Kalan büyük işler değişmedi: ilçe geometrisiyle streaming PBF tarayıcı ve ulusal tarama yok; 81/81 il defteri pending. Ntfy topic/token GitHub secret'ları yok, bu nedenle ntfy gerçek teslimat yapmıyor. İşletme e-postası sender circuit paused ve yasal alıcı uygunluğu sıfır olduğu için kapalı.

## Otomatik işletme e-postası devamı — 2026-11-27

- PR [#107](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/107): outreach CI bağımlılıkları; PR [#108](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/108): mevcut Gmail SMTP secret aktarımı; PR [#109](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/109): PII sızdırmayan aşama tanısı; PR [#110](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/110): 200 kayıtlık backlog sayfalama. Tüm PR'lar CI ile birleştirildi.
- Günlük outreach run [46014890146](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/46014890146) başarılı: CRM 412; contact 27; legal eligibility 0; sender paused; sendable 0; actual SMTP 0. İş akışı kuyruğun ilk 200 kaydını `backlog_truncated=1` ile işledi; mail özeti `accepted=15, skipped=22` (accepted sayısı geçmiş kayıtların toplamıdır).
- PR [#111](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/111) ile e-posta göndermeyen SMTP AUTH denetimi eklendi. CI geçti. Canlı denetim [46016040964](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/46016040964): `authenticated=1; message_sent=0`. Gmail kimlik doğrulaması çalışıyor; bu sonuç geçmiş teslimat hatalarını veya itibar kilidini temizlemez.
- Salt-okunur Gmail denetimi [45942713471](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45942713471): yeni teslimat/yanıt yok; 15 geçmiş kabul, 4 hata, 11 kabulde teslim kanıtı yok, 0 yasal uygun aday, `unlock_authorized=0`.
- Güncel tam test: 463 geçti, 28 yerel DB testi atlandı; SMTP AUTH testleri +2 geçti. Kendine test veya işletme e-postası gönderilmedi.

## Ulusal PBF tarama ve performans — 2026-11-28

- PR [#118](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/118) ile ilçe PBF geometrisi ve makbuz kontrollü tarayıcı `main`e alındı; PR [#121](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/121) geçersiz OSM way güvenli geri dönüşünü, uzun PBF ayrıştırması sırasında Neon kilidinin bırakılmasını ve daha eski snapshot'ın yeni makbuzu ezmesini önleyen kontrolü ekledi.
- Canlı run [#46088692204](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/46088692204): Neon ön kontrolünde 81 il/973 ilçe planı geçerliydi (`receipt_confirmed=0`); Geofabrik MD5 ve PBF header doğrulandı. Ulusal aday eşleme adımı 3 saatlik job timeout'unda iptal oldu. Adaylar tamamen eşlenmeden Neon yazımı başlamadığı için bu run yeni ilçe makbuzu veya CRM kaydı yazmadı.
- PR [#122](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/122) taslak durumunda: Pyosmium C++ `KeyFilter`/`TagFilter`, bütün node koordinatları konum cache'ine girdikten sonra uygulanıyor. Mevcut izinli OSM tag seti, STRtree ve kesin `covers` ataması korunuyor. CI run [#46146208110](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/46146208110) `test` ve sentetik `postgres-dedup` kontrollerini geçti.
- Tekrar çalıştırılabilir `python tools/benchmark_national_scan_filter.py` yalnızca geçici sentetik PBF kullanır; ağ/DB erişimi yapmaz. 100.250 nesneli ölçümde (100.000 ilgisiz adlandırılmış nesne, 250 işletme) Python tarafı 4,086 sn'den 0,079 sn'ye indi (51,42×) ve aynı 250 OSM ID'si bulundu. Bu mikrobenchmark tüm ülke PBF runtime'ını ölçmez; ulusal canlı tarama tamamlanmış değildir ve Neon makbuzları 0'dır.
- Yerel, henüz PR #122'ye aktarılmamış tanı iyileştirmesi: tarayıcı snapshot doğrulama, ilçe geometrisi çıkarma, STRtree kurma ve işletme eşleme evrelerinin başlangıç/bitiş/hata süresini; eşleme bittiğinde aday sayılarını yazıyor. Her il işleminde geçen süre de loglanıyor. Böylece sonraki izinli çalıştırmada timeout evresi ayrıştırılabilir. Tam ülke performansını kanıtlamaz ve ulusal taramayı başlatmaz. Odaklı tarama testleri 17/17; tam çevrimdışı test paketi 523 geçti, 28 yerel DB testi atlandı.

