#!/usr/bin/env python3
"""
Rewrite app/public/data/layouts/*.json so every photo URL points at the
migrated B2 mirror, dropping any photo whose source object was unreachable
(Glacier or 404). Cluster centroids and counts are recomputed from the
surviving photos.

Inputs:
  scripts/url_map.json     — produced by migrate_to_b2.py
  app/public/data/layouts  — original layouts (modified in place)

Idempotent. Safe to re-run after additional migration passes.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS_DIR = ROOT / "app" / "public" / "data" / "layouts"
URL_MAP_PATH = ROOT / "scripts" / "url_map.json"


def main() -> None:
    if not URL_MAP_PATH.exists():
        raise SystemExit(f"missing {URL_MAP_PATH} — run migrate_to_b2.py first")
    url_map: dict[str, str] = json.loads(URL_MAP_PATH.read_text())

    rewritten = dropped = 0
    layouts_touched = 0

    for path in sorted(LAYOUTS_DIR.glob("*.json")):
        layout = json.loads(path.read_text())
        photos = layout.get("photos", [])

        kept: list[dict] = []
        for p in photos:
            new_url = url_map.get(p.get("url"))
            new_tn = url_map.get(p.get("thumbnail_url"))
            if new_url in (None, "dead") or new_tn in (None, "dead"):
                dropped += 1
                continue
            p["url"] = new_url
            p["thumbnail_url"] = new_tn
            kept.append(p)
            rewritten += 1

        layout["photos"] = kept
        layout["photo_count"] = len(kept)
        layout["clusters"] = recompute_clusters(layout.get("clusters", []), kept)
        path.write_text(json.dumps(layout))
        layouts_touched += 1

    print(f"rewrote {rewritten} URLs · dropped {dropped} dead photos · "
          f"{layouts_touched} layouts updated")


def recompute_clusters(clusters: list[dict], photos: list[dict]) -> list[dict]:
    """Recompute centroid + count for each cluster from surviving photos."""
    by_cluster: dict[int, list[dict]] = {}
    for p in photos:
        by_cluster.setdefault(p["cluster"], []).append(p)

    out = []
    for c in clusters:
        members = by_cluster.get(c["id"], [])
        if not members:
            continue                                       # cluster vanished
        xs = [m["x"] for m in members]
        ys = [m["y"] for m in members]
        c = {**c,
             "centroid_x": sum(xs) / len(xs),
             "centroid_y": sum(ys) / len(ys),
             "count":      len(members)}
        out.append(c)
    return out


if __name__ == "__main__":
    main()
