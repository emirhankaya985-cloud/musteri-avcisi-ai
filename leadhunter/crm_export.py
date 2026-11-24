"""Private owner CRM workbook export and delivery through the owner's DM only."""
from __future__ import annotations

from datetime import date, datetime
from io import BytesIO
import json
import re
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Istanbul")
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FIELDS = (
    "osm_id", "status", "first_seen_at", "sent_at", "business_name", "city",
    "sector", "website", "phone", "email", "email_preflight", "email_source",
    "research_score", "whatsapp", "whatsapp_status", "auto_mail_state",
    "gmail_message_id", "delivery_state", "delivery_error", "reply_state",
    "last_verified_at",
)
HEADERS = (
    "İşletme adı", "Şehir", "Sektör", "E-posta", "Web sitesi",
    "WhatsApp durumu", "Müşteri kategorisi", "Mevcut araştırma segmenti",
    "Araştırma puanı (/100)", "Önerilen hizmet", "Gönderim tarihi",
    "Gmail message ID", "E-posta durumu", "Yanıt durumu", "Hata nedeni",
    "Sonraki işlem", "Kaynak bağlantısı", "Son doğrulama tarihi",
    "İşletme telefonu", "E-posta ön kontrolü (MX)", "OSM kimliği",
)


def fetch_rows(connection):
    """Fetch only CRM fields needed in the private workbook, never mail bodies."""
    query = """
        SELECT osm_id, status, first_seen_at, sent_at,
               lead_data->>'name', lead_data->>'city', lead_data->>'category',
               lead_data->>'website', lead_data->>'phone',
               COALESCE(NULLIF(lead_data->>'email',''),
                        NULLIF(lead_data->'_auto_mail'->>'recipient',''),
                        NULLIF(lead_data->'_mail'->>'recipient','')),
               COALESCE(NULLIF(lead_data->>'email_check',''),
                        NULLIF(lead_data->'_auto_mail'->>'email_check','')),
               COALESCE(NULLIF(lead_data->>'email_source',''),
                        NULLIF(lead_data->'_auto_mail'->>'recipient_source','')),
               lead_data->>'score',
               COALESCE(lead_data->>'whatsapp', lead_data->>'contact:whatsapp'),
               COALESCE(lead_data->>'whatsapp_status', lead_data->>'whatsapp_check'),
               COALESCE(lead_data->'_auto_mail'->>'state', lead_data->'_mail'->>'state'),
               COALESCE(lead_data->'_auto_mail'->>'gmail_message_id',
                        lead_data->'_mail'->>'gmail_message_id'),
               COALESCE(lead_data->'_auto_mail'->'delivery_feedback'->>'state',
                        lead_data->'_mail'->'delivery_feedback'->>'state'),
               COALESCE(lead_data->'_auto_mail'->'delivery_feedback'->>'reason',
                        lead_data->'_mail'->'delivery_feedback'->>'reason'),
               COALESCE(lead_data->>'last_verified_at', lead_data->>'verified_at',
                        lead_data->'qualification'->>'verified_at')
          FROM owner_leads
         ORDER BY CASE WHEN COALESCE(NULLIF(btrim(lead_data->>'website'),''),'')=''
                       THEN 0 ELSE 1 END,
                  CASE WHEN lead_data->>'score' ~ '^[0-9]+(\\.[0-9]+)?$'
                       THEN (lead_data->>'score')::numeric ELSE 0 END DESC,
                  osm_id
    """
    try:
        with connection.cursor() as cur:
            cur.execute(query)
            raw_rows = cur.fetchall()
    except Exception:
        raise RuntimeError("Private CRM export read failed; details redacted") from None
    return [dict(zip(FIELDS, row)) for row in raw_rows]


def _date_text(value):
    if not value:
        return "Kayıt yok"
    if isinstance(value, datetime):
        return value.astimezone(ZONE).replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(ZONE).replace(tzinfo=None) if parsed.tzinfo else parsed
    except (ValueError, TypeError, OverflowError):
        return "Tarih biçimi doğrulanamadı"


def _map_row(row):
    website = str(row.get("website") or "").strip()
    state = row.get("auto_mail_state") or ""
    delivery = row.get("delivery_state") or ""
    crm_status = row.get("status") or "review"
    if delivery == "failed":
        email_status = "Teslimat hatası doğrulandı"
    elif delivery == "delayed":
        email_status = "Teslimat gecikmesi gözlendi"
    elif state == "accepted" or crm_status == "email_sent":
        email_status = "SMTP kabul etti; teslimat doğrulanmadı"
    elif state in ("sending", "uncertain"):
        email_status = "Sonuç belirsiz — yeniden gönderme"
    elif state == "skipped":
        email_status = "Atlandı"
    elif state == "duplicate":
        email_status = "Mükerrer gönderim engellendi"
    elif state == "draft":
        email_status = "Taslak — gönderilmedi"
    else:
        email_status = "İnceleniyor — gönderilmedi"

    if delivery == "failed":
        next_action = "Yeniden gönderme; hata ve itibar durumunu incele."
    elif state == "accepted" or crm_status == "email_sent":
        next_action = "Yeniden gönderme; teslimatı ve yanıtı doğrula."
    else:
        next_action = "Web/WhatsApp durumunu, ihtiyacı ve iletişim uygunluğunu doğrula."

    # OSM website metadata is a research hint only. WhatsApp, true website
    # absence, commercial fit, and the user's requested categories stay unknown.
    research_tier = ("Tier 1: OSM web alanı dolu" if website else
                     "Tier 2: OSM web alanı boş")
    category = "Atanmadı — gerçek web/WhatsApp durumu bilinmiyor"
    service = ("İş akışı otomasyonu fikri; ihtiyacı doğrula" if website else
               "Web sitesi fikri; gerçek site durumunu doğrula")
    source = row.get("osm_id") or ""
    match = re.fullmatch(r"(node|way|relation)/(\d+)", str(source))
    source_url = (f"https://www.openstreetmap.org/{match.group(1)}/{match.group(2)}"
                  if match else "Kaynak bağlantısı kayıtlı değil")
    score = row.get("research_score")
    try:
        score = float(score) if score not in (None, "") else None
    except (TypeError, ValueError):
        score = None
    last_verified = _date_text(row.get("last_verified_at"))
    if isinstance(last_verified, datetime):
        last_verified = last_verified.date()
    if isinstance(last_verified, datetime):
        last_verified = last_verified.date()

    return [
        row.get("business_name") or "İşletme adı kaydedilmemiş",
        row.get("city") or "Doğrulanmadı",
        row.get("sector") or "Sektör kaydedilmemiş",
        row.get("email") or "Kayıt yok",
        website or "OSM web alanı boş; gerçek durum bilinmiyor",
        row.get("whatsapp_status") or "Araştırılmadı",
        category, research_tier, score, service,
        _date_text(row.get("sent_at")),
        row.get("gmail_message_id") or "Kayıt yok — Gmail API kullanılmıyor",
        email_status, row.get("reply_state") or "Yanıt eşleşmedi",
        row.get("delivery_error") or "Yok", next_action, source_url,
        last_verified, row.get("phone") or "Kayıt yok",
        row.get("email_preflight") or "Kontrol edilmedi", source,
    ]


def build_workbook(rows, counts, report_day, send_enabled=False):
    """Build a compact XLSX in memory; never write CRM data into the checkout."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.worksheet.table import Table, TableStyleInfo
    except ImportError:
        raise RuntimeError("Excel export dependency is unavailable") from None

    book = Workbook()
    sheet = book.active
    sheet.title = "CRM"
    sheet.sheet_view.showGridLines = False
    sheet["A2"] = "Müşteri Avcısı AI — CRM günlük anlık görüntüsü"
    sheet["A2"].font = Font(name="Aptos", size=16, bold=True, color="16324F")
    sheet["A3"] = (
        f"Özel Neon CRM • {report_day} • Şehir, WhatsApp ve doğrulama tarihi "
        "kayıtlı değilse bilinmiyor olarak gösterilir."
    )
    sheet["A3"].font = Font(name="Aptos", size=10, italic=True, color="52616B")
    accepted = int(counts.get("accepted", 0) or 0)
    failed = int(counts.get("failed", 0) or 0)
    paused = accepted >= 10 and failed * 100 >= accepted * 15
    sendable = (int(counts.get("eligible", 0) or 0)
                if send_enabled and not paused else 0)
    metrics = [
        ("CRM toplamı", counts.get("total", len(rows))),
        ("Bugün taranan", counts.get("inspected", "Ölçülmedi")),
        ("Bugün yeni kayıt", counts.get("new", 0)),
        ("Şu an gönderilebilir", sendable),
        ("Geçmiş SMTP kabulü", accepted),
        ("Teslimat hatası", failed),
        ("Eşleşen yanıt", counts.get("replies", 0)),
        ("Yasal uygunluğu doğrulanmış", counts.get("eligible", 0)),
        ("Bugün gönderilen", counts.get("accepted_today", 0)),
        ("Kazanılan müşteri", "CRM'de takip edilmiyor"),
    ]
    for index, (label, value) in enumerate(metrics):
        col = index * 2 + 1
        sheet.cell(4, col, label)
        sheet.cell(4, col + 1, value)
        for cell in (sheet.cell(4, col), sheet.cell(4, col + 1)):
            cell.fill = PatternFill("solid", fgColor="EAF1F7")
            cell.font = Font(name="Aptos", size=10, bold=True, color="16324F")
            cell.alignment = Alignment(vertical="center")
    sheet["A5"] = (
        f"{accepted} SMTP kabulü gelen kutusu teslimi değildir. Mevcut puan eski OSM "
        "araştırma sezgisidir; ticari uygunluk puanı değildir. Yasal uygunluğu "
        "doğrulanmamış işletmelere gönderim yapılmaz."
    )
    sheet["A5"].font = Font(name="Aptos", size=9, color="6B4F00")
    sheet["A6"] = (
        "Segment 2/1 yalnızca OSM web sitesi alanına göre gösterilir. OSM kaydında "
        "site alanının boş olması gerçek site yokluğu veya WhatsApp kullanmama kanıtı değildir."
    )
    sheet["A6"].font = Font(name="Aptos", size=9, color="6B4F00")

    header_row = 8
    for col, header in enumerate(HEADERS, start=1):
        cell = sheet.cell(header_row, col, header)
        cell.fill = PatternFill("solid", fgColor="16324F")
        cell.font = Font(name="Aptos", size=10, bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[header_row].height = 38

    data_rows = []
    for row in rows:
        data_rows.append(_map_row(row))
    for r_index, values in enumerate(data_rows, start=header_row + 1):
        for c_index, value in enumerate(values, start=1):
            cell = sheet.cell(r_index, c_index, value)
            cell.font = Font(name="Aptos", size=10, color="202A33")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if r_index % 2:
                cell.fill = PatternFill("solid", fgColor="F2F7FA")
        sheet.cell(r_index, 11).number_format = "yyyy-mm-dd hh:mm"
        sheet.cell(r_index, 18).number_format = "yyyy-mm-dd"
        sheet.row_dimensions[r_index].height = 32
        source_cell = sheet.cell(r_index, 17)
        if str(source_cell.value).startswith("https://"):
            source_cell.hyperlink = source_cell.value
            source_cell.style = "Hyperlink"

    widths = [28, 18, 20, 34, 34, 20, 30, 27, 18, 38, 20, 32, 34,
              22, 22, 40, 45, 20, 20, 24, 20]
    for col, width in enumerate(widths, start=1):
        sheet.column_dimensions[sheet.cell(1, col).column_letter].width = width
    sheet.freeze_panes = f"A{header_row + 1}"
    sheet.auto_filter.ref = f"A{header_row}:U{header_row + len(data_rows)}"
    if data_rows:
        table = Table(displayName="CrmSnapshot", ref=sheet.auto_filter.ref)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2",
                                               showFirstColumn=False,
                                               showLastColumn=False,
                                               showRowStripes=True,
                                               showColumnStripes=False)
        sheet.add_table(table)
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.outlinePr.summaryBelow = True
    sheet.title = "Tüm işletmeler"
    summary = book.create_sheet("Genel özet", 0)
    summary.sheet_view.showGridLines = False
    summary["A1"] = "Müşteri Avcısı AI — Günlük özel CRM özeti"
    summary["A1"].font = Font(name="Aptos", size=16, bold=True, color="16324F")
    for source_row, target_row in ((3, 2), (5, 3), (6, 4)):
        summary.cell(target_row, 1, sheet.cell(source_row, 1).value)
    for source_row in range(4, 5):
        for col in range(1, 21):
            cell = summary.cell(6, col, sheet.cell(source_row, col).value)
            cell.fill = PatternFill("solid", fgColor="EAF1F7")
            cell.font = Font(name="Aptos", size=9, bold=True, color="16324F")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
    summary.column_dimensions["A"].width = 42
    summary.column_dimensions["B"].width = 24
    summary.freeze_panes = "A6"

    # Keep the requested report navigation while returning only rows supported
    # by the stored evidence. Empty tabs are intentional when a signal is unknown.
    extra_tabs = {
        "Yüksek potansiyelli müşteriler": ([], "Mevcut araştırma puanı ticari puan değildir; yüksek potansiyel henüz hesaplanmıyor."),
        "Web sitesi olmayanlar": ([], "OSM web alanı boşluğu gerçek web sitesi yokluğu kanıtı değildir; doğrulama bekliyor."),
        "WhatsApp otomasyonu adayları": ([], "WhatsApp durumu doğrulanmadığından aday sınıflandırması yapılmadı."),
        "AI otomasyonu adayları": ([], "Doğrulanmış iş akışı ihtiyacı bulunmadığından aday sınıflandırması yapılmadı."),
        "Başarılı gönderimler": ([], "Teslimatı doğrulanmış gönderim kaydı bulunmuyor; SMTP kabulü teslim kanıtı değildir."),
        "Başarısız gönderimler": ([], "Raporlama kaynağında mesaj bazlı hata nedeni eksik; özet sayaç dışında sınıflandırma yapılamıyor."),
        "Gelen yanıtlar": ([], "Eşleşmiş yanıt kaydı bulunmuyor."),
        "Görüşmeler": ([], "Görüşme durumu CRM'de izlenmiyor."),
        "Gönderime uygun olmayanlar": ([], "412 kaydın hiçbiri şu an gönderime uygun değil; ayrıntılı yasal ve teknik nedenler CRM'de eksik."),
        "Günlük istatistikler": ([], "Ölçülmeyen değerler sıfır değil, bilinmiyor olarak değerlendirilir."),
    }
    for name, (subset, note) in extra_tabs.items():
        tab = book.create_sheet(name)
        tab.sheet_view.showGridLines = False
        tab["A1"] = note
        tab["A1"].font = Font(name="Aptos", size=10, italic=True, color="6B4F00")
        for col, header in enumerate(HEADERS, start=1):
            cell = tab.cell(3, col, header)
            cell.fill = PatternFill("solid", fgColor="16324F")
            cell.font = Font(name="Aptos", size=10, bold=True, color="FFFFFF")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        tab.row_dimensions[3].height = 38
        if name == "Günlük istatistikler":
            tab.append(["Metrik", "Değer"])
            for label, value in metrics:
                tab.append([label, value])
        tab.freeze_panes = "A4"
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def send_document(token, chat_id, content, filename, caption="Günlük özel CRM raporu",
                  opener=None):
    """Upload a report to one positive, private owner chat ID; never a group."""
    if not token or not str(chat_id).isdigit() or int(chat_id) <= 0:
        raise RuntimeError("Private owner Telegram chat is required")
    if not isinstance(content, bytes) or not content.startswith(b"PK\x03\x04"):
        raise RuntimeError("CRM workbook is invalid")
    boundary = "----CodexCrmReportBoundary7MA4YWxkTrZu0gW"
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", str(filename))[:100]
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{int(chat_id)}\r\n".encode(),
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n").encode("utf-8"),
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{safe_name}\"\r\n"
         f"Content-Type: {MIME_XLSX}\r\n\r\n").encode("utf-8"),
        content,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendDocument",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    open_url = urllib.request.urlopen if opener is None else opener
    try:
        with open_url(request, timeout=45) as response:
            result = json.loads(response.read(1_000_000))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        raise RuntimeError("Owner CRM workbook delivery uncertain; details redacted") from None
    sent = result.get("result") if isinstance(result, dict) else None
    if (not isinstance(result, dict) or result.get("ok") is not True
            or not isinstance(sent, dict) or type(sent.get("message_id")) is not int
            or sent["message_id"] <= 0 or not isinstance(sent.get("chat"), dict)
            or sent["chat"].get("id") != int(chat_id)):
        raise RuntimeError("Owner CRM workbook delivery was not confirmed")
    return sent["message_id"]
