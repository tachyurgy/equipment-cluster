#!/usr/bin/env python3
"""
Cluster each unit's DINOv2 embeddings by visual angle/view.
Uses created_at for true chronological ordering of inspections.

Output:
  app/public/data/units.json
  app/public/data/layouts/{unit_id}.json

Usage:
  python3 cluster.py
  python3 cluster.py --units 12107412 12107457
  python3 cluster.py --min-cluster 5
"""

import json
import argparse
import concurrent.futures
from datetime import datetime
from io import BytesIO
from pathlib import Path
from collections import defaultdict

import numpy as np
import umap
from sklearn.cluster import HDBSCAN
import torch
import open_clip
import requests
from PIL import Image

DEVICE = (
    "mps"  if torch.backends.mps.is_available() else
    "cuda" if torch.cuda.is_available() else
    "cpu"
)

ANGLE_LABELS = [
    "front of heavy equipment machine blade",
    "rear engine compartment of construction equipment",
    "left side of bulldozer or excavator",
    "right side of bulldozer or excavator",
    "operator cab interior controls dashboard",
    "undercarriage tracks or wheels of heavy equipment",
    "bucket arm boom of excavator",
    "damage rust dent scratch close-up",
    "overhead aerial top view of equipment",
    "equipment serial number identification plate",
    "tire or wheel of construction equipment",
    "engine or mechanical component close-up",
]

CLUSTER_COLORS = [
    "#60A5FA", "#34D399", "#F87171", "#FBBF24", "#A78BFA",
    "#FB923C", "#22D3EE", "#F472B6", "#A3E635", "#E879F9",
    "#2DD4BF", "#818CF8", "#FCA5A5", "#6EE7B7", "#FDE68A",
]

_clip_cache = {}


def fetch_image(url):
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGB")
    except Exception:
        return None


def clip_label_clusters(cluster_ids, embs, labels, photo_urls):
    """
    Label clusters by re-encoding representative images through CLIP
    (needed because DINOv2 is 768-dim, CLIP text is 512-dim — can't mix directly).
    photo_urls: list of thumbnail URLs aligned with embs rows.
    """
    if "model" not in _clip_cache:
        print("  Loading CLIP for labeling...")
        model, _, prep = open_clip.create_model_and_transforms("ViT-B-32", pretrained="openai")
        model = model.to(DEVICE).eval()
        tok = open_clip.get_tokenizer("ViT-B-32")
        with torch.no_grad():
            tokens = tok(ANGLE_LABELS).to(DEVICE)
            feats = model.encode_text(tokens)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            _clip_cache["text_feats"] = feats.cpu().float().numpy()
        _clip_cache["model"] = model
        _clip_cache["prep"]  = prep

    model = _clip_cache["model"]
    prep  = _clip_cache["prep"]
    tf    = _clip_cache["text_feats"]

    # For each cluster, pick 3 images closest to centroid in DINOv2 space,
    # encode through CLIP, average, then compare to text labels.
    names = {}
    for cid in cluster_ids:
        if cid == -1:
            names[cid] = "Other"
            continue
        mask = np.where(labels == cid)[0]
        centroid = embs[mask].mean(0)
        dists = np.linalg.norm(embs[mask] - centroid, axis=1)
        top_k = mask[np.argsort(dists)[:3]]
        urls = [photo_urls[i] for i in top_k]

        imgs = []
        for url in urls:
            img = fetch_image(url)
            if img: imgs.append(prep(img))

        if not imgs:
            names[cid] = "View"
            continue

        with torch.no_grad():
            batch = torch.stack(imgs).to(DEVICE)
            img_feats = model.encode_image(batch)
            img_feats = img_feats / img_feats.norm(dim=-1, keepdim=True)
            avg_feat = img_feats.mean(0)
            avg_feat = avg_feat / avg_feat.norm()
            sims = tf @ avg_feat.cpu().float().numpy()
        names[cid] = ANGLE_LABELS[int(sims.argmax())].title()

    # Deduplicate
    seen = {}
    for cid in sorted(k for k in names if k != -1):
        base = names[cid]
        if base in seen:
            seen[base] += 1
            names[cid] = f"{base} {seen[base] + 1}"
        else:
            seen[base] = 1
    return names


def parse_date(s):
    """Parse 'YYYY-MM-DD HH:MM:SS UTC' → datetime."""
    try:
        return datetime.strptime(s.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.min


def cluster_unit(unit_id, emb_data, min_cluster_size):
    photo_ids = list(emb_data.keys())
    embs = np.array([emb_data[pid]["embedding"] for pid in photo_ids], dtype=np.float32)
    n = len(photo_ids)
    print(f"  {n} photos")

    if n < 6:
        print("  Too few — skip")
        return None

    # UMAP
    nn = min(15, n - 1)
    coords = umap.UMAP(
        n_components=2, n_neighbors=nn, min_dist=0.05,
        metric="cosine", random_state=42, verbose=False,
    ).fit_transform(embs)

    xr = coords[:, 0].max() - coords[:, 0].min() or 1
    yr = coords[:, 1].max() - coords[:, 1].min() or 1
    coords_norm = np.column_stack([
        (coords[:, 0] - coords[:, 0].min()) / xr,
        (coords[:, 1] - coords[:, 1].min()) / yr,
    ])

    # HDBSCAN
    mc = min(min_cluster_size, max(3, n // 8))
    labels = HDBSCAN(min_cluster_size=mc, min_samples=3).fit_predict(coords)

    n_cl = len(set(labels)) - (1 if -1 in labels else 0)
    print(f"  {n_cl} clusters, {(labels==-1).sum()} noise")

    photo_urls = [emb_data[pid]["thumbnail_url"] for pid in photo_ids]
    cluster_names = clip_label_clusters(list(set(labels)), embs, labels, photo_urls)
    for cid, name in sorted(cluster_names.items()):
        if cid != -1:
            print(f"    {cid}: {(labels==cid).sum():4d}  {name}")

    # Build transaction list ordered by earliest created_at per txn
    txn_dates = defaultdict(list)
    for pid in photo_ids:
        info = emb_data[pid]
        txn_dates[info["txn_id"]].append(parse_date(info["created_at"]))

    all_txns = sorted(txn_dates.keys(), key=lambda t: min(txn_dates[t]))
    txn_order = {t: i for i, t in enumerate(all_txns)}

    def fmt_date(dt):
        return dt.strftime("%b %-d, %Y")

    transactions = [
        {
            "id":    txn,
            "order": i,
            "date":  fmt_date(min(txn_dates[txn])),
            "date_iso": min(txn_dates[txn]).strftime("%Y-%m-%d"),
        }
        for i, txn in enumerate(all_txns)
    ]

    photos = []
    for i, pid in enumerate(photo_ids):
        info = emb_data[pid]
        photos.append({
            "id":           pid,
            "txn_id":       info["txn_id"],
            "txn_order":    txn_order[info["txn_id"]],
            "created_at":   info["created_at"],
            "thumbnail_url": info["thumbnail_url"],
            "url":          info["url"],
            "x":            float(coords_norm[i, 0]),
            "y":            float(coords_norm[i, 1]),
            "cluster":      int(labels[i]),
        })

    clusters = []
    for cid in sorted(set(labels)):
        mask = labels == cid
        col = cid % len(CLUSTER_COLORS) if cid >= 0 else len(CLUSTER_COLORS) - 1
        clusters.append({
            "id":         int(cid),
            "label":      cluster_names[cid],
            "color":      CLUSTER_COLORS[col],
            "centroid_x": float(coords_norm[mask, 0].mean()),
            "centroid_y": float(coords_norm[mask, 1].mean()),
            "count":      int(mask.sum()),
        })

    return {
        "unit_id":          unit_id,
        "photo_count":      n,
        "transaction_count": len(all_txns),
        "date_range": {
            "start": transactions[0]["date"]  if transactions else "",
            "end":   transactions[-1]["date"] if transactions else "",
        },
        "transactions": transactions,
        "clusters":     clusters,
        "photos":       photos,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--units", nargs="*")
    parser.add_argument("--embeddings-dir", default="data/embeddings")
    parser.add_argument("--output-dir",     default="app/public/data")
    parser.add_argument("--min-cluster",    type=int, default=6)
    args = parser.parse_args()

    emb_dir  = Path(args.embeddings_dir)
    out_dir  = Path(args.output_dir)
    lay_dir  = out_dir / "layouts"
    lay_dir.mkdir(parents=True, exist_ok=True)

    emb_files = ([emb_dir / f"{u}.json" for u in args.units]
                 if args.units else sorted(emb_dir.glob("*.json")))

    units_meta = []
    for emb_file in emb_files:
        if not emb_file.exists():
            print(f"Missing: {emb_file}")
            continue
        uid = emb_file.stem
        print(f"\nUnit {uid}:")
        with open(emb_file) as f:
            emb_data = json.load(f)

        layout = cluster_unit(uid, emb_data, args.min_cluster)
        if not layout:
            continue

        with open(lay_dir / f"{uid}.json", "w") as f:
            json.dump(layout, f)

        real_cl = [c for c in layout["clusters"] if c["id"] != -1]
        units_meta.append({
            "id":               uid,
            "photo_count":      layout["photo_count"],
            "transaction_count": layout["transaction_count"],
            "cluster_count":    len(real_cl),
            "date_range":       layout["date_range"],
        })
        print(f"  → saved layout")

    with open(out_dir / "units.json", "w") as f:
        json.dump({"units": units_meta}, f)

    print(f"\n✓ {len(units_meta)} units written to {out_dir}")
    print("  cd app && npm install && npm run dev")


if __name__ == "__main__":
    main()
