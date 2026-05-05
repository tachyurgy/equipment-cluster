# Equipment Cluster — visual history, by angle

> A pipeline that takes 20,000+ unstructured inspection photos of heavy equipment
> and reorganises them into per-machine "visual histories" you can scan in
> seconds. Built for an equipment-rental client; the public demo runs on
> sanitised metadata.

**Live demo:** [tachyurgy.github.io/equipment-cluster](https://tachyurgy.github.io/equipment-cluster/)

---

## The ask

The client owns a fleet of construction machines (excavators, skid steers,
bulldozers, etc.). Every time a unit goes out for rent and comes back, the
yard crew walks around it and snaps inspection photos — front, rear, both
sides, undercarriage, dashboard, damage close-ups. Over a unit's lifetime
that's hundreds of photos across dozens of inspections.

The photos were piling up in S3 with **zero structure**: no consistent angle
labels, no ordering inside a session, no easy way to compare "left side, last
month" vs. "left side, this month." Looking up a single piece of equipment's
visual history meant scrolling through a flat grid and squinting.

The brief was: *give us a way to see one unit's full history at a glance,
with photos grouped by what they actually show.*

## The solution, end to end

```
                      ┌──────────────────────────┐
                      │    photos.json           │
                      │    (per unit, per txn)   │
                      └────────────┬─────────────┘
                                   │
            ┌──────────────────────▼──────────────────────┐
            │   embed.py        DINOv2 ViT-B/14           │
            │                   768-dim self-supervised   │
            │                   feature per image         │
            └──────────────────────┬──────────────────────┘
                                   │
                                   ▼
                      ┌──────────────────────────┐
                      │  data/embeddings/{id}.json│
                      └────────────┬─────────────┘
                                   │
            ┌──────────────────────▼──────────────────────┐
            │   cluster.py      UMAP → 2-D layout         │
            │                   HDBSCAN → angle clusters  │
            │                   CLIP → zero-shot labels   │
            └──────────────────────┬──────────────────────┘
                                   │
                                   ▼
                      ┌──────────────────────────┐
                      │  app/public/data/layouts │
                      └────────────┬─────────────┘
                                   │
            ┌──────────────────────▼──────────────────────┐
            │   app/   React + Vite                        │
            │          ScatterView · ClusterGrid · Timeline│
            └─────────────────────────────────────────────┘
```

Three stages of ML, one viewer. Each stage is its own script and writes a
plain-JSON artifact, so any stage can be re-run independently.

### Stage 1 — Self-supervised features (`embed.py`)

For each unit, pull the photo metadata, download thumbnails in parallel, and
push them through **DINOv2 ViT-B/14** to get a 768-dim feature per image.
DINOv2 is the right backbone here: it's trained without labels to be
*invariant to lighting and pose but sensitive to viewpoint and structure* —
which is exactly what "this is the same machine, photographed from the same
angle, on a different day" means.

Key implementation details worth pointing out:

- **Apple Silicon-aware device selection** (MPS → CUDA → CPU fallback), so
  it just works on a laptop or a server.
- **Per-transaction sampling** with `--max-per-txn` so a single 200-photo
  inspection can't drown out 50 other inspections — keeps the timeline
  legible without losing temporal coverage.
- **Concurrent thumbnail download** (`ThreadPoolExecutor`, 40 workers by
  default) overlapped with the GPU forward pass.

### Stage 2 — Clustering (`cluster.py`)

For each unit independently:

1. **UMAP** the 768-dim DINOv2 features down to 2-D, cosine distance,
   `n_neighbors=15`, `min_dist=0.05`. The 2-D coords are what the viewer
   actually plots, so the embedding has to be visually legible, not just
   numerically tidy.
2. **HDBSCAN** on the *2-D* coords (not the 768-D originals — UMAP already
   did the heavy lifting and HDBSCAN works better in low dim). `min_cluster_size`
   adapts to unit size: `min(6, n // 8)`. Outliers go to cluster `-1`
   ("Other") and are rendered greyed-out.
3. **CLIP zero-shot labels** for each cluster (described below).

Output is one `app/public/data/layouts/{unit_id}.json` per unit, plus a
top-level `units.json` index. Total artifact size is ~10 MB for ~40 units —
small enough that the viewer ships them as static files.

### Stage 3 — Cross-modal cluster labels (`cluster.py`, `clip_label_clusters`)

This is the part I'm proudest of. DINOv2 is great for similarity but doesn't
speak text. CLIP speaks text but its image encoder is a worse feature
extractor for this domain. So:

- Cluster in DINOv2 space (best similarity).
- For each cluster, pick the 3 images closest to the centroid in DINOv2
  space.
- Encode *those representative images* through **CLIP ViT-B/32** and average
  their image features.
- Compare against pre-computed CLIP text embeddings of a fixed vocabulary
  ("front of heavy equipment machine blade", "rear engine compartment",
  "operator cab interior controls dashboard", …).
- The top-similarity caption becomes the cluster label.

Net effect: each cluster gets a human-readable name like *"Operator Cab
Interior Controls Dashboard"* without anyone hand-labeling a single image.
And because the labels are fixed strings, they collapse cleanly across units —
"Left Side of Bulldozer" means the same thing for every machine.

### Stage 4 — The viewer (`app/`)

A small, fast React app (Vite, no UI library, ~150 kB JS):

- **Scatter view** — every photo as a dot in the UMAP plane, hover for
  thumbnail, click for full-res. The dot positions come straight from
  Stage 2.
- **Cluster grid** — collapses the scatter into one tile per angle, with
  a representative thumbnail. This is the "give me the gist" view.
- **Timeline** — for any selected angle, lay out one column per inspection
  date so you can see the **same view of the same machine** evolve over
  time. This is the headline feature — it turns "find me how the left side
  has changed over six months" from a 30-minute scroll into a glance.

## Scale and stats

The full pipeline ran across the client's complete fleet:

|                          |        |
|--------------------------|--------|
| Units processed          | 40     |
| Inspections              | 898    |
| Photos                   | 20,743 |
| Angle-clusters discovered| 1,158  |
| Median clusters per unit | ~28    |
| Layout JSON, all units   | 9.9 MB |

End-to-end pipeline time on an M-series MacBook (MPS): roughly 25 minutes for
all 40 units, dominated by image download from the source CDN — the actual
DINOv2 forward pass is a few seconds per unit.

The **public demo** ships a curated 2-unit subset (2,088 photos, 138 clusters)
mirrored to a Backblaze B2 bucket so the live site has no dependency on the
client's infrastructure. A GitHub Actions cron re-mints the 7-day B2 download
authorization tokens every 6 days and pushes the fresh signed URLs.

## Tech stack

**Python (the heavy lifting)**
- [PyTorch](https://pytorch.org/) (MPS / CUDA / CPU)
- [`timm`](https://huggingface.co/docs/timm) — DINOv2 ViT-B/14 backbone
- [`open_clip`](https://github.com/mlfoundations/open_clip) — CLIP ViT-B/32 for labels
- [`umap-learn`](https://umap-learn.readthedocs.io/) — dimensionality reduction
- [`scikit-learn`](https://scikit-learn.org/) `HDBSCAN` — density clustering
- `requests` + `concurrent.futures` for parallel I/O
- `b2sdk`-free B2 client written against the native HTTP API (`scripts/migrate_to_b2.py`)

**Frontend**
- [React 18](https://react.dev/) + [Vite 5](https://vitejs.dev/)
- CSS modules, no UI library
- Plain `<canvas>` for the scatter view (60 fps with 1500 photos in frame)

**Hosting**
- GitHub Pages for the app
- Backblaze B2 for the migrated images (mirror of the client's S3)

## Running it yourself

```bash
# 1. embed
python3 embed.py --input photos.json --output-dir data/embeddings

# 2. cluster + label + lay out
python3 cluster.py

# 3. view
cd app && npm install && npm run dev
```

`photos.json` is the only thing not included — it's the client's metadata
(IDs, timestamps, source URLs), and it's what the pipeline expects as input.
Drop in any equivalent file with `{unit_id: {photo_id: {url, thumbnail_url,
created_at}}}` and everything downstream works.

## Repository layout

```
.
├── embed.py                  # Stage 1 — DINOv2 features
├── cluster.py                # Stages 2 + 3 — UMAP, HDBSCAN, CLIP labels
├── scripts/
│   ├── migrate_to_b2.py      # Mirror source-CDN images to Backblaze B2
│   └── rewrite_layouts.py    # Swap CDN URLs in layout JSONs to mirrored ones
├── data/embeddings/          # (gitignored — regenerate from embed.py)
├── app/                      # React viewer (Vite, GitHub Pages target)
│   ├── src/components/       # ScatterView, ClusterGrid, ClusterTimeline, …
│   └── public/data/          # units.json + layouts/*.json
└── archive/                  # earlier iterations kept locally, not published
```

## Engineering notes / decisions worth flagging

- **Why DINOv2 instead of CLIP for the embedding?** CLIP's image encoder is
  optimised for matching text, which makes it leaky on viewpoint — two
  pictures of "an excavator" cluster together regardless of angle. DINOv2 is
  pure self-supervised, so it preserves viewpoint signal much better. Tested
  both side-by-side; DINOv2 was visibly cleaner.
- **Why UMAP before HDBSCAN, not on raw 768-D?** HDBSCAN's density estimate
  in 768-D is dominated by the curse of dimensionality. UMAP gives you a 2-D
  manifold that's both clusterable and renderable — one structure, two uses.
- **Per-thread B2 upload URLs.** The B2 native API gives one upload URL per
  call, valid until it 503s. The migration script (`scripts/migrate_to_b2.py`)
  uses `threading.local()` to hold one URL per worker and refreshes on
  failure — a small detail that gives a ~10× throughput improvement over
  re-fetching per upload.
- **Resumable migration.** The migration writes a state file every 10 s and
  on shutdown. If it dies, restarting picks up exactly where it left off —
  no double-uploads, no missed files.
- **Dead-photo handling.** A non-trivial slice of the source S3 objects are
  unreachable — Glacier Deep Archive (returns `403 InvalidObjectState` on a
  GET), private ACLs (`403 AccessDenied`), or 404s. The migration script
  classifies each by inspecting the S3 error body, and the rewrite step drops
  those photos from the layouts (and recomputes cluster centroids) so the
  viewer never shows a broken image. A single GET per URL doubles as the
  reachability check — no separate HEAD round trip.

## Where else this approach fits

The pipeline is generic: anything that produces a stream of photos which
*should* group by viewpoint or visual category, but currently doesn't, is a
candidate. A few directions this naturally extends to:

- **Insurance claims and damage photography** — group submitted photos by
  what they show (front bumper, rear quarter panel, interior, undercarriage)
  so adjusters can see all "rear bumper" shots side-by-side instead of a
  random scroll. The same DINOv2 + UMAP + HDBSCAN structure works as-is.
- **Real-estate listings and property inspections** — collapse 200 listing
  photos into kitchen / living room / bedroom / exterior / landscaping
  groups for a clean gallery, automatically. Useful for portals that
  ingest photos from many agents with no consistent structure.
- **Construction site progress monitoring** — same machine, same site,
  shot weekly. The timeline view is already the right interface for
  "show me the foundation through time."
- **Quality control on assembly lines** — every unit photographed on its
  way out; cluster by what part is in frame and surface drift over a
  shift, a day, a month.
- **Medical imaging triage (with proper safeguards)** — same idea: group by
  view (sagittal vs. coronal vs. axial; or organ-of-interest); the
  radiology workflow is exactly the "all of view X across this patient's
  history" problem the timeline view solves here.
- **Wildlife camera traps and ecological surveys** — bin millions of
  motion-triggered frames by what's actually in them (deer / coyote /
  empty / human) without hand-labeling, then check time series.
- **Retail visual merchandising** — store-level photo audits: did every
  shelf get the new planogram? Group photos by aisle and shelf, compare
  across stores.
- **E-commerce listing dedup** — photos uploaded by multiple sellers for
  the same product cluster together; surface canonical product views and
  flag near-duplicates.

The expensive part is the foundation model (DINOv2). Everything downstream
of it — the dimensionality reduction, the density clustering, the CLIP
labelling, the React viewer — is light, fast, and reusable. Swapping in a
domain-specific embedding (medical, satellite, etc.) is the only change
needed to retarget.

## Data privacy

The repository contains pipeline code, sanitised layout JSONs, and image
URLs that point at the project's own Backblaze mirror. It does **not**
contain the client's source `photos.json`, the original raw photos, the
client's S3 URLs, or any account / customer data. The 768-dim DINOv2
embeddings (`data/embeddings/`) are gitignored because they're large and
trivially regeneratable.

## License

MIT — see [LICENSE](LICENSE).
