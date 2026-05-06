import { useState, useMemo, useRef, useCallback } from 'react'
import Lightbox from './Lightbox'
import styles from './MatrixView.module.css'

export default function MatrixView({ layout }) {
  const { photos, clusters, transactions } = layout
  const [lightbox, setLightbox] = useState(null) // { photos, index }

  // Clusters sorted by count desc (excluding noise)
  const rows = useMemo(() =>
    clusters
      .filter(c => c.id !== -1)
      .sort((a, b) => b.count - a.count),
    [clusters]
  )

  // Transactions sorted chronologically
  const cols = useMemo(() =>
    [...transactions].sort((a, b) => a.order - b.order),
    [transactions]
  )

  // Build cell map: clusterid__txnid → [photos]
  const cellMap = useMemo(() => {
    const m = {}
    photos.forEach(p => {
      if (p.cluster === -1) return
      const key = `${p.cluster}__${p.txn_id}`
      if (!m[key]) m[key] = []
      m[key].push(p)
    })
    return m
  }, [photos])

  const openLightbox = useCallback((cellPhotos, startIdx = 0) => {
    setLightbox({ photos: cellPhotos, index: startIdx })
  }, [])

  return (
    <>
      <div className={styles.wrapper}>
        <div
          className={styles.grid}
          style={{ gridTemplateColumns: `var(--label-w) repeat(${cols.length}, var(--cell-size))` }}
        >
          {/* Corner */}
          <div className={`${styles.corner} ${styles.stickyColHeader}`}>
            <span>Angle  /  Inspection →</span>
          </div>

          {/* Column headers */}
          {cols.map(txn => (
            <div key={txn.id} className={`${styles.colHeader} ${styles.stickyRow}`}>
              <span className={styles.inspNum}>#{txn.order + 1}</span>
              <span className={styles.inspDate}>{txn.date}</span>
            </div>
          ))}

          {/* Rows */}
          {rows.map(cluster => (
            <>
              {/* Row label */}
              <div
                key={`label-${cluster.id}`}
                className={`${styles.rowLabel} ${styles.stickyCol}`}
                style={{ borderLeft: `3px solid ${cluster.color}` }}
              >
                <span className={styles.clusterName}>{cluster.label}</span>
                <span className={styles.clusterCount}>{cluster.count} photos</span>
              </div>

              {/* Cells */}
              {cols.map(txn => {
                const key = `${cluster.id}__${txn.id}`
                const cellPhotos = cellMap[key] || []
                return (
                  <Cell
                    key={`${cluster.id}-${txn.id}`}
                    photos={cellPhotos}
                    color={cluster.color}
                    onOpen={openLightbox}
                  />
                )
              })}
            </>
          ))}
        </div>
      </div>

      {lightbox && (
        <Lightbox
          photos={lightbox.photos}
          startIndex={lightbox.index}
          onClose={() => setLightbox(null)}
        />
      )}
    </>
  )
}

function Cell({ photos, color, onOpen }) {
  const [hovered, setHovered] = useState(false)

  if (photos.length === 0) {
    return <div className={styles.cellEmpty} />
  }

  const main = photos[0]
  const extra = photos.length - 1

  return (
    <div
      className={`${styles.cell} ${hovered ? styles.cellHovered : ''}`}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={() => onOpen(photos, 0)}
      style={{ '--cluster-color': color }}
    >
      <img
        src={main.thumbnail_url}
        alt=""
        loading="lazy"
        decoding="async"
        className={styles.thumb}
        draggable={false}
      />
      {extra > 0 && (
        <span className={styles.badge}>+{extra}</span>
      )}
      {hovered && (
        <div className={styles.hoverBar} style={{ background: color }} />
      )}
    </div>
  )
}
