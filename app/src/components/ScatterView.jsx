import { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import styles from './ScatterView.module.css'

const PAD   = 0.08
const R     = 4
const R_HOV = 6

export default function ScatterView({ layout }) {
  const { photos, clusters, transactions } = layout
  const canvasRef = useRef(null)
  const stateRef  = useRef({ photos, clusters, W: 0, H: 0 })
  const [tooltip, setTooltip] = useState(null) // { x, y, photo, cluster, date }

  const txnDateMap = useMemo(() => {
    const m = {}
    transactions.forEach(t => { m[t.id] = t.date })
    return m
  }, [transactions])

  const clusterMap = useMemo(
    () => new Map(clusters.map(c => [c.id, c])),
    [clusters]
  )

  // Keep ref in sync so canvas callbacks always use fresh data
  useEffect(() => {
    stateRef.current.photos   = photos
    stateRef.current.clusters = clusters
  }, [photos, clusters])

  const toCanvas = useCallback((nx, ny, W, H) => [
    PAD * W + nx * W * (1 - 2 * PAD),
    PAD * H + ny * H * (1 - 2 * PAD),
  ], [])

  const draw = useCallback((hoverId = null) => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    const { W, H, photos: ps, clusters: cls } = stateRef.current
    const cMap = new Map(cls.map(c => [c.id, c]))

    ctx.clearRect(0, 0, W, H)

    // Cluster label text
    ctx.textAlign = 'center'
    ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    for (const cl of cls) {
      if (cl.id === -1) continue
      const [cx, cy] = toCanvas(cl.centroid_x, cl.centroid_y, W, H)
      ctx.fillStyle = cl.color + '44'
      ctx.fillText(cl.label, cx, cy - R - 6)
    }

    // Dots (non-hovered)
    for (const p of ps) {
      if (p.id === hoverId) continue
      const cl = cMap.get(p.cluster)
      const [px, py] = toCanvas(p.x, p.y, W, H)
      ctx.beginPath()
      ctx.arc(px, py, R, 0, Math.PI * 2)
      ctx.fillStyle = (cl?.color ?? '#666') + 'bb'
      ctx.fill()
    }

    // Hovered dot on top
    if (hoverId) {
      const p = ps.find(ph => ph.id === hoverId)
      if (p) {
        const cl = cMap.get(p.cluster)
        const [px, py] = toCanvas(p.x, p.y, W, H)
        ctx.beginPath()
        ctx.arc(px, py, R_HOV, 0, Math.PI * 2)
        ctx.fillStyle = cl?.color ?? '#fff'
        ctx.fill()
        ctx.strokeStyle = '#fff'
        ctx.lineWidth = 1.5
        ctx.stroke()
      }
    }
  }, [toCanvas])

  // Resize + initial draw
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const resize = () => {
      const W = canvas.offsetWidth
      const H = canvas.offsetHeight
      canvas.width  = W
      canvas.height = H
      stateRef.current.W = W
      stateRef.current.H = H
      draw()
    }

    const ro = new ResizeObserver(resize)
    ro.observe(canvas)
    resize()
    return () => ro.disconnect()
  }, [draw])

  const hitTest = useCallback((mx, my) => {
    const { W, H, photos: ps } = stateRef.current
    let best = null, bestD = (R + 6) ** 2
    for (const p of ps) {
      const [px, py] = toCanvas(p.x, p.y, W, H)
      const d = (mx - px) ** 2 + (my - py) ** 2
      if (d < bestD) { bestD = d; best = p }
    }
    return best
  }, [toCanvas])

  const onMouseMove = useCallback(e => {
    const rect = canvasRef.current.getBoundingClientRect()
    const p = hitTest(e.clientX - rect.left, e.clientY - rect.top)
    if (p) {
      draw(p.id)
      setTooltip({
        x:       e.clientX,
        y:       e.clientY,
        photo:   p,
        cluster: clusterMap.get(p.cluster)?.label ?? 'Other',
        date:    txnDateMap[p.txn_id] ?? '',
      })
    } else {
      draw()
      setTooltip(null)
    }
  }, [hitTest, draw, clusterMap, txnDateMap])

  const onClick = useCallback(e => {
    const rect = canvasRef.current.getBoundingClientRect()
    const p = hitTest(e.clientX - rect.left, e.clientY - rect.top)
    if (p) window.open(p.url, '_blank', 'noopener,noreferrer')
  }, [hitTest])

  const onMouseLeave = useCallback(() => { draw(); setTooltip(null) }, [draw])

  return (
    <div className={styles.wrap}>
      <canvas
        ref={canvasRef}
        className={styles.canvas}
        onMouseMove={onMouseMove}
        onClick={onClick}
        onMouseLeave={onMouseLeave}
      />

      {tooltip && (
        <div
          className={styles.tooltip}
          style={{ left: tooltip.x + 14, top: tooltip.y - 80 }}
        >
          <img
            src={tooltip.photo.thumbnail_url}
            alt=""
            className={styles.tipImg}
          />
          <div className={styles.tipCluster}>{tooltip.cluster}</div>
          <div className={styles.tipDate}>{tooltip.date}</div>
        </div>
      )}

      <div className={styles.legend}>
        {clusters.filter(c => c.id !== -1).sort((a, b) => b.count - a.count).map(c => (
          <div key={c.id} className={styles.legendItem}>
            <span className={styles.dot} style={{ background: c.color }} />
            <span className={styles.lLabel}>{c.label}</span>
            <span className={styles.lCount}>{c.count}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
