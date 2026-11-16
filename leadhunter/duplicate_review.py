"""Conservative cross-OSM company similarity queue in private Neon.

Equal names across branches are review candidates, NOT merged businesses.
No SMTP, Telegram, public GitHub identifiers or customer data are emitted.
"""
import json
import os
import re
import unicodedata
from collections import defaultdict
from itertools import combinations
from urllib.parse import urlsplit

from .review_private import connect_private_database

REASONS=frozenset((
    "same_first_party_domain","same_phone",
    "same_name_address","same_name_category_review"))
SHARED_HOSTS=frozenset((
    "facebook.com","m.facebook.com","instagram.com","tiktok.com",
    "wa.me","whatsapp.com","linktr.ee","bit.ly","tinyurl.com",
    "sites.google.com","maps.google.com","google.com",
    "youtube.com","x.com","twitter.com","business.site",
    "wixsite.com","blogspot.com","wordpress.com",
    "kolayrandevu.com"))
MAX_CANDIDATE_PAIRS=25000


def normalized(value):
    text=unicodedata.normalize("NFKC",str(value or "")).casefold()
    text=re.sub(r"[^\w]+"," ",text,flags=re.UNICODE)
    return " ".join(text.split())


def domain(value):
    raw=str(value or "").strip()
    if not raw or len(raw)>300:
        return None
    try:
        split=urlsplit(raw if "://" in raw else "https://"+raw)
        hostname=(split.hostname or "").casefold().rstrip(".")
        if hostname.startswith("www."):
            hostname=hostname[4:]
        if (not hostname or "." not in hostname or
                hostname in SHARED_HOSTS or hostname.endswith(".facebook.com")
                or hostname.endswith(".instagram.com")
                or hostname.endswith(".wixsite.com")):
            return None
        return hostname
    except ValueError:
        return None


def phone(value):
    raw=re.sub(r"[^0-9]+","",str(value or ""))
    if len(raw)==11 and raw.startswith("0"):
        raw="90"+raw[1:]
    elif len(raw)==10 and raw.startswith("5"):
        raw="90"+raw
    return raw if 10<=len(raw)<=15 else None


def candidates(rows):
    """Return {sorted(id_a,id_b): set(safe reason labels)}.

    Uses robust signals when present; exact name/category-only is a weak
    candidate requiring manual review and never permits an automatic merge.
    """
    buckets=defaultdict(set)
    for lead_id,raw in rows:
        if not isinstance(lead_id,str) or not 0<len(lead_id)<=200:
            raise ValueError("Private lead has invalid identifier")
        data=json.loads(raw) if isinstance(raw,str) else raw
        if not isinstance(data,dict):
            raise ValueError("Private lead JSON is not an object")
        name=normalized(data.get("name"))
        category=normalized(data.get("category"))
        address=normalized(data.get("address"))
        host=domain(data.get("website"))
        telephone=phone(data.get("phone"))
        if host:
            buckets[("same_first_party_domain",host)].add(lead_id)
        if telephone:
            buckets[("same_phone",telephone)].add(lead_id)
        if name and category and len(name)>=4:
            buckets[("same_name_category_review",name,category)].add(lead_id)
            if address and len(address)>=6:
                buckets[("same_name_address",name,address,category)].add(lead_id)
    pairs=defaultdict(set)
    for key,values in buckets.items():
        if len(values)<2:
            continue
        # Never silently omit a crowded group: halt and require manual
        # eligibility review instead of fabricating complete dedup.
        if len(values)>250:
            raise RuntimeError("Duplicate group exceeds safe review limit")
        for left,right in combinations(sorted(values),2):
            pairs[(left,right)].add(key[0])
            if len(pairs)>MAX_CANDIDATE_PAIRS:
                raise RuntimeError("Duplicate review candidate volume exceeds safe limit")
    return {pair:tuple(sorted(evidence)) for pair,evidence in pairs.items()}


def sync(conn,output=print):
    with conn.cursor() as cur:
        cur.execute("SELECT osm_id,lead_data FROM owner_leads ORDER BY osm_id")
        rows=cur.fetchall()
    pair_map=candidates(rows)
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(785632014)")
            cur.execute("SELECT count(*) FROM owner_duplicate_review_pairs")
            before=int(cur.fetchone()[0])
            for (a,b),reasons in sorted(pair_map.items()):
                cur.execute(
                    "INSERT INTO owner_duplicate_review_pairs "
                    "(lead_a,lead_b,evidence) VALUES (%s,%s,%s) "
                    "ON CONFLICT(lead_a,lead_b) DO UPDATE SET "
                    "evidence=EXCLUDED.evidence,last_observed_at=now()",
                    (a,b,list(reasons)))
            cur.execute("SELECT count(*) FROM owner_duplicate_review_pairs")
            after=int(cur.fetchone()[0])
    output("COMPANY_DUPLICATES: pairs_detected="+str(len(pair_map))+
           "; new_private_review_pairs="+str(after-before)+
           "; automatically_merged=0; outbound_business_mail=0")
    return len(pair_map), after-before


def run(env=None,output=print,conn=None):
    env=os.environ if env is None else env
    owned=conn is None
    db=connect_private_database(env.get("REVIEW_DATABASE_URL")) if owned else conn
    try:
        return sync(db,output)
    finally:
        if owned:
            db.close()


if __name__=="__main__":
    run()
