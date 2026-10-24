"""Discover small sets of businesses via OpenStreetMap and report only to owner."""
import html
import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Public Overpass instances can be temporarily busy; keep requests low volume.
OVERPASS_ENDPOINTS = (
    'https://overpass.private.coffee/api/interpreter',
    'https://overpass-api.de/api/interpreter',
    'https://overpass.osm.ch/api/interpreter',
)
DEFAULT_BBOX = '40.982,29.015,41.008,29.055'
CATEGORIES = {'car_wash': 'Oto yıkama', 'hairdresser': 'Kuaför/berber', 'beauty': 'Güzellik salonu'}


def bbox_parse(s):
    p = [float(v.strip()) for v in s.split(',')]
    if len(p) != 4 or not (-90 <= p[0] < p[2] <= 90 and -180 <= p[1] < p[3] <= 180):
        raise ValueError('SCAN_BBOX güney,batı,kuzey,doğu şeklinde olmalı')
    if p[2] - p[0] > .2 or p[3] - p[1] > .2:
        raise ValueError('Kamu sunucusuna aşırı geniş alan sorgulanamaz')
    return tuple(p)


def get_osm(bbox, opener=urlopen):
    box = ','.join(str(v) for v in bbox)
    query = ('[out:json][timeout:25];('
             f'nwr["amenity"="car_wash"]({box});'
             f'nwr["shop"="hairdresser"]({box});'
             f'nwr["shop"="beauty"]({box}););out center tags 200;')
    payload = urlencode({'data': query}).encode()
    for endpoint in OVERPASS_ENDPOINTS:
        req = Request(endpoint, data=payload, headers={
            'User-Agent': 'MusteriAvcisiAI/0.1 (small weekdays-only lead research)',
            'Content-Type': 'application/x-www-form-urlencoded'})
        try:
            with opener(req, timeout=25) as response:
                data = json.load(response)
            return data['elements']
        except HTTPError as exc:
            # Try another instance only for temporary failures.
            if exc.code not in (408, 429, 500, 502, 503, 504):
                raise RuntimeError(f'Overpass API HTTP {exc.code}') from None
        except (TimeoutError, URLError, OSError):
            # Limited sequential fallbacks only; do not retry indefinitely.
            pass
    raise RuntimeError('Overpass instances unavailable; no leads sent')


def lead_from_osm(row):
    tags = row.get('tags') or {}
    name = str(tags.get('name') or '').strip()
    typ, oid = row.get('type'), row.get('id')
    category = CATEGORIES.get(tags.get('amenity')) or CATEGORIES.get(tags.get('shop'))
    if not name or not category or typ not in ('node', 'way', 'relation') or not isinstance(oid, int):
        return None
    website = str(tags.get('website') or tags.get('contact:website') or '').strip()
    phone = str(tags.get('contact:phone') or tags.get('phone') or '').strip()
    address = ' '.join(str(tags.get(t) or '') for t in
                       ('addr:street', 'addr:housenumber', 'addr:district')).strip()
    return {'id': f'{typ}/{oid}', 'name': name[:100], 'category': category,
            'website': website[:200], 'phone': phone[:80], 'address': address[:150],
            'score': 45 + (30 if not website else 0) + (15 if phone else 0) + (10 if address else 0)}


def select_leads(raw, already_seen, maximum=5):
    unique = {}
    for row in raw:
        lead = lead_from_osm(row)
        if lead and lead['id'] not in already_seen:
            unique[lead['id']] = lead
    return sorted(unique.values(), key=lambda x: (-x['score'], x['id']))[:maximum]


def discovery_stats(raw, already_seen):
    """Count discovery outcomes without exposing business contact details."""
    eligible = {}
    rejected = 0
    for row in raw:
        lead = lead_from_osm(row)
        if lead is None:
            rejected += 1
        else:
            eligible[lead['id']] = lead
    old = sum(lead_id in already_seen for lead_id in eligible)
    return {
        'fetched': len(raw),
        'eligible': len(eligible),
        'rejected': rejected,
        'duplicates': len(raw) - rejected - len(eligible),
        'already_seen': old,
        'new': len(eligible) - old,
    }


def emit_discovery_summary(stats, sent, env, output):
    """Print safe counters, optionally writing GitHub's workflow summary."""
    summary = (
        f"OSM tarama: {stats['fetched']} ham kayıt; "
        f"{stats['eligible']} geçerli; {stats['rejected']} elendi; "
        f"{stats['duplicates']} tekrar; {stats['already_seen']} önce görülmüş; "
        f"{stats['new']} yeni aday"
    )
    output(summary)
    output(f'Gönderilen yeni fırsat: {sent}')
    summary_path = env.get('GITHUB_STEP_SUMMARY')
    if summary_path:
        with open(summary_path, 'a', encoding='utf-8') as handle:
            handle.write(
                '\n### Müşteri Avcısı AI — OSM tarama özeti\n'
                '| Ham | Geçerli | Elenen | Tekrar | Önceden görülen | Yeni aday | Telegram gönderimi |\n'
                '| ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n'
                f"| {stats['fetched']} | {stats['eligible']} | {stats['rejected']} | "
                f"{stats['duplicates']} | {stats['already_seen']} | "
                f"{stats['new']} | {sent} |\n"
            )


# Ideas are hypotheses for manual prospect research, not verified shortcomings.
SECTOR_IDEAS = {
    'Oto yıkama': {
        'website': 'yıkama paketleri, konum ve randevu talebi için mobil bir sayfa',
        'automation': 'randevu taleplerinin takibi ve tekrar bakım hatırlatmaları',
    },
    'Kuaför/berber': {
        'website': 'hizmet ve örnek çalışmalar galerisiyle randevu talep sayfası',
        'automation': 'randevu takvimi, uygunluk takibi ve hatırlatma akışı',
    },
    'Güzellik salonu': {
        'website': 'seans tanıtımı, hizmet kataloğu ve danışma/randevu formu',
        'automation': 'seans takvimi, randevu hatırlatmaları ve talep takibi',
    },
}


# Proposed premium website scope, not a claim about an existing business.
PREMIUM_SITE_SCOPE = {
    'Oto yıkama': 'özgün marka tasarımı, yıkama paketleri, mobil randevu veya WhatsApp talebi ve harita',
    'Kuaför/berber': 'özel tasarım, örnek çalışma galerisi, hizmet menüsü, mobil randevu ve harita',
    'Güzellik salonu': 'premium görsel tasarım, hizmet/seans tanıtımı ve mobil danışma-randevu formu',
}

def recommend(lead):
    """Classify from *OSM metadata only*, never infer the business' real needs."""
    website_recorded = bool(str(lead.get('website') or '').strip())
    focus = 'automation' if website_recorded else 'website'
    ideas = SECTOR_IDEAS.get(lead.get('category'), {
        'website': 'mobil tanıtım ve iletişim sayfası',
        'automation': 'randevu ve talep takibi',
    })
    if focus == 'website':
        evidence = ('OSM kaydında web sitesi alanı boş. İşletmenin gerçekten '
                    'web sitesi olup olmadığını manuel doğrula.')
        indicator = '🔴 WEB SİTESİ FIRSATI'
    else:
        evidence = ('OSM kaydında web adresi var. Otomasyon yalnızca görüşmede '
                    'değerlendirilecek bir fikir; mevcut sistemleri bilinmiyor.')
        indicator = '🟢 OTOMASYON FIRSATI'
    contacts = ('OSM telefon kaydı var; iletişim uygunluğunu ayrıca doğrula.'
                if lead.get('phone') else
                'OSM telefon alanı boş; iletişim kanalı ayrıca araştırılmalı.')
    location = ('Konum bilgisi OSM üzerinde kayıtlı.'
                if lead.get('address') else
                'OSM adres alanı eksik; konumu ayrıca doğrula.')
    if focus == 'website':
        next_step = ('Önce işletmenin web varlığını manuel doğrula. Gerçekten ihtiyaç '
                     'görülüyorsa uygun ve hukuka uygun tek bir iletişimde örnek '
                     'tasarımı görmeyi isteyip istemediklerini sor; yanıt yoksa ısrar etme.')
    else:
        next_step = ('Mevcut randevu ve müşteri takip süreçlerini araştır. İhtiyaç '
                     'doğrulanmadan otomasyon çözümü varmış gibi davranma.')
    return {'focus': focus, 'indicator': indicator, 'idea': ideas[focus],
            'evidence': evidence, 'contacts': contacts, 'location': location,
            'next_step': next_step,
            'premium_scope': PREMIUM_SITE_SCOPE.get(
                lead.get('category'),
                'özel marka tasarımı, hızlı mobil sayfalar, iletişim ve talep formu')
            if focus == 'website' else None}


def offer(lead):
    """Unsent, individualized proposal. Never claim verified unmet needs."""
    recommendation = recommend(lead)
    name = str(lead.get('name') or 'işletmeniz')
    category = str(lead.get('category') or 'işletmeniz')
    if recommendation['focus'] == 'website':
        return (f'Merhaba, {name} için {category.lower()} alanına özel, '
                f'premium bir web sitesi konsepti önermek istiyorum: '
                f"{recommendation['premium_scope']}. "
                'İlginizi çekerse kısa, size özel bir örnek tasarım '
                'paylaşabilirim. İyi çalışmalar.')
    return (f'Merhaba, {name} için {category.lower()} alanındaki '
            f"iş süreçlerini kolaylaştırabilecek bir fikir: {recommendation['idea']}. "
            'Mevcut sistemlerinize uygunsa kısa bir örnek paylaşabilirim. '
            'İyi çalışmalar.')


def format_telegram(lead, demo=False):
    h = html.escape
    suggestion = recommend(lead)
    intro = '🧪 DEMO — GERÇEK İŞLETME DEĞİL\n' if demo else ''
    site = ('⚠️ OSM kaydında web sitesi belirtilmemiş; ayrıca doğrula'
            if not lead['website'] else '✅ OSM kaydında web sitesi var')
    lines = [intro + '🎯 <b>YENİ MÜŞTERİ FIRSATI</b>',
             f"🏪 <b>{h(lead['name'])}</b>",
             f"🏷️ {h(lead['category'])} | OSM araştırma önceliği: {lead['score']}/100",
             f"📌 <b>{h(suggestion['indicator'])}</b>",
             f"💡 İşletmeye uygun fikir: {h(suggestion['idea'])}",
             *( [f"✨ Premium web sitesi kapsamı: {h(suggestion['premium_scope'])}"]
                if suggestion['premium_scope'] else []),
             f"🔎 Gerekçe: {h(suggestion['evidence'])}",
             f'🌐 {site}']
    if lead['phone']:
        lines.append(f"☎️ OSM telefon kaydı: {h(lead['phone'])}")
    if lead['address']:
        lines.append(f"📍 {h(lead['address'])}")
    if lead['website']:
        lines.append(f"🔗 Kayıtlı site: {h(lead['website'])}")
    lines += [f"📝 Kontrol: {h(suggestion['contacts'])} {h(suggestion['location'])}",
              f"➡️ Sonraki adım: {h(suggestion['next_step'])}",
              f"🗺️ <a href=\"https://www.openstreetmap.org/{h(lead['id'])}\">OSM kaydı</a>",
              '\n✉️ <b>Yalnızca manuel kullanım için kişiselleştirilmiş teklif:</b>',
              f"<blockquote>{h(offer(lead))}</blockquote>",
              '\n© OpenStreetMap contributors — ODbL. İhtiyaçlar doğrulanmadı. İşletmeye otomatik mesaj gönderilmez.']
    return '\n'.join(lines)


def read_seen(path):
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('seen_ids', []), list):
        raise ValueError('Bozuk seen.json')
    return set(data.get('seen_ids', []))


def save_seen(path, seen):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps({'seen_ids': sorted(seen)}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def send_telegram(message, token, chat_id, opener=urlopen):
    if len(message) > 4096:
        raise ValueError('Telegram sınırı aşıldı')
    body = json.dumps({'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML',
                       'disable_web_page_preview': True}).encode()
    request = Request(f'https://api.telegram.org/bot{token}/sendMessage', data=body,
                      headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with opener(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        # urllib's exception contains the full bot-token URL: never expose it in CI logs.
        raise RuntimeError(f'Telegram API HTTP {exc.code}; credentials redacted') from None
    except URLError:
        raise RuntimeError('Telegram API connection failed; credentials redacted') from None
    if not result.get('ok'):
        raise RuntimeError('Telegram API gönderimi başarısız')
    return result.get('result', {}).get('message_id')


def live(env=None, opener=urlopen, output=print):
    env = os.environ if env is None else env
    token, chat_id = env.get('TELEGRAM_BOT_TOKEN'), env.get('TELEGRAM_CHAT_ID')
    if not token or not chat_id:
        raise RuntimeError('TELEGRAM_BOT_TOKEN ve TELEGRAM_CHAT_ID eksik')
    state = Path(env.get('STATE_FILE', 'data/seen.json'))
    seen = read_seen(state)
    raw = get_osm(bbox_parse(env.get('SCAN_BBOX') or DEFAULT_BBOX), opener)
    stats = discovery_stats(raw, seen)
    chosen = select_leads(raw, seen)
    sent = 0
    try:
        for item in chosen:
            send_telegram(format_telegram(item), token, chat_id, opener)
            seen.add(item['id'])
            save_seen(state, seen)
            sent += 1
    finally:
        emit_discovery_summary(stats, sent, env, output)
    return sent
