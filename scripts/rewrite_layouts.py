#!/usr/bin/env python3
"""
Rewrite app/public/data/layouts/*.json so every photo URL is a clean,
public, token-free URL into the B2 bucket. Photos whose source object was
unreachable (Glacier / 404) are dropped, and cluster centroids/counts are
recomputed from the survivors.

The bucket is public (allPublic), so there is no download-authorization
token, no 7-day TTL, no refresh cron, and no credentials required — the URLs
never expire. (This replaced an earlier signed-URL design whose tokens kept
expiring and silently breaking the live demo.)

Inputs:
  scripts/url_map.json     — produced by migrate_to_b2.py
                             {source_url: b2_key | "dead"}
  app/public/data/layouts  — layouts, modified in place

Environment (both optional, defaults match the live bucket):
  B2_BUCKET        bucket name              (default: equipment-cluster-portfolio)
  B2_DOWNLOAD_URL  region download host     (default: https://f004.backblazeb2.com)

Idempotent: run as often as you like. Already-public B2 URLs are normalised
(any leftover ?Authorization=… is stripped); original source URLs are mapped
to public B2 URLs via url_map; dead/unknown photos are dropped.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS_DIR = ROOT / "app" / "public" / "data" / "layouts"
URL_MAP_PATH = ROOT / "scripts" / "url_map.json"

BUCKET = os.environ.get("B2_BUCKET", "equipment-cluster-portfolio")
DOWNLOAD_URL = os.environ.get("B2_DOWNLOAD_URL", "https://f004.backblazeb2.com").rstrip("/")


# ── URL helpers ───────────────────────────────────────────────────────────────

def public_url(key: str) -> str:
    return f"{DOWNLOAD_URL}/file/{BUCKET}/{key}"


def b2_key_from_url(url: str | None) -> str | None:
    """If `url` already points at our B2 bucket, return its object key
    (stripping any leftover ?Authorization=…). Otherwise return None."""
    marker = f"/file/{BUCKET}/"
    if not url or marker not in url:
        return None
    return url.split(marker, 1)[1].split("?", 1)[0]


def resolve_key(url: str | None, url_map: dict[str, str]) -> str | None:
    """Object key for a photo URL, or None if it should be dropped.

    Already-migrated B2 URL  → reuse its key (strip any token; steady state).
    Original source URL      → look up in url_map (first-time migration);
                               "dead" or unknown ⇒ drop."""
    existing = b2_key_from_url(url)
    if existing is not None:
        return existing
    mapped = url_map.get(url)
    return None if mapped in (None, "dead") else mapped


# ── Layout rewrite ────────────────────────────────────────────────────────────

def main() -> None:
    if not URL_MAP_PATH.exists():
        raise SystemExit(f"missing {URL_MAP_PATH} — run migrate_to_b2.py first")

    url_map: dict[str, str] = json.loads(URL_MAP_PATH.read_text())
    print(f"writing public URLs for {BUCKET} at {DOWNLOAD_URL} (no token, no expiry)")

    rewritten = dropped = layouts_touched = 0

    for path in sorted(LAYOUTS_DIR.glob("*.json")):
        layout = json.loads(path.read_text())
        photos = layout.get("photos", [])

        kept: list[dict] = []
        for p in photos:
            full_key = resolve_key(p.get("url"), url_map)
            tn_key   = resolve_key(p.get("thumbnail_url"), url_map)
            if full_key is None or tn_key is None:
                dropped += 1
                continue
            p["url"]           = public_url(full_key)
            p["thumbnail_url"] = public_url(tn_key)
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
            continue
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
