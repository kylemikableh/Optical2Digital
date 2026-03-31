import { useState, useCallback, useEffect, useRef } from 'react'

const API = ''  // proxied by vite in dev

function App() {
  // Project state
  const [loaded, setLoaded] = useState(false)
  const [numFrames, setNumFrames] = useState(0)
  const [frameWidth, setFrameWidth] = useState(0)
  const [frameHeight, setFrameHeight] = useState(0)
  const [frameIndex, setFrameIndex] = useState(0)
  const [inputDir, setInputDir] = useState('./examples/fulltest/')
  const [showLoad, setShowLoad] = useState(true)
  const [loadError, setLoadError] = useState('')

  // Crop
  const [cropTop, setCropTop] = useState(2330)
  const [trackHeight, setTrackHeight] = useState(134)
  const [cropLeft, setCropLeft] = useState(960)
  const [cropRight, setCropRight] = useState(2796)

  // Corrections
  const [rotate, setRotate] = useState(270)
  const [negative, setNegative] = useState(false)
  const [lift, setLift] = useState(0.0)
  const [gamma, setGamma] = useState(1.0)
  const [gain, setGain] = useState(1.0)
  const [threshold, setThreshold] = useState(0.0)

  // Extraction settings
  const [fps, setFps] = useState(24.0)
  const [sampleRate, setSampleRate] = useState(48000)
  const [hpf, setHpf] = useState(40.0)
  const [lpf, setLpf] = useState(13500.0)
  const [overlap, setOverlap] = useState(0.25)
  const [reverse, setReverse] = useState(false)

  // Crop overlay interaction
  const imgRef = useRef(null)
  const [dragState, setDragState] = useState(null)
  const [extracting, setExtracting] = useState(false)
  const [status, setStatus] = useState('')

  // --- Load project ---
  const loadProject = useCallback(async () => {
    setLoadError('')
    try {
      const res = await fetch(`${API}/api/load`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input_dir: inputDir }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Load failed')
      }
      const data = await res.json()
      setNumFrames(data.num_frames)
      setFrameWidth(data.frame_width)
      setFrameHeight(data.frame_height)
      setFrameIndex(0)
      setLoaded(true)
      setShowLoad(false)
      setStatus(`Loaded ${data.num_frames} frames (${data.frame_width}×${data.frame_height})`)
    } catch (e) {
      setLoadError(e.message)
    }
  }, [inputDir])

  // --- Image URLs (server returns already-rotated images) ---
  const rawUrl = loaded
    ? `${API}/api/frame/${frameIndex}/raw?rotate=${rotate}`
    : null

  const correctedParams = new URLSearchParams({
    rotate, negative, lift, gamma, gain, threshold,
  }).toString()
  const correctedUrl = loaded
    ? `${API}/api/frame/${frameIndex}/corrected?${correctedParams}`
    : null

  // Screen dimensions after rotation
  const screenWidth = (rotate === 90 || rotate === 270) ? frameHeight : frameWidth
  const screenHeight = (rotate === 90 || rotate === 270) ? frameWidth : frameHeight

  // Derived crop bottom from top + trackHeight
  const cropBottom = cropTop + trackHeight

  // Overlap in pixels
  const overlapPx = Math.round(trackHeight * overlap)
  const overlapTopY = Math.max(0, cropTop - overlapPx)
  const overlapBottomY = Math.min(screenHeight, cropBottom + overlapPx)

  // Crop region as percentages of screen dimensions
  const topPct = screenHeight > 0 ? (cropTop / screenHeight * 100) : 0
  const bottomPct = screenHeight > 0 ? (cropBottom / screenHeight * 100) : 0
  const leftPct = screenWidth > 0 ? (cropLeft / screenWidth * 100) : 0
  const rightPct = screenWidth > 0 ? (cropRight / screenWidth * 100) : 0

  // Overlap zone percentages
  const overlapTopPct = screenHeight > 0 ? (overlapTopY / screenHeight * 100) : 0
  const overlapBottomPct = screenHeight > 0 ? (overlapBottomY / screenHeight * 100) : 0

  // Convert screen-space crop to image-space crop for API calls
  function screenToImageCrop(sTop, sBot, sLeft, sRight) {
    const W = frameWidth, H = frameHeight
    switch (rotate) {
      case 90:  return { top: H - sRight, bottom: H - sLeft, left: sTop, right: sBot }
      case 180: return { top: H - sBot, bottom: H - sTop, left: W - sRight, right: W - sLeft }
      case 270: return { top: sLeft, bottom: sRight, left: W - sBot, right: W - sTop }
      default:  return { top: sTop, bottom: sBot, left: sLeft, right: sRight }
    }
  }

  // --- Crop drag handling ---
  useEffect(() => {
    if (!dragState) return
    const cursors = {
      move: 'move', t: 'ns-resize', b: 'ns-resize',
      l: 'ew-resize', r: 'ew-resize',
      tl: 'nwse-resize', br: 'nwse-resize',
      tr: 'nesw-resize', bl: 'nesw-resize',
    }
    document.body.style.cursor = cursors[dragState.type] || 'default'
    document.body.style.userSelect = 'none'

    const handleMouseMove = (e) => {
      if (!imgRef.current) return
      const scale = imgRef.current.offsetWidth / screenWidth
      const dx = Math.round((e.clientX - dragState.startX) / scale)
      const dy = Math.round((e.clientY - dragState.startY) / scale)
      const { type, origTop, origBottom, origLeft, origRight } = dragState
      const clampX = v => Math.max(0, Math.min(screenWidth, v))
      const clampY = v => Math.max(0, Math.min(screenHeight, v))

      if (type === 'move') {
        const w = origRight - origLeft
        const h = origBottom - origTop
        let nl = Math.max(0, Math.min(screenWidth - w, origLeft + dx))
        let nt = Math.max(0, Math.min(screenHeight - h, origTop + dy))
        setCropLeft(nl); setCropRight(nl + w)
        setCropTop(nt)
      } else {
        // Top edge: move top, adjust trackHeight
        if (type.includes('t')) {
          const newTop = clampY(Math.min(origTop + dy, origBottom - 10))
          setCropTop(newTop)
          setTrackHeight(origBottom - newTop)
        }
        // Bottom edge: adjust trackHeight, keep top fixed
        if (type.includes('b')) {
          const newBottom = clampY(Math.max(origBottom + dy, origTop + 10))
          setTrackHeight(newBottom - origTop)
        }
        if (type.includes('l')) setCropLeft(clampX(Math.min(origLeft + dx, dragState.origRight - 10)))
        if (type.includes('r')) setCropRight(clampX(Math.max(origRight + dx, dragState.origLeft + 10)))
      }
    }
    const handleMouseUp = () => {
      setDragState(null)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
  }, [dragState, screenWidth, screenHeight, trackHeight])

  // --- Extract ---
  const handleExtract = useCallback(async () => {
    setExtracting(true)
    setStatus('Extracting audio...')
    try {
      const imgCrop = screenToImageCrop(cropTop, cropBottom, cropLeft, cropRight)
      const res = await fetch(`${API}/api/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          top: imgCrop.top, bottom: imgCrop.bottom, left: imgCrop.left, right: imgCrop.right,
          rotate, negative, lift, gamma, gain, threshold,
          fps, sample_rate: sampleRate, hpf, lpf, overlap, reverse,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Extraction failed')
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'output.wav'
      a.click()
      URL.revokeObjectURL(url)
      setStatus('Extraction complete — WAV downloaded')
    } catch (e) {
      setStatus(`Error: ${e.message}`)
    } finally {
      setExtracting(false)
    }
  }, [cropTop, trackHeight, cropLeft, cropRight, rotate, negative, lift, gamma, gain, threshold, fps, sampleRate, hpf, lpf, overlap, reverse])

  return (
    <div className="app">
      {/* Load dialog */}
      {showLoad && (
        <div className="load-overlay">
          <div className="load-dialog">
            <h2>Load Frame Directory</h2>
            <input
              type="text"
              value={inputDir}
              onChange={e => setInputDir(e.target.value)}
              placeholder="Path to frame images directory..."
              onKeyDown={e => e.key === 'Enter' && loadProject()}
            />
            {loadError && <p className="error">{loadError}</p>}
            <div className="actions">
              {loaded && <button className="btn-secondary" onClick={() => setShowLoad(false)}>Cancel</button>}
              <button className="btn-primary" onClick={loadProject}>Load</button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="header">
        <h1>Kyle's Optical Decoder</h1>
        {loaded && (
          <>
            <span className="project-info">{numFrames} frames • {frameWidth}×{frameHeight}</span>
            <button className="btn-secondary btn-small" onClick={() => setShowLoad(true)}>Change</button>
          </>
        )}
      </div>

      <div className="main">
        {/* Sidebar */}
        <div className="sidebar">
          {/* Crop */}
          <section>
            <h3>Crop Region</h3>
            <div className="control-group">
              <NumberInput label="Top" value={cropTop} onChange={setCropTop} min={0} max={screenHeight - trackHeight} />
              <NumberInput label="Track Height" value={trackHeight} onChange={setTrackHeight} min={10} max={screenHeight} />
              <NumberInput label="Left" value={cropLeft} onChange={setCropLeft} min={0} max={screenWidth} />
              <NumberInput label="Right" value={cropRight} onChange={setCropRight} min={0} max={screenWidth} />
            </div>
          </section>

          {/* Rotation */}
          <section>
            <h3>Rotation</h3>
            <div className="control-row">
              <label>Degrees CW</label>
              <select value={rotate} onChange={e => setRotate(Number(e.target.value))}>
                <option value={0}>0°</option>
                <option value={90}>90°</option>
                <option value={180}>180°</option>
                <option value={270}>270°</option>
              </select>
            </div>
          </section>

          {/* Corrections */}
          <section>
            <h3>Image Corrections</h3>
            <div className="control-group">
              <div className="checkbox-row">
                <input type="checkbox" id="neg" checked={negative} onChange={e => setNegative(e.target.checked)} />
                <label htmlFor="neg">Negative inversion</label>
              </div>
              <SliderInput label="Lift" value={lift} onChange={setLift} min={-1} max={1} step={0.01} />
              <SliderInput label="Gamma" value={gamma} onChange={setGamma} min={0.1} max={5} step={0.05} />
              <SliderInput label="Gain" value={gain} onChange={setGain} min={0} max={5} step={0.05} />
              <SliderInput label="S-Curve" value={threshold} onChange={setThreshold} min={0} max={20} step={0.5} />
            </div>
          </section>

          {/* Audio / Extraction */}
          <section>
            <h3>Audio Settings</h3>
            <div className="control-group">
              <NumberInput label="FPS" value={fps} onChange={setFps} min={1} max={120} step={0.001} />
              <NumberInput label="Sample Rate" value={sampleRate} onChange={setSampleRate} min={8000} max={192000} />
              <SliderInput label="HPF (Hz)" value={hpf} onChange={setHpf} min={0} max={500} step={1} />
              <SliderInput label="LPF (Hz)" value={lpf} onChange={setLpf} min={1000} max={24000} step={100} />
              <SliderInput label="Overlap" value={overlap} onChange={setOverlap} min={0} max={0.5} step={0.01} />
              <div className="checkbox-row">
                <input type="checkbox" id="rev" checked={reverse} onChange={e => setReverse(e.target.checked)} />
                <label htmlFor="rev">Reverse frame order</label>
              </div>
            </div>
          </section>

          {/* Extract */}
          <section className="extract-section">
            <h3>Extract</h3>
            <button className="btn-primary" onClick={handleExtract} disabled={!loaded || extracting}>
              {extracting ? 'Extracting...' : 'Extract Audio'}
            </button>
          </section>
        </div>

        {/* Preview with interactive crop overlay */}
        <div className="preview-area">
          <div className="crop-canvas">
            {loaded && rawUrl ? (
              <div className="image-wrapper">
                <img ref={imgRef} src={rawUrl} alt={`Frame ${frameIndex}`} className="base-image" />
                {/* Corrected image clipped to crop region */}
                <img
                  src={correctedUrl} alt="" className="corrected-image"
                  style={{ clipPath: `inset(${topPct}% ${100 - rightPct}% ${100 - bottomPct}% ${leftPct}%)` }}
                />
                {/* Overlap zones */}
                {overlapPx > 0 && (
                  <>
                    <div className="overlap-zone" style={{
                      top: `${overlapTopPct}%`, left: `${leftPct}%`,
                      width: `${rightPct - leftPct}%`, height: `${topPct - overlapTopPct}%`,
                    }} />
                    <div className="overlap-zone" style={{
                      top: `${bottomPct}%`, left: `${leftPct}%`,
                      width: `${rightPct - leftPct}%`, height: `${overlapBottomPct - bottomPct}%`,
                    }} />
                  </>
                )}
                {/* Dim overlay outside crop+overlap */}
                <div className="crop-dim" style={{ top: 0, left: 0, right: 0, height: `${topPct}%` }} />
                <div className="crop-dim" style={{ bottom: 0, left: 0, right: 0, height: `${100 - bottomPct}%` }} />
                <div className="crop-dim" style={{ top: `${topPct}%`, left: 0, width: `${leftPct}%`, bottom: `${100 - bottomPct}%` }} />
                <div className="crop-dim" style={{ top: `${topPct}%`, right: 0, width: `${100 - rightPct}%`, bottom: `${100 - bottomPct}%` }} />
                {/* Frame boundary lines — full width */}
                <div className="frame-line" style={{ top: `${topPct}%` }} />
                <div className="frame-line" style={{ top: `${bottomPct}%` }} />
                {/* Crop border */}
                <div className="crop-border" style={{
                  top: `${topPct}%`, left: `${leftPct}%`,
                  width: `${rightPct - leftPct}%`, height: `${bottomPct - topPct}%`,
                }} />
                {/* Draggable move area */}
                <div
                  className="crop-move-area"
                  style={{ top: `${topPct}%`, left: `${leftPct}%`, width: `${rightPct - leftPct}%`, height: `${bottomPct - topPct}%` }}
                  onMouseDown={e => { e.preventDefault(); setDragState({ type: 'move', startX: e.clientX, startY: e.clientY, origTop: cropTop, origBottom: cropBottom, origLeft: cropLeft, origRight: cropRight }) }}
                />
                {/* Corner + edge drag handles — vertical handles move box, horizontal resize width */}
                {[
                  { type: 'tl', top: topPct, left: leftPct, cursor: 'nwse-resize' },
                  { type: 'tr', top: topPct, left: rightPct, cursor: 'nesw-resize' },
                  { type: 'bl', top: bottomPct, left: leftPct, cursor: 'nesw-resize' },
                  { type: 'br', top: bottomPct, left: rightPct, cursor: 'nwse-resize' },
                  { type: 't', top: topPct, left: (leftPct + rightPct) / 2, cursor: 'ns-resize' },
                  { type: 'b', top: bottomPct, left: (leftPct + rightPct) / 2, cursor: 'ns-resize' },
                  { type: 'l', top: (topPct + bottomPct) / 2, left: leftPct, cursor: 'ew-resize' },
                  { type: 'r', top: (topPct + bottomPct) / 2, left: rightPct, cursor: 'ew-resize' },
                ].map(h => (
                  <div
                    key={h.type} className="crop-handle"
                    style={{ top: `${h.top}%`, left: `${h.left}%`, transform: 'translate(-50%, -50%)', cursor: h.cursor }}
                    onMouseDown={e => { e.preventDefault(); e.stopPropagation(); setDragState({ type: h.type, startX: e.clientX, startY: e.clientY, origTop: cropTop, origBottom: cropBottom, origLeft: cropLeft, origRight: cropRight }) }}
                  />
                ))}
              </div>
            ) : (
              <p style={{ color: 'var(--text-muted)' }}>Load a project to preview frames</p>
            )}
          </div>
          {loaded && (
            <div className="frame-nav">
              <button className="btn-secondary btn-small" onClick={() => setFrameIndex(0)} disabled={frameIndex === 0}>⏮</button>
              <button className="btn-secondary btn-small" onClick={() => setFrameIndex(i => Math.max(0, i - 1))} disabled={frameIndex === 0}>◀</button>
              <span>Frame {frameIndex + 1} / {numFrames}</span>
              <button className="btn-secondary btn-small" onClick={() => setFrameIndex(i => Math.min(numFrames - 1, i + 1))} disabled={frameIndex >= numFrames - 1}>▶</button>
              <button className="btn-secondary btn-small" onClick={() => setFrameIndex(numFrames - 1)} disabled={frameIndex >= numFrames - 1}>⏭</button>
              <input
                type="range" min={0} max={numFrames - 1} value={frameIndex}
                onChange={e => setFrameIndex(Number(e.target.value))}
                style={{ width: 200 }}
              />
            </div>
          )}
        </div>
      </div>

      {/* Status bar */}
      <div className="status-bar">
        <span>{status}</span>
      </div>
    </div>
  )
}

// --- Reusable control components ---

function SliderInput({ label, value, onChange, min, max, step }) {
  return (
    <div className="control-row">
      <label>{label}</label>
      <input type="range" min={min} max={max} step={step} value={value}
        onChange={e => onChange(Number(e.target.value))} />
      <span className="value">{typeof value === 'number' ? (Number.isInteger(step) ? value : value.toFixed(2)) : value}</span>
    </div>
  )
}

function NumberInput({ label, value, onChange, min, max, step }) {
  return (
    <div className="control-row">
      <label>{label}</label>
      <input type="number" min={min} max={max} step={step || 1} value={value}
        onChange={e => onChange(Number(e.target.value))} />
    </div>
  )
}

export default App
