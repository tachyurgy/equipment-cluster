import { useMemo, useEffect } from 'react'
import styles from './ClusterGrid.module.css'

function parseDate(str) {
  if (!str) return null
  try {
    return new Date(str.replace(' UTC', 'Z'))
  } catch {
    return null
  }
}

function fmtShort(str) {
  const d = parseDate(str)
  if (!d) return ''
  return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

const THUMB_CONCURRENCY = 6

export default function ClusterGrid({ layout, onSelectCluster }) {
  const { photos, clusters } = layout

  // Preload all thumbnails + the cover full-res for each cluster
  useEffect(() => {
    let active = true

    function makeQueue(urls, concurrency) {
      let ptr = 0
      function next() {
        if (!active || ptr >= urls.length) return
        const img = new Image()
        img.onload = img.onerror = next
        img.src = urls[ptr++]
      }
      for (let i = 0; i < Math.min(concurrency, urls.length); i++) next()
    }

    // All thumbnails — 6 concurrent
    makeQueue(photos.map(p => p.thumbnail_url), THUMB_CONCURRENCY)

    // Full-res cover image (most recent) for each cluster — 2 concurrent so
    // they don't fight with thumbnails but are ready when user drills in
    const coverUrls = clusters
      .filter(c => c.id !== -1)
      .map(c => {
        const clusterPhotos = photos.filter(p => p.cluster === c.id)
        return clusterPhotos[clusterPhotos.length - 1]?.url
      })
      .filter(Boolean)
    makeQueue(coverUrls, 2)

    return () => { active = false }
  }, [photos, clusters])

  const cards = useMemo(() => {
    // Sort by UMAP centroid position so visually similar angles appear adjacent.
    // Bin the y-axis into rows, then sort left-to-right within each row.
    const real = clusters.filter(c => c.id !== -1)
    const ROW_BUCKETS = Math.max(3, Math.ceil(Math.sqrt(real.length / 2)))
    return real
      .sort((a, b) => {
        const aRow = Math.floor(a.centroid_y * ROW_BUCKETS)
        const bRow = Math.floor(b.centroid_y * ROW_BUCKETS)
        if (aRow !== bRow) return aRow - bRow
        return a.centroid_x - b.centroid_x
      })
      .map(cluster => {
        const clusterPhotos = photos
          .filter(p => p.cluster === cluster.id)
          .sort((a, b) => parseDate(a.created_at) - parseDate(b.created_at))
        const mostRecent = clusterPhotos[clusterPhotos.length - 1]
        const oldest = clusterPhotos[0]
        return { cluster, photos: clusterPhotos, mostRecent, oldest }
      })
  }, [photos, clusters])

  return (
    <div className={styles.grid}>
      {cards.map(({ cluster, photos, mostRecent, oldest }) => (
        <button
          key={cluster.id}
          className={styles.cardOuter}
          style={{ '--c': cluster.color }}
          onClick={() => onSelectCluster({ cluster, photos })}
        >
          {mostRecent ? (
            <img
              src={mostRecent.thumbnail_url}
              alt=""
              className={styles.thumb}
              loading="lazy"
            />
          ) : (
            <div className={styles.noPhoto} />
          )}

          <div className={styles.colorDot} />

          <div className={styles.hoverOverlay}>
            <div className={styles.hoverInfo}>
              <span className={styles.hoverCount}>{photos.length} photos</span>
              {oldest && mostRecent && oldest.id !== mostRecent.id && (
                <span className={styles.hoverDates}>
                  {fmtShort(oldest.created_at)} – {fmtShort(mostRecent.created_at)}
                </span>
              )}
            </div>
          </div>
        </button>
      ))}
    </div>
  )
}
