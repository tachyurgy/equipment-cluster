import { useMemo } from 'react'
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

export default function ClusterGrid({ layout, onSelectCluster }) {
  const { photos, clusters } = layout

  // No JS preloading: each card's <img> handles its own loading natively
  // (eager for the first rows, lazy below the fold). The old effect eagerly
  // pulled all 576 thumbnails + 36 full-res covers (~30MB) on mount, which is
  // what made the grid take forever to become usable.

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
      {cards.map(({ cluster, photos, mostRecent, oldest }, cardIdx) => (
        <button
          key={cluster.id}
          className={styles.cardOuter}
          style={{ '--c': cluster.color }}
          onClick={() => onSelectCluster({ cluster, photos })}
        >
          <div className={styles.ratio}>
            {mostRecent ? (
              <img
                src={mostRecent.thumbnail_url}
                alt=""
                className={styles.thumb}
                loading={cardIdx < 24 ? 'eager' : 'lazy'}
                fetchpriority={cardIdx < 8 ? 'high' : 'auto'}
                decoding="async"
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
          </div>
        </button>
      ))}
    </div>
  )
}
