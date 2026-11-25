# Müşteri Avcısı AI — Görev 6.2 checkpoint

Güncelleme: 2026-11-25 (Europe/Istanbul)

## Kurtarılan çalışma ve Git durumu

- Kaynak `main`: `6e6b92c38f030a20ef19ed83977cdd16976feff2` (başlangıç doğrulaması).
- Entegrasyon dalı: `codex/task-v6-integration`; kurtarılan uzman dalları silinmedi.
- Entegrasyon commitleri: `ac1db9d` il defteri modeli; `eb9b4f4` kanıta dayalı puanlama; `76d4b99` sektör sözlüğü; `aa5c6dc` Neon il kapsam migrasyonu; `316b9f8` kapsam başlatma/okuma; `c0a6e8e` kapalı Gmail API taşıyıcısı; `2e05397` mükerrer güven skoru ve audit migrasyonu; `7beb09a` audit değişmezliği testleri; `73bd8d9` workbook snapshot/provenance; `f83ebc6` checkpoint/test fixture; `60b10d0` XLSX mükerrer serialization ve migration CI düzeltmeleri.
- Açık taslak PR: [#98](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/pull/98), hedef `main`; son doğrulanan baş `0255782`. [CI 45619756040](https://github.com/emirhankaya985-cloud/musteri-avcisi-ai/actions/runs/45619756040) iki işte de başarılı (offline ve sentetik PostgreSQL). Yeni migration workflow'u henüz CI'a girmedi.
- Kaynak ajan dalları/worktree'leri korunuyor; hiçbir worktree silinmedi. QA ajanı kullanım sınırına takıldı, bağımsız son QA tamamlanmadı.
- PR sonrası yalnız 014/015/016 statik migrasyonlarını uygulayıp doğrulayan manuel GitHub Actions workflow'u eklendi; henüz çalıştırılmadı.

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
- Neon üretimine 014/015/016 migrasyonları uygulanmadı. Telegram'a yeni rapor gönderilmedi.
- Bağlı Neon hesabında yeni/erişilebilir proje listesi boş döndü; repo `REVIEW_DATABASE_URL` secret'ına bağlı production projesi Neon MCP tarafından bulunamadı. Secret değeri okunmadı. Ancak başarılı pilot GitHub Action'ı repo secret'ı üzerinden veritabanına bağlandı; migrasyon workflow'u bu kanalı kullanacak.
- Tahmini ek maliyet: 0 TL; ücretli servis eklenmedi.

## Kesin sonraki adımlar

1. PR #98'in son CI'ını, yeni migration workflow'u dahil, bekle ve kaydet.
2. CI geçerse PR #98'i `main`e birleştir; ardından `Apply Additive Owner CRM Migrations` workflow'unu yalnız `main`den elle tetikle ve schema doğrulama logunu kaydet.
3. 81 il taraması için lisanslı/teyitli il-ilçe sınır kaynak manifesti, streaming PBF işlemcisi, güvenli upsert ve checkpoint/CI kanıtı tamamlanmadan ulusal üretim taraması başlatma.
4. Kullanıcıdan gizli bilgi isteme; Google resmi OAuth consent adımı ve secret'ları kullanıcı hesabında ayarlaması gereken aşamada tek bir işlem listesi sun.
5. Doğal günlük rapor kanıtını yeni koddan ayrı tut; yeni cron koşumu oluşana kadar eski run'ı yeni sürüm kanıtı diye sunma.
