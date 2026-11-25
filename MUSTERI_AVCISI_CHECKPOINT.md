# Müşteri Avcısı AI — Görev 6.2 checkpoint

Güncelleme: 2026-11-25 (Europe/Istanbul)

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
