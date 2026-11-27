# Özel İYS uygunluk kaydı içe aktarma

Bu komut İYS'ye bağlanmaz ve İYS kararı üretmez. Yetkili işletme/İYS
kontrolünü tamamladıktan sonra yalnızca doğrulanmış sonucu özel Neon CRM'e
eşlemek içindir. SMTP çağrısı yapmaz.

## Girdi

Özel makinede, depoya eklenmeyen UTF-8 JSON dosyası kullan:

```json
{
  "schema": "iys-business-evidence-v1",
  "records": [
    {
      "email": "resmi-sitede-yayimlanan@isletme.example",
      "merchant_evidence_ref": "private-official-registry-reference",
      "iys_evidence_ref": "private-iys-query-reference",
      "checked_at": "2026-11-27T12:00:00+03:00",
      "merchant_verified": true,
      "iys_registered": true,
      "iys_rejected": false
    }
  ]
}
```

Kaynak referansları gizli belgeleri veya kimlik numaralarını değil, sahibin
özel kayıtlarında kanıta ulaşmasını sağlayan kısa referansları içermelidir.
Komut dosya içeriğini ekrana yazmaz. Adres, CRM'deki e-posta alanıyla tam
eşleşmelidir. 24 saatten eski, saat dilimsiz, mükerrer, belirsiz biçimde birden
fazla CRM kaydına eşleşen, reddedilmiş, kayıtlı olmayan veya tacirliği
doğrulanmamış adresler gönderilebilir yapılmaz. Önceden kaydedilmiş ret/hold
üstündür. Import yalnızca uygunluk JSON'unu günceller; gönderim geçmişini
değiştirmez.

## Çalıştırma

`REVIEW_DATABASE_URL` yalnızca SSL zorunlu özel Neon URL'si olarak ortamdan
verilir. Dosyayı public repo, Actions artifact veya issue'a koyma.

```powershell
$env:REVIEW_DATABASE_URL = '<private SSL Neon URL>'
python -m leadhunter.import_iys_evidence .\private-iys-evidence.json
```

Çıktı yalnızca toplu sayımlardır. Ardından `execute-outreach.yml` mevcut
uygunluk, tekrar gönderim, kota ve gönderici koruması kapılarını yeniden
denetler. Gönderici durdurma devresi ayrıca çözülmeden import tek başına SMTP'yi
açmaz. CRM'ye import edilen izler özel müşteri verisidir; paylaşma.

## Yerel doğrulama

```powershell
python -m unittest tests.test_import_iys_evidence tests.test_recipient_eligibility -v
```
