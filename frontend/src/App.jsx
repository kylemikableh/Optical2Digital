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
  const [cropBottom, setCropBottom] = useState(2464)
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

  // View mode: 'raw' or 'preview'
  const [viewMode, setViewMode] = useState('preview')
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

  // --- Image URLs ---
  const rawUrl = loaded
    ? `${API}/api/frame/${frameIndex}/raw`
    : null

  const previewParams = new URLSearchParams({
    top: cropTop, bottom: cropBottom, left: cropLeft, right: cropRight,
    rotate, negative, lift, gamma, gain, threshold,
  }).toString()
  const previewUrl = loaded
    ? `${API}/api/frame/${frameIndex}/preview?${previewParams}`
    : null

  const imgSrc = viewMode === 'raw' ? rawUrl : previewUrl

  // --- Extract ---
  const handleExtract = useCallback(async () => {
    setExtracting(true)
    setStatus('Extracting audio...')
    try {
      const res = await fetch(`${API}/api/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          top: cropTop, bottom: cropBottom, left: cropLeft, right: cropRight,
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
  }, [cropTop, cropBottom, cropLeft, cropRight, rotate, negative, lift, gamma, gain, threshold, fps, sampleRate, hpf, lpf, overlap, reverse])

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
              <NumberInput label="Top" value={cropTop} onChange={setCropTop} min={0} max={frameHeight} />
              <NumberInput label="Bottom" value={cropBottom} onChange={setCropBottom} min={0} max={frameHeight} />
              <NumberInput label="Left" value={cropLeft} onChange={setCropLeft} min={0} max={frameWidth} />
              <NumberInput label="Right" value={cropRight} onChange={setCropRight} min={0} max={frameWidth} />
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

        {/* Preview */}
        <div className="preview-area">
          <div className="tab-bar">
            <button className={viewMode === 'raw' ? 'active' : ''} onClick={() => setViewMode('raw')}>Raw Frame</button>
            <button className={viewMode === 'preview' ? 'active' : ''} onClick={() => setViewMode('preview')}>Cropped + Corrected</button>
          </div>
          <div className="preview-container">
            {loaded && imgSrc ? (
              <img src={imgSrc} alt={`Frame ${frameIndex}`} />
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
