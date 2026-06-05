import { useState, useEffect, useCallback } from 'react'
import styles from './ClusterTimeline.module.css'

function parseDate(str) {
  if (!str) return null
  try { return new Date(str.replace(' UTC', 'Z')) } catch { return null }
}

function fmtFull(str) {
  const d = parseDate(str)
  if (!d) return ''
  return d.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' })
}

// Browsers cap ~6 concurrent connections per host (all photos are on the same
// B2 host), so 6 in-flight saturates the pipe; the rest queue automatically.
const PRELOAD_CONCURRENCY = 6

export default function ClusterTimeline({ cluster, photos }) {
  const [idx, setIdx] = useState(photos.length - 1)
  const [loaded, setLoaded] = useState(() => new Set())

  const photo = photos[idx]
  const isLoaded = photo ? loaded.has(photo.url) : false

  const markLoaded = useCallback((url) => {
    setLoaded(prev => {
      if (prev.has(url)) return prev
      const n = new Set(prev)
      n.add(url)
      return n
    })
  }, [])

  // Eagerly download EVERY full-res photo for this angle the moment it opens,
  // newest-first (the direction the user clicks). Once cached, navigating shows
  // full-res instantly with no thumbnail flash. Runs once per cluster.
  useEffect(() => {
    let active = true
    const urls = [...photos].reverse().map(p => p.url)
    let ptr = 0

    function pump() {
      if (!active || ptr >= urls.length) return
      const url = urls[ptr++]
      const img = new Image()
      img.onload = img.onerror = () => { if (active) { markLoaded(url); pump() } }
      img.src = url
    }

    for (let i = 0; i < Math.min(PRELOAD_CONCURRENCY, urls.length); i++) pump()

    return () => { active = false }
  }, [photos, markLoaded])

  const prev = useCallback(() => setIdx(i => Math.max(0, i - 1)), [])
  const next = useCallback(() => setIdx(i => Math.min(photos.length - 1, i + 1)), [photos.length])

  useEffect(() => {
    const onKey = e => {
      if (e.key === 'ArrowLeft') prev()
      if (e.key === 'ArrowRight') next()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [prev, next])

  return (
    <div className={styles.container}>

      {/* ── Main photo ── */}
      <div className={styles.mainArea}>
        {idx > 0 && (
          <button className={`${styles.nav} ${styles.navLeft}`} onClick={prev}>‹</button>
        )}

        <div className={styles.photoWrap}>
          {photo && (
            <>
              {/* Thumbnail placeholder only while the full-res isn't cached yet.
                  Once preloaded, we skip it entirely so there's no thumbnail flash. */}
              {!isLoaded && (
                <img
                  key={`thumb-${photo.id}`}
                  src={photo.thumbnail_url}
                  alt=""
                  className={styles.mainImgThumb}
                  aria-hidden="true"
                />
              )}
              <img
                key={photo.id}
                src={photo.url}
                alt=""
                className={`${styles.mainImg} ${isLoaded ? styles.mainImgLoaded : ''}`}
                onLoad={() => markLoaded(photo.url)}
              />
            </>
          )}
        </div>

        {idx < photos.length - 1 && (
          <button className={`${styles.nav} ${styles.navRight}`} onClick={next}>›</button>
        )}

        {/* Date overlay */}
        {photo && (
          <div className={styles.dateOverlay}>
            <span className={styles.dateMain}>{fmtFull(photo.created_at)}</span>
            <div className={styles.dateMeta}>
              <span className={styles.inspBadge} style={{ '--c': cluster.color }}>
                Inspection {idx + 1} of {photos.length}
              </span>
              {photo.url && (
                <a href={photo.url} target="_blank" rel="noopener noreferrer" className={styles.openLink}>
                  Full res ↗
                </a>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Thumbnail strip ── */}
      <div className={styles.strip}>
        {photos.map((p, i) => (
          <button
            key={p.id}
            className={`${styles.stripItem} ${i === idx ? styles.stripActive : ''}`}
            style={{ '--c': cluster.color }}
            onClick={() => setIdx(i)}
            title={fmtFull(p.created_at)}
          >
            <img src={p.thumbnail_url} alt="" className={styles.stripThumb} loading="lazy" />
          </button>
        ))}
      </div>
    </div>
  )
}
