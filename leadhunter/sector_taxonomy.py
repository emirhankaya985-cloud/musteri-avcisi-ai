"""Source-backed OSM sector taxonomy.

This classifies tags already present in an OSM record. It does not expand a
provider query, establish a business's legal identity, infer unmet service
needs, or estimate company size.
"""
def _entry(sector, sector_label, subcategory, label, key, value,
           *, entity_kind="business_place"):
    return {
        "sector": sector,
        "sector_label": sector_label,
        "subcategory": subcategory,
        "label": label,
        "tag_key": key,
        "tag_value": value,
        "entity_kind": entity_kind,
    }


# OSM distinguishes venues and types of activity with different keys. Keep
# each tag explicit so downstream displays can explain exactly why it matched.
TAG_TAXONOMY = (
    _entry("food_hospitality", "Yeme içme", "restaurant", "Restoran",
           "amenity", "restaurant"),
    _entry("food_hospitality", "Yeme içme", "cafe", "Kafe",
           "amenity", "cafe"),
    _entry("food_hospitality", "Yeme içme", "fast_food", "Hızlı servis yeme içme",
           "amenity", "fast_food"),
    _entry("accommodation", "Konaklama", "hotel", "Otel",
           "tourism", "hotel"),
    _entry("accommodation", "Konaklama", "motel", "Motel",
           "tourism", "motel"),
    _entry("accommodation", "Konaklama", "guest_house", "Konukevi",
           "tourism", "guest_house"),
    _entry("accommodation", "Konaklama", "hostel", "Hostel",
           "tourism", "hostel"),
    _entry("real_estate", "Gayrimenkul", "estate_agent", "Emlak ofisi",
           "office", "estate_agent"),
    _entry("real_estate", "Gayrimenkul", "estate_agent", "Emlak ofisi",
           "shop", "estate_agent"),
    _entry("automotive", "Otomotiv", "car_wash", "Oto yıkama",
           "amenity", "car_wash"),
    _entry("automotive", "Otomotiv", "car_repair", "Oto tamir servisi",
           "shop", "car_repair"),
    _entry("automotive", "Otomotiv", "car_dealer", "Otomotiv satış noktası",
           "shop", "car"),
    _entry("automotive", "Otomotiv", "car_parts", "Oto yedek parça",
           "shop", "car_parts"),
    _entry("construction", "İnşaat", "construction_company", "İnşaat şirketi",
           "office", "construction_company"),
    _entry("construction", "İnşaat", "builder", "Yapı ustası / yüklenici",
           "craft", "builder"),
    _entry("manufacturing", "Üretim", "production_site", "Üretim tesisi",
           "man_made", "works", entity_kind="production_site"),
    _entry("manufacturing", "Üretim", "production_site", "Üretim tesisi",
           "industrial", "factory", entity_kind="production_site"),
    _entry("beauty_personal_care", "Güzellik ve kişisel bakım", "beauty_salon",
           "Güzellik salonu", "shop", "beauty"),
    _entry("beauty_personal_care", "Güzellik ve kişisel bakım", "hairdresser",
           "Kuaför / berber", "shop", "hairdresser"),
    _entry("retail_services", "Perakende hizmetleri", "florist", "Çiçekçi",
           "shop", "florist"),
    _entry("retail_services", "Perakende hizmetleri", "optician", "Optik mağazası",
           "shop", "optician"),
    _entry("tourism_travel", "Turizm ve seyahat", "travel_agent", "Seyahat acentesi",
           "office", "travel_agent"),
    _entry("tourism_travel", "Turizm ve seyahat", "travel_agency", "Seyahat acentesi",
           "shop", "travel_agency"),
)

_BY_TAG = {(row["tag_key"], row["tag_value"]): row for row in TAG_TAXONOMY}


def classify_osm_tags(tags, *, osm_type=None, osm_id=None):
    """Return a taxonomy classification plus traceable direct-tag evidence.

    The generic `office=company` tag establishes only that the OSM object is
    tagged as a company office. It cannot establish a target sector, service
    need, SME status, or marketing eligibility.
    """
    tags = tags if isinstance(tags, dict) else {}
    matches = []
    for (key, value), entry in _BY_TAG.items():
        if tags.get(key) == value:
            matches.append(entry)

    # Preserve the legacy supported tag while making a generic company
    # candidate available to research. It remains explicitly unclassified.
    generic_company = tags.get("office") == "company"
    source_ref = None
    if (osm_type in ("node", "way", "relation")
            and isinstance(osm_id, int) and not isinstance(osm_id, bool)
            and osm_id > 0):
        source_ref = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"

    evidence = [
        {"source": "OpenStreetMap", "source_url": source_ref,
         "tag_key": row["tag_key"], "tag_value": row["tag_value"],
         "evidence_type": "direct_osm_classification_tag",
         "entity_kind": row["entity_kind"]}
        for row in matches
    ]
    if generic_company:
        evidence.append({
            "source": "OpenStreetMap", "source_url": source_ref,
            "tag_key": "office", "tag_value": "company",
            "evidence_type": "direct_osm_generic_company_tag",
        })

    sectors = sorted({row["sector"] for row in matches})
    if len(sectors) > 1:
        return {
            "sector": None, "sector_label": "Bilinmiyor",
            "subcategory": None, "category": None,
            "classification_status": "multiple_sectors_manual_review",
            "matches": matches, "category_evidence": evidence,
            "business_size_status": "unknown",
        }
    if len(sectors) == 1:
        sector = sectors[0]
        subcategories = sorted({row["subcategory"] for row in matches})
        if len(subcategories) == 1:
            primary = next(row for row in matches
                           if row["subcategory"] == subcategories[0])
            return {
                "sector": sector, "sector_label": primary["sector_label"],
                "subcategory": primary["subcategory"],
                "category": primary["label"],
                "classification_status": "source_tag_match",
                "matches": matches, "category_evidence": evidence,
                "business_size_status": "unknown",
            }
        return {
            "sector": sector, "sector_label": matches[0]["sector_label"],
            "subcategory": None, "category": None,
            "classification_status": "multiple_subcategories_manual_review",
            "matches": matches, "category_evidence": evidence,
            "business_size_status": "unknown",
        }
    if generic_company:
        return {
            "sector": None, "sector_label": "Bilinmiyor",
            "subcategory": "general_company_unknown_sector",
            "category": "Şirket ofisi (sektör bilinmiyor)",
            "classification_status": "generic_company_manual_research",
            "matches": [], "category_evidence": evidence,
            "business_size_status": "unknown",
        }
    return {
        "sector": None, "sector_label": "Bilinmiyor",
        "subcategory": None, "category": None,
        "classification_status": "unknown_manual_research",
        "matches": [], "category_evidence": evidence,
        "business_size_status": "unknown",
    }


def overpass_tag_selectors():
    """Return explicit candidate tag pairs; query callers must add their own bounds/caps."""
    return tuple(sorted(_BY_TAG))
