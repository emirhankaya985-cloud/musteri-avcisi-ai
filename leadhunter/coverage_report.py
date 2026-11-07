"""Public-only OSM coverage text for the owner status command and hourly digest.

This is historical confirmed map-tile coverage, not the number of leads
collected, total region breadth fetched by Overpass, or a promise of completion.
"""
from pathlib import Path
from .tile_progress import _load, tile_total
from .scan_regions import PILOT_BBOXES
from .core import bbox_parse


def coverage_text(path="data/osm_tile_progress.json", details=False):
    path = Path(path)
    if not path.exists():
        return "🗺️ Harita ilerlemesi: henüz kalıcı kanıt yok."
    try:
        data = _load(path)
        pieces, total, summary, stalled = 0, 0, [], []
        for i, coordinates in enumerate(PILOT_BBOXES,1):
            slot = f"pilot_{i}_of_8"
            capacity = tile_total(bbox_parse(coordinates))
            entry = data["regions"].get(slot) or {}
            if entry and entry["total"] != capacity:
                raise ValueError("Inconsistent OSM geometry")
            done = entry.get("next",0)
            failures = entry.get("stalls",0)
            pieces += done
            total += capacity
            summary.append(f"{i}:{done}/{capacity}")
            if failures >= 3:
                stalled.append(str(i))
        percent = pieces * 100 / total if total else 0
        result = f"🗺️ Kanıtlı OSM kapsaması: {pieces}/{total} (%{percent:.1f})"
        if details:
            result += "\n📍 Bölge parçaları: " + " | ".join(summary)
            if stalled:
                result += "\n⚠️ İlerlemeyen bölgeler: " + ",".join(stalled)
        return result
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        return "🗺️ Harita ilerlemesi: kanıt doğrulanamadı."
