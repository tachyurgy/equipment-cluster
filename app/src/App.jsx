import { useState, useEffect } from 'react'
import UnitViewer from './components/UnitViewer'
import styles from './App.module.css'

export default function App() {
  const [units, setUnits]             = useState([])
  const [selectedId, setSelectedId]   = useState(null)
  const [layout, setLayout]           = useState(null)
  const [loading, setLoading]         = useState(false)
  const [error, setError]             = useState(null)

  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}data/units.json`)
      .then(r => r.json())
      .then(d => {
        const sorted = [...d.units].sort((a, b) => b.transaction_count - a.transaction_count)
        setUnits(sorted)
        if (sorted.length) setSelectedId(sorted[0].id)
      })
      .catch(() => setError('Could not load units.json — run python3 cluster.py first'))
  }, [])

  useEffect(() => {
    if (!selectedId) return
    setLoading(true)
    setLayout(null)
    setError(null)
    fetch(`${import.meta.env.BASE_URL}data/layouts/${selectedId}.json`)
      .then(r => r.json())
      .then(d => { setLayout(d); setLoading(false) })
      .catch(() => { setError(`No layout for unit ${selectedId}`); setLoading(false) })
  }, [selectedId])

  return (
    <div className={styles.app}>
      {/* Sidebar */}
      <aside className={styles.sidebar}>
        <div className={styles.sidebarHeader}>
          <span className={styles.logo}>⚙</span>
          <span>Equipment History</span>
        </div>
        <div className={styles.unitList}>
          {units.map(u => (
            <button
              key={u.id}
              className={`${styles.unitBtn} ${u.id === selectedId ? styles.active : ''}`}
              onClick={() => setSelectedId(u.id)}
            >
              <span className={styles.unitId}>#{u.id}</span>
              <span className={styles.unitMeta}>
                {u.transaction_count} inspections
                {u.date_range?.start && (
                  <span className={styles.dateRange}>
                    {' '}· {u.date_range.start.split(',')[0]} – {u.date_range.end.split(',')[0]}
                  </span>
                )}
              </span>
            </button>
          ))}
        </div>
      </aside>

      {/* Main */}
      <main className={styles.main}>
        {error && <div className={styles.error}>{error}</div>}
        {loading && <div className={styles.spinner}><div className={styles.dot} /></div>}
        {layout && !loading && <UnitViewer layout={layout} />}
        {!layout && !loading && !error && units.length === 0 && (
          <div className={styles.empty}>
            Run <code>python3 embed.py &amp;&amp; python3 cluster.py</code> to generate data.
          </div>
        )}
      </main>
    </div>
  )
}
