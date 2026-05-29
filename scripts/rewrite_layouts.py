#!/usr/bin/env python3
"""
Rewrite app/public/data/layouts/*.json so every photo URL points at the
private B2 bucket via a signed (download-authorized) URL. Photos whose
source object was unreachable (Glacier / 404) are dropped, and cluster
centroids/counts are recomputed from the survivors.

Inputs:
  scripts/url_map.json     — produced by migrate_to_b2.py
                             {source_url: b2_key | "dead"}
  app/public/data/layouts  — original layouts (modified in place)

Environment:
  B2_KEY_ID, B2_KEY, B2_BUCKET — same credentials as migrate_to_b2.py

B2 download-authorization tokens are valid for at most 7 days
(`validDurationInSeconds=604800`). This script must be re-run before then —
a GitHub Actions cron in .github/workflows/refresh-tokens.yml automates it.

Idempotent: run as often as you like; each run mints a fresh token and
re-signs whatever keys the layouts already hold. The first run migrates
original source URLs via url_map; every run after that re-signs the B2 URLs
in place (url_map is only consulted for URLs not yet pointing at the bucket).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS_DIR = ROOT / "app" / "public" / "data" / "layouts"
URL_MAP_PATH = ROOT / "scripts" / "url_map.json"

PREFIX = "img/"                 # everything under this gets a single auth token
TOKEN_TTL_SECONDS = 7 * 24 * 3600  # B2 max


# ── B2 download-auth ──────────────────────────────────────────────────────────

def get_download_auth(key_id: str, key: str, bucket: str) -> tuple[str, str, str]:
    """Returns (download_url, bucket_name, auth_token).
    The token is valid for any file under PREFIX for TOKEN_TTL_SECONDS."""
    auth = requests.get(
        "https://api.backblazeb2.com/b2api/v3/b2_authorize_account",
        auth=(key_id, key), timeout=20,
    ).json()
    api_url = auth["apiInfo"]["storageApi"]["apiUrl"]
    download_url = auth["apiInfo"]["storageApi"]["downloadUrl"]
    account_token = auth["authorizationToken"]
    account_id = auth["accountId"]

    bucket_resp = requests.post(
        f"{api_url}/b2api/v3/b2_list_buckets",
        headers={"Authorization": account_token},
        json={"accountId": account_id, "bucketName": bucket},
        timeout=20,
    ).json()
    bucket_id = bucket_resp["buckets"][0]["bucketId"]

    auth_resp = requests.post(
        f"{api_url}/b2api/v3/b2_get_download_authorization",
        headers={"Authorization": account_token},
        json={
            "bucketId": bucket_id,
            "fileNamePrefix": PREFIX,
            "validDurationInSeconds": TOKEN_TTL_SECONDS,
        },
        timeout=20,
    ).json()
    return download_url, bucket, auth_resp["authorizationToken"]


def signed_url(download_url: str, bucket: str, key: str, token: str) -> str:
    return f"{download_url}/file/{bucket}/{key}?Authorization={token}"


def b2_key_from_url(url: str | None, bucket: str) -> str | None:
    """If `url` already points at our B2 bucket, return its object key
    (stripping any stale ?Authorization=…). Otherwise return None.

    This is what makes the refresh idempotent against already-migrated
    layouts: once a layout holds B2 URLs, every run just re-signs the keys
    in place with a fresh token instead of looking them up in url_map —
    which is keyed by the *original* source URLs and would miss every one,
    silently dropping the entire demo."""
    marker = f"/file/{bucket}/"
    if not url or marker not in url:
        return None
    return url.split(marker, 1)[1].split("?", 1)[0]


def resolve_key(url: str | None, bucket: str, url_map: dict[str, str]) -> str | None:
    """Object key for a photo URL, or None if it should be dropped.

    Already-migrated B2 URL  → re-sign in place (steady-state / cron path).
    Original source URL      → look up in url_map (first-time migration);
                               "dead" or unknown ⇒ drop."""
    existing = b2_key_from_url(url, bucket)
    if existing is not None:
        return existing
    mapped = url_map.get(url)
    return None if mapped in (None, "dead") else mapped


# ── Layout rewrite ────────────────────────────────────────────────────────────

def main() -> None:
    if not URL_MAP_PATH.exists():
        raise SystemExit(f"missing {URL_MAP_PATH} — run migrate_to_b2.py first")

    for k in ("B2_KEY_ID", "B2_KEY", "B2_BUCKET"):
        if not os.environ.get(k):
            print(f"missing env var {k}", file=sys.stderr)
            sys.exit(1)

    url_map: dict[str, str] = json.loads(URL_MAP_PATH.read_text())
    download_url, bucket, token = get_download_auth(
        os.environ["B2_KEY_ID"], os.environ["B2_KEY"], os.environ["B2_BUCKET"]
    )
    print(f"minted download token for {bucket} (valid 7 days)")

    rewritten = dropped = layouts_touched = 0

    for path in sorted(LAYOUTS_DIR.glob("*.json")):
        layout = json.loads(path.read_text())
        photos = layout.get("photos", [])

        kept: list[dict] = []
        for p in photos:
            full_key = resolve_key(p.get("url"), bucket, url_map)
            tn_key   = resolve_key(p.get("thumbnail_url"), bucket, url_map)
            if full_key is None or tn_key is None:
                dropped += 1
                continue
            p["url"]           = signed_url(download_url, bucket, full_key, token)
            p["thumbnail_url"] = signed_url(download_url, bucket, tn_key, token)
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
