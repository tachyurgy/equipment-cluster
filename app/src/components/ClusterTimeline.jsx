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

const PRELOAD_CONCURRENCY = 5

export default function ClusterTimeline({ cluster, photos }) {
  const [idx, setIdx] = useState(photos.length - 1)
  const [imgLoaded, setImgLoaded] = useState(false)

  const photo = photos[idx]

  // Once the initial image is loaded, preload the rest newest-first with 5 concurrent downloads.
  useEffect(() => {
    if (!imgLoaded) return
    let active = true

    const initialUrl = photos[photos.length - 1]?.url
    const rest = [...photos].reverse().map(p => p.url).filter(u => u !== initialUrl)
    let ptr = 0

    function next() {
      if (!active || ptr >= rest.length) return
      const url = rest[ptr++]
      const img = new Image()
      img.onload = img.onerror = next
      img.src = url
    }

    for (let i = 0; i < Math.min(PRELOAD_CONCURRENCY, rest.length); i++) next()

    return () => { active = false }
  }, [imgLoaded, photos])

  // Reset load state when photo changes
  useEffect(() => { setImgLoaded(false) }, [idx])

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
              {/* Thumbnail shows instantly (44KB) as a soft placeholder; the
                  full-res image fades in on top once it has downloaded. */}
              <img
                key={`thumb-${photo.id}`}
                src={photo.thumbnail_url}
                alt=""
                className={styles.mainImgThumb}
                aria-hidden="true"
              />
              <img
                key={photo.id}
                src={photo.url}
                alt=""
                className={`${styles.mainImg} ${imgLoaded ? styles.mainImgLoaded : ''}`}
                onLoad={() => setImgLoaded(true)}
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
