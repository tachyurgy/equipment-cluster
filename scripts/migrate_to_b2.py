#!/usr/bin/env python3
"""
Mirror every image referenced in the layout JSONs from the source CDN
into a Backblaze B2 bucket, then emit a URL map.

The pipeline:
  1. Walk app/public/data/layouts/*.json and collect every (full, thumbnail) URL.
  2. Concurrently HEAD each source URL — anything in Glacier or 404 is recorded
     as dead and skipped (the rewrite step will drop those photos from layouts).
  3. For each live URL, stream-download from S3 and upload to B2 under a
     stable key derived from the original path. Per-thread B2 upload URLs are
     refreshed on 503 / token-expiry per the B2 docs.
  4. Write scripts/url_map.json: {original_url: b2_url | "dead"}.

Resumable: a state file (scripts/.b2_migration_state.json) is updated after
every successful upload and replayed on restart.

Usage:
  export B2_KEY_ID=...  B2_KEY=...  B2_BUCKET=equipment-cluster-portfolio
  python3 scripts/migrate_to_b2.py --workers 32
  python3 scripts/migrate_to_b2.py --dry-run    # just classify alive/dead
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import requests

ROOT = Path(__file__).resolve().parent.parent
LAYOUTS_DIR = ROOT / "app" / "public" / "data" / "layouts"
STATE_PATH = ROOT / "scripts" / ".b2_migration_state.json"
URL_MAP_PATH = ROOT / "scripts" / "url_map.json"


# ── B2 API helpers ────────────────────────────────────────────────────────────

class B2:
    """Minimal B2 native-API client. One auth, per-thread upload URLs."""

    def __init__(self, key_id: str, key: str, bucket_name: str):
        self.key_id = key_id
        self.key = key
        self.bucket_name = bucket_name
        self.account_id: str = ""
        self.api_url: str = ""
        self.download_url: str = ""
        self.account_auth: str = ""
        self.bucket_id: str = ""
        self._upload_locals = threading.local()
        self._authorize()
        self._resolve_bucket()

    def _authorize(self) -> None:
        r = requests.get(
            "https://api.backblazeb2.com/b2api/v3/b2_authorize_account",
            auth=(self.key_id, self.key),
            timeout=20,
        )
        r.raise_for_status()
        d = r.json()
        self.account_id = d["accountId"]
        self.account_auth = d["authorizationToken"]
        api = d["apiInfo"]["storageApi"]
        self.api_url = api["apiUrl"]
        self.download_url = api["downloadUrl"]

    def _resolve_bucket(self) -> None:
        r = requests.post(
            f"{self.api_url}/b2api/v3/b2_list_buckets",
            headers={"Authorization": self.account_auth},
            json={"accountId": self.account_id, "bucketName": self.bucket_name},
            timeout=20,
        )
        r.raise_for_status()
        buckets = r.json()["buckets"]
        if not buckets:
            raise RuntimeError(f"bucket {self.bucket_name!r} not found")
        self.bucket_id = buckets[0]["bucketId"]

    def _get_upload_url(self) -> tuple[str, str]:
        r = requests.post(
            f"{self.api_url}/b2api/v3/b2_get_upload_url",
            headers={"Authorization": self.account_auth},
            json={"bucketId": self.bucket_id},
            timeout=20,
        )
        r.raise_for_status()
        d = r.json()
        return d["uploadUrl"], d["authorizationToken"]

    def _thread_upload_url(self, force: bool = False) -> tuple[str, str]:
        if force or not getattr(self._upload_locals, "url", None):
            self._upload_locals.url, self._upload_locals.token = self._get_upload_url()
        return self._upload_locals.url, self._upload_locals.token

    def upload(self, key: str, body: bytes, content_type: str) -> None:
        """Upload bytes under `key`. Idempotent — re-uploads overwrite by name.
        Refreshes the upload URL on every retry (B2 docs: a single upload URL
        is sticky to one pod, so transient failures often mean that pod is
        unhealthy and a fresh URL is required)."""
        sha1 = hashlib.sha1(body).hexdigest()
        for attempt in range(7):
            url, token = self._thread_upload_url(force=(attempt > 0))
            try:
                r = requests.post(
                    url,
                    headers={
                        "Authorization": token,
                        "X-Bz-File-Name": key,
                        "Content-Type": content_type,
                        "Content-Length": str(len(body)),
                        "X-Bz-Content-Sha1": sha1,
                    },
                    data=body,
                    timeout=120,
                )
                if r.status_code == 200:
                    return
                if r.status_code in (401, 408, 429, 500, 502, 503, 504):
                    time.sleep(min(30, 2 ** attempt))
                    continue
                r.raise_for_status()
            except requests.RequestException:
                time.sleep(min(30, 2 ** attempt))
        raise RuntimeError(f"upload failed for {key}")


# ── URL handling ──────────────────────────────────────────────────────────────

def url_to_key(u: str) -> str:
    """Hash the source URL into an opaque B2 key. Drops the client's
    transaction/photo IDs and path structure so the migrated URLs reveal
    nothing about the origin. Deterministic — same source URL always maps
    to the same key, so reruns are idempotent."""
    h = hashlib.sha256(u.encode()).hexdigest()
    return f"img/{h[:2]}/{h[2:4]}/{h}"


@dataclass
class State:
    done: dict[str, str] = field(default_factory=dict)   # url -> b2_url
    dead: dict[str, str] = field(default_factory=dict)   # url -> reason
    started_at: float = field(default_factory=time.time)

    @classmethod
    def load(cls) -> "State":
        if STATE_PATH.exists():
            d = json.loads(STATE_PATH.read_text())
            return cls(done=d.get("done", {}), dead=d.get("dead", {}),
                       started_at=d.get("started_at", time.time()))
        return cls()

    def save(self) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(
            {"done": self.done, "dead": self.dead, "started_at": self.started_at}
        ))


def collect_urls() -> list[str]:
    seen: set[str] = set()
    for f in sorted(LAYOUTS_DIR.glob("*.json")):
        layout = json.loads(f.read_text())
        for p in layout.get("photos", []):
            if u := p.get("url"):           seen.add(u)
            if u := p.get("thumbnail_url"): seen.add(u)
    return sorted(seen)


# ── Migration ─────────────────────────────────────────────────────────────────

def fetch_one(session: requests.Session, url: str) -> tuple[bytes, str] | tuple[None, str]:
    """Single GET with backoff. Glacier returns 403 InvalidObjectState on direct
    GET (permanent — body contains InvalidObjectState). A bare 403 from S3 with
    no such body is throttling/SlowDown — retry with exponential backoff. 5xx
    and 429 are also retried."""
    last_info = "unknown"
    for attempt in range(6):
        try:
            g = session.get(url, timeout=120)
            if g.status_code == 200:
                return g.content, g.headers.get("Content-Type", "application/octet-stream")
            # Permanent failures — distinguish by S3 error body so we don't waste
            # backoff cycles on objects that will never be reachable.
            head = g.content[:400]
            if g.status_code == 403 and b"InvalidObjectState" in head:
                return None, "glacier"
            if g.status_code == 403 and b"AccessDenied" in head:
                return None, "access_denied"   # private ACL — permanent
            if g.status_code == 404:
                return None, "get_404"
            # Transient — back off and retry. SlowDown is the real throttle signal.
            last_info = f"get_{g.status_code}"
            if g.status_code in (429, 500, 502, 503, 504) or b"SlowDown" in head:
                time.sleep(min(60, 2 ** attempt) + (attempt * 0.5))
                continue
            return None, last_info
        except requests.RequestException as e:
            last_info = f"net_{type(e).__name__}"
            time.sleep(min(60, 2 ** attempt))
    return None, last_info


def migrate(args) -> None:
    urls = collect_urls()
    state = State.load()

    pending = [u for u in urls if u not in state.done and u not in state.dead]
    print(f"discovered {len(urls)} unique URLs · "
          f"already done {len(state.done)} · "
          f"already dead {len(state.dead)} · "
          f"pending {len(pending)}")

    if args.dry_run:
        print("(dry run) — exiting before B2 auth/upload")
        return

    b2 = B2(os.environ["B2_KEY_ID"], os.environ["B2_KEY"], os.environ["B2_BUCKET"])
    print(f"B2 bucket {b2.bucket_name} resolved · download base {b2.download_url}")

    state_lock = threading.Lock()
    saved_at = [time.time()]
    counters = {"ok": 0, "dead": 0, "err": 0, "bytes": 0}
    start = time.time()

    tlocal = threading.local()

    def session() -> requests.Session:
        s = getattr(tlocal, "s", None)
        if s is None:
            s = requests.Session()
            s.headers["User-Agent"] = "equipment-cluster-migrate/1.0"
            # urllib3 default pool is 10 — too small for hot loops with many workers
            adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64)
            s.mount("https://", adapter)
            s.mount("http://", adapter)
            tlocal.s = s
        return s

    def worker(url: str) -> None:
        body, info = fetch_one(session(), url)
        if body is None:
            with state_lock:
                state.dead[url] = info
                counters["dead"] += 1
            return
        key = url_to_key(url)
        try:
            b2.upload(key, body, info)
        except Exception:                                       # noqa: BLE001
            # Don't poison the dead set — leave the URL pending so a re-run
            # picks it up. B2 upload errors are almost always transient.
            with state_lock:
                counters["err"] += 1
            return
        with state_lock:
            state.done[url] = key
            counters["ok"] += 1
            counters["bytes"] += len(body)

    print(f"migrating with {args.workers} workers...\n")
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(worker, u) for u in pending]
            for i, fut in enumerate(as_completed(futures), 1):
                fut.result()
                if i % 50 == 0 or i == len(futures):
                    elapsed = time.time() - start
                    rate = i / max(elapsed, 0.01)
                    mb = counters["bytes"] / 1e6
                    eta = (len(futures) - i) / max(rate, 0.01)
                    print(f"  [{i:>5}/{len(futures)}] "
                          f"ok={counters['ok']} dead={counters['dead']} err={counters['err']} "
                          f"· {mb:,.0f} MB · {rate:5.1f}/s · eta {eta/60:5.1f} min")
                if time.time() - saved_at[0] > 10:
                    with state_lock:
                        state.save()
                    saved_at[0] = time.time()
    finally:
        with state_lock:
            state.save()

    write_url_map(state)
    elapsed = time.time() - start
    print(f"\ndone in {elapsed/60:.1f} min · "
          f"alive {len(state.done)} · dead {len(state.dead)} · "
          f"{counters['bytes']/1e9:.2f} GB transferred")


def write_url_map(state: State) -> None:
    payload = {**state.done, **{k: "dead" for k in state.dead}}
    URL_MAP_PATH.write_text(json.dumps(payload, indent=0))
    print(f"wrote {URL_MAP_PATH.relative_to(ROOT)} ({len(payload)} entries)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=32)
    ap.add_argument("--dry-run", action="store_true", help="classify alive/dead without uploading")
    args = ap.parse_args()

    if not args.dry_run:
        for k in ("B2_KEY_ID", "B2_KEY", "B2_BUCKET"):
            if not os.environ.get(k):
                print(f"missing env var {k}", file=sys.stderr)
                sys.exit(1)

    migrate(args)


if __name__ == "__main__":
    main()
