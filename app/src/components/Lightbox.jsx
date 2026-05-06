import { useEffect, useCallback } from 'react'
import { useState } from 'react'
import styles from './Lightbox.module.css'

export default function Lightbox({ photos, startIndex, onClose }) {
  const [idx, setIdx] = useState(startIndex ?? 0)
  const photo = photos[idx]

  const prev = useCallback(() => setIdx(i => Math.max(0, i - 1)), [])
  const next = useCallback(() => setIdx(i => Math.min(photos.length - 1, i + 1)), [photos.length])

  useEffect(() => {
    const onKey = e => {
      if (e.key === 'ArrowLeft')  prev()
      if (e.key === 'ArrowRight') next()
      if (e.key === 'Escape')     onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [prev, next, onClose])

  if (!photo) return null

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.box} onClick={e => e.stopPropagation()}>
        {/* Toolbar */}
        <div className={styles.toolbar}>
          <span className={styles.counter}>{idx + 1} / {photos.length}</span>
          <a
            href={photo.url}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.openBtn}
          >
            Open full ↗
          </a>
          <button className={styles.closeBtn} onClick={onClose}>✕</button>
        </div>

        {/* Image */}
        <div className={styles.imgWrap}>
          {idx > 0 && (
            <button className={`${styles.nav} ${styles.navLeft}`} onClick={prev}>‹</button>
          )}
          <img
            key={photo.id}
            src={photo.url}
            alt=""
            className={styles.img}
          />
          {idx < photos.length - 1 && (
            <button className={`${styles.nav} ${styles.navRight}`} onClick={next}>›</button>
          )}
        </div>

        {/* Strip */}
        {photos.length > 1 && (
          <div className={styles.strip}>
            {photos.map((p, i) => (
              <button
                key={p.id}
                className={`${styles.stripThumb} ${i === idx ? styles.stripActive : ''}`}
                onClick={() => setIdx(i)}
              >
                <img src={p.thumbnail_url} alt="" loading="lazy" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
