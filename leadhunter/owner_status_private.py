"""Read-only, owner-private operational summary for Telegram /durum.

Only aggregate integers and freshness classes may leave this module.
No recipient addresses, company names, credentials, message bodies or raw
query errors are included in Telegram or GitHub logs.
"""
from datetime import datetime, timezone

CATEGORIES = (
    ("Kuaför/berber", "Kuaför"),
    ("Oto yıkama", "Oto yıkama"),
    ("Güzellik salonu", "Güzellik"),
    ("Çiçekçi", "Çiçekçi"),
    ("Optik mağazası", "Optik"),
)


def collect(review_store, now=None):
    """Read aggregate-only private CRM facts without modifying any tables."""
    from .ops_freshness import classify
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Owner summary needs timezone-aware time")
    with review_store.db.cursor() as cur:
        cur.execute(
            "SELECT COALESCE(sum(new_registered),0) FROM owner_scan_run_metrics "
            "WHERE report_day=(now() AT TIME ZONE 'Europe/Istanbul')::date")
        new_today = int(cur.fetchone()[0])
        cur.execute(
            "SELECT coalesce(lead_data->>'category',''),count(*) "
            "FROM owner_leads GROUP BY 1")
        category_rows = cur.fetchall()
        cur.execute("SELECT max(created_at) FROM owner_scan_run_metrics")
        last_scan = cur.fetchone()[0]
        cur.execute("SELECT max(created_at) FROM owner_mail_watch_runs")
        last_gmail = cur.fetchone()[0]
    if new_today < 0:
        raise ValueError("Negative scan metric")
    accepted = {key: 0 for key, _ in CATEGORIES}
    unclassified = 0
    for key, value in category_rows:
        count = int(value)
        if count < 0:
            raise ValueError("Negative category count")
        if key in accepted:
            accepted[key] += count
        else:
            unclassified += count
    freshness = classify(last_scan, last_gmail, now=now)
    return {"new_today": new_today, "categories": accepted,
            "unclassified": unclassified, "freshness": freshness}


def safe_text(data):
    """Only fixed sector labels, nonnegative counts and known freshness classes."""
    categories = data["categories"]
    if (type(data["new_today"]) is not int or data["new_today"] < 0 or
            type(data["unclassified"]) is not int or data["unclassified"] < 0):
        raise ValueError("Invalid owner summary metrics")
    for key, _ in CATEGORIES:
        if type(categories[key]) is not int or categories[key] < 0:
            raise ValueError("Invalid sector count")
    statuses = data["freshness"]
    if any(statuses.get(k) not in ("fresh", "stale", "unverified")
           for k in ("scan", "gmail")):
        raise ValueError("Invalid schedule health class")
    labels = {"fresh":"güncel","stale":"gecikmiş","unverified":"doğrulanamadı"}
    text = (
        "📊 Özel CRM işletim özeti\n"
        f"🆕 Bugün Neon'a yeni aday: {data['new_today']}\n"
        "🏪 Beş sektör: " +
        " | ".join(label + ": " + str(categories[key])
                   for key, label in CATEGORIES) + "\n"
        f"⏱️ Son kayıt güncelliği: tarama {labels[statuses['scan']]} | "
        f"Gmail {labels[statuses['gmail']]}\n"
    )
    if data["unclassified"]:
        text += f"🧩 Diğer/sınıflandırılmamış: {data['unclassified']}\n"
    return text + (
        "ℹ️ Bu sayaçlar Render HTTP veya yetkili CRM/OAuth kabulü değildir. "
        "Yeni ticari SMTP gönderimi kapalı."
    )
