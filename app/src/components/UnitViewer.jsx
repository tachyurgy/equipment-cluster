import { useState } from 'react'
import ClusterGrid from './ClusterGrid'
import ClusterTimeline from './ClusterTimeline'
import styles from './UnitViewer.module.css'

export default function UnitViewer({ layout }) {
  const [selected, setSelected] = useState(null) // { cluster, photos }

  const realClusters = layout.clusters.filter(c => c.id !== -1)
  const noisePct = layout.clusters.find(c => c.id === -1)?.count ?? 0

  return (
    <div className={styles.viewer}>
      <div className={styles.header}>
        <span className={styles.unitId}>Unit #{layout.unit_id}</span>
        <span className={styles.sep}>·</span>
        <span className={styles.metaStrong}>{realClusters.length} angles</span>
        <span className={styles.sep}>·</span>
        <span className={styles.meta}>{layout.photo_count} photos across {layout.transaction_count} inspections</span>
        {layout.date_range?.start && (
          <>
            <span className={styles.sep}>·</span>
            <span className={styles.meta}>
              {layout.date_range.start} – {layout.date_range.end}
            </span>
          </>
        )}

      </div>

      <div className={styles.content}>
        {selected ? (
          <div className={styles.timelineWrap}>
            <button
              className={styles.backPill}
              onClick={() => setSelected(null)}
            >
              ← All angles
            </button>
            <ClusterTimeline
              cluster={selected.cluster}
              photos={selected.photos}
            />
          </div>
        ) : (
          <ClusterGrid
            layout={layout}
            onSelectCluster={setSelected}
          />
        )}
      </div>
    </div>
  )
}
