"""Rebuild the checked-in OSM-derived boundary inventory from its pinned source."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from leadhunter.osm_boundary_manifest import build_manifest

RELEASE_TAG = "v2026.11.0"
TAG_COMMIT_SHA = "2bd61aecb8e500ce049fa3ae4c6eb76350bcf9b0"
SUMMARY_SHA256 = "7dc6fbc3741aeb158f186e7860d8ba6399d6a46ee7c936d0f63a5aaf2a824803"
SUMMARY_URL = ("https://raw.githubusercontent.com/topografya/veri/"
               f"{RELEASE_TAG}/sinirlar/ozet.json")
OUTPUT = Path("data/osm_boundary_manifest_v2026.11.0.json")


def build(raw_summary: bytes) -> dict:
    digest = hashlib.sha256(raw_summary).hexdigest()
    if digest != SUMMARY_SHA256:
        raise RuntimeError("Pinned OSM boundary summary checksum mismatch")
    return build_manifest(raw_summary, release_tag=RELEASE_TAG,
                          tag_commit_sha=TAG_COMMIT_SHA)


def main() -> int:
    request = Request(SUMMARY_URL, headers={"User-Agent": "MusteriAvcisiAI/0.1 boundary inventory"})
    with urlopen(request, timeout=30) as response:
        raw = response.read(5_000_001)
    if not raw or len(raw) > 5_000_000:
        raise RuntimeError("Pinned OSM boundary summary is empty or oversized")
    manifest = build(raw)
    output = OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(output)
    print("OSM_BOUNDARY_MANIFEST: "
          f"provinces={manifest['province_count']}; "
          f"districts={manifest['district_count']}; "
          f"release={RELEASE_TAG}; official_boundary=false; "
          f"summary_sha256={manifest['source']['summary_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
