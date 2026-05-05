#!/usr/bin/env python3
"""
Compute DINOv2 ViT-B/14 embeddings for each unit's photos.
Input:  photos2.json  (has url, thumbnail_url, created_at per photo)
Output: data/embeddings/{unit_id}.json

Samples up to --max-per-txn photos per transaction so all inspection
dates appear in the matrix view.

Usage:
  python3 embed.py                              # all units
  python3 embed.py --units 12107412 12107457    # specific units
  python3 embed.py --max-per-txn 8
"""

import json
import re
import argparse
import concurrent.futures
from io import BytesIO
from pathlib import Path
from collections import defaultdict

import torch
import timm
from PIL import Image
import requests
import numpy as np

DEVICE = (
    "mps"  if torch.backends.mps.is_available() else
    "cuda" if torch.cuda.is_available() else
    "cpu"
)


def load_dinov2():
    print(f"Loading DINOv2 ViT-B/14 on {DEVICE}...")
    model = timm.create_model("vit_base_patch14_dinov2", pretrained=True, num_classes=0)
    model = model.to(DEVICE).eval()
    cfg = timm.data.resolve_model_data_config(model)
    transforms = timm.data.create_transform(**cfg, is_training=False)
    print(f"  input size: {cfg['input_size']}  dim: 768")
    return model, transforms


def download_image(item):
    photo_id, txn_id, created_at, thumbnail_url, full_url = item
    try:
        r = requests.get(thumbnail_url, timeout=15)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content)).convert("RGB")
        return photo_id, txn_id, created_at, thumbnail_url, full_url, img
    except Exception:
        return photo_id, txn_id, created_at, thumbnail_url, full_url, None


def extract_txn_id(url):
    m = re.search(r"/transactions/(\d+)/", url)
    return m.group(1) if m else "unknown"


def sample_photos(photos, max_per_txn):
    """Group by transaction, sample evenly within each, return flat list.
    If max_per_txn is None, all photos are included."""
    by_txn = defaultdict(list)
    for photo_id, info in photos.items():
        txn = extract_txn_id(info["url"])
        by_txn[txn].append((photo_id, info))

    sampled = []
    for txn_id, txn_photos in by_txn.items():
        n = len(txn_photos)
        if max_per_txn is None or n <= max_per_txn:
            chosen = txn_photos
        else:
            step = n / max_per_txn
            chosen = [txn_photos[int(i * step)] for i in range(max_per_txn)]

        for photo_id, info in chosen:
            sampled.append((
                photo_id,
                txn_id,
                info.get("created_at", ""),
                info["thumbnail_url"],
                info["url"],
            ))

    return sampled


def embed_unit(unit_id, photos, model, transforms, max_per_txn, workers, batch_size):
    sampled = sample_photos(photos, max_per_txn)
    n_txns = len(set(s[1] for s in sampled))
    print(f"  {len(photos)} photos / {n_txns} txns → sampling {len(sampled)}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        raw = list(ex.map(download_image, sampled))

    ok = [r for r in raw if r[5] is not None]
    if len(raw) - len(ok):
        print(f"  {len(raw)-len(ok)} downloads failed")

    embeddings = {}
    with torch.no_grad():
        for i in range(0, len(ok), batch_size):
            batch = ok[i : i + batch_size]
            tensors = torch.stack([transforms(item[5]) for item in batch]).to(DEVICE)
            feats = model(tensors)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            feats_np = feats.cpu().float().numpy()

            for j, (photo_id, txn_id, created_at, tn_url, full_url, _) in enumerate(batch):
                embeddings[photo_id] = {
                    "txn_id":       txn_id,
                    "created_at":   created_at,
                    "thumbnail_url": tn_url,
                    "url":          full_url,
                    "embedding":    feats_np[j].tolist(),
                }

    return embeddings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--units", nargs="*")
    parser.add_argument("--max-per-txn", type=int, default=None)
    parser.add_argument("--batch-size",  type=int, default=32)
    parser.add_argument("--workers",     type=int, default=40)
    parser.add_argument("--input",       default="photos2.json")
    parser.add_argument("--output-dir",  default="data/embeddings")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(args.input) as f:
        data = json.load(f)

    unit_ids = args.units if args.units else list(data.keys())
    print(f"Processing {len(unit_ids)} units  (max {args.max_per_txn} photos/txn)\n")

    model, transforms = load_dinov2()
    print()

    for i, uid in enumerate(unit_ids):
        out_path = out_dir / f"{uid}.json"
        if out_path.exists():
            print(f"[{i+1}/{len(unit_ids)}] Unit {uid}: already done, skipping")
            continue
        if uid not in data:
            print(f"[{i+1}/{len(unit_ids)}] Unit {uid}: not in data")
            continue

        print(f"[{i+1}/{len(unit_ids)}] Unit {uid}:")
        embs = embed_unit(uid, data[uid], model, transforms,
                          args.max_per_txn, args.workers, args.batch_size)
        with open(out_path, "w") as f:
            json.dump(embs, f)
        print(f"  saved {len(embs)} embeddings\n")

    print("Done! Next: python3 cluster.py")


if __name__ == "__main__":
    main()
