# Neon — izole yedek/geri yükleme kabul prosedürü

- **Kaynak:** mevcut Neon `REVIEW_DATABASE_URL`; yalnızca `pg_dump` (salt-okunur) ve satır imzası hesaplaması.
- **Hedef:** GitHub Actions içinde geçici PostgreSQL 16 test servisi; canlı Neon projesine hiçbir `DROP`, `INSERT`, `UPDATE` veya `pg_restore` komutu gönderilmez.
- **Arşiv:** `mktemp` içine `pg_dump -Fc --schema=public`; loga basılmaz, artifact/upload yapılmaz, job sonunda silinir.
- **Karşılaştırma:** şema içindeki bütün normal public tablolar aynı mı ve satır sayısı + tüm satırların sıra-bağımsız SHA-256 imzaları eşleşiyor mu? İmzalar/özel adresler loglanmaz.
- **Risk:** İzleme sırasında kaynak değişirse eşleşme başarısız olabilir. Bir başarısız deneme veriyi bozmaz; ayrı güvenli tekrarla doğrulanmalıdır.
- **Gerçek yedek politikası:** Geçici test arşivi **kalıcı yedek değildir**. Neon'un hesap planında sunulan geri yükleme/PITR kabiliyetinin ve saklama süresinin ayrıca doğrulanması gerekir. Yeni ücretli depolama otomatik açılmaz.
- **Hukuki/iletişim:** Test SMTP/Telegram işletme gönderimi ve Google yanıtı içermez.
