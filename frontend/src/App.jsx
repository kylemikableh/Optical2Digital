/*
 * This file is part of Kyle's Optical Decoder.
 *
 * Copyright (C) 2026 Kyle Mikolajczyk
 *
 * Kyle's Optical Decoder is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * Kyle's Optical Decoder is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with Kyle's Optical Decoder; if not, write to the Free Software
 * Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
 */

import { useState, useCallback, useEffect, useRef } from 'react'

const API = ''  // proxied by vite in dev

const SETTINGS_PREFIX = 'optical2digital:'

/** Debounce URL changes and fetch images via AbortController so rapid
 *  scrubbing / slider drags don't flood the server with stale requests. */
function useDebouncedImageUrl(url, delay = 150) {
  const [src, setSrc] = useState(null)
  const abortRef = useRef(null)
  const blobRef = useRef(null)

  useEffect(() => {
    if (!url) {
      if (abortRef.current) abortRef.current.abort()
      if (blobRef.current) URL.revokeObjectURL(blobRef.current)
      blobRef.current = null
      setSrc(null)
      return
    }

    const timer = setTimeout(() => {
      if (abortRef.current) abortRef.current.abort()
      const ac = new AbortController()
      abortRef.current = ac

      fetch(url, { signal: ac.signal })
        .then(r => r.blob())
        .then(blob => {
          if (ac.signal.aborted) return
          const next = URL.createObjectURL(blob)
          if (blobRef.current) URL.revokeObjectURL(blobRef.current)
          blobRef.current = next
          setSrc(next)
        })
        .catch(e => { if (e.name !== 'AbortError') console.error(e) })
    }, delay)

    return () => clearTimeout(timer)
  }, [url, delay])

  useEffect(() => () => {
    if (abortRef.current) abortRef.current.abort()
    if (blobRef.current) URL.revokeObjectURL(blobRef.current)
  }, [])

  return src
}

function saveSettings(path, settings) {
  try { localStorage.setItem(SETTINGS_PREFIX + path, JSON.stringify(settings)) } catch {}
}

function loadSettings(path) {
  try {
    const raw = localStorage.getItem(SETTINGS_PREFIX + path)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function soundtrackChannelLabel(soundtrackColor) {
  if (soundtrackColor === 'Cyan') return 'RED channel (non-monochrome frames)'
  return 'GREEN channel (non-monochrome frames)'
}

function App() {
  // Project state
  const [loaded, setLoaded] = useState(false)
  const [numFrames, setNumFrames] = useState(0)
  const [frameWidth, setFrameWidth] = useState(0)
  const [frameHeight, setFrameHeight] = useState(0)
  const [frameIndex, setFrameIndex] = useState(0)
  const [inputDir, setInputDir] = useState('./examples/output/')
  const [showLoad, setShowLoad] = useState(true)
  const [loadError, setLoadError] = useState('')

  // Crop
  const [cropTop, setCropTop] = useState(297)
  const [trackHeight, setTrackHeight] = useState(3070)
  const [cropLeft, setCropLeft] = useState(849)
  const [cropRight, setCropRight] = useState(1191)

  // Corrections
  const [rotate, setRotate] = useState(0)
  const [negative, setNegative] = useState(false)
  const [dminValue, setDminValue] = useState(1.0)
  const [dminHeadroom, setDminHeadroom] = useState(0.2)
  const [binaryMask, setBinaryMask] = useState(false)
  const [binaryLb, setBinaryLb] = useState(96)
  const [binaryUb, setBinaryUb] = useState(255)

  // Extraction settings
  const [fps, setFps] = useState(24.0)
  const [sampleRate, setSampleRate] = useState(48000)
  const [hpf, setHpf] = useState(40.0)
  const [lpf, setLpf] = useState(13500.0)
  const [overlap, setOverlap] = useState(0.05)
  const [soundtrackColor, setSoundtrackColor] = useState('B&W')
  const [reverse, setReverse] = useState(false)
  const [stereo, setStereo] = useState(true)
  const [showStereoGuides, setShowStereoGuides] = useState(true)
  const [showZoom, setShowZoom] = useState(true)
  const [zoomLevel, setZoomLevel] = useState(6)
  const [startFrame, setStartFrame] = useState(0)
  const [endFrame, setEndFrame] = useState(0)

  // Crop overlay interaction
  const imgRef = useRef(null)
  const importSettingsRef = useRef(null)
  const [dragState, setDragState] = useState(null)
  const [extracting, setExtracting] = useState(false)
  const [status, setStatus] = useState('')
  const [extractProgress, setExtractProgress] = useState(null)
  const [pickingDmin, setPickingDmin] = useState(false)
  const [dminPickPoint, setDminPickPoint] = useState(null)
  const [hoverZoom, setHoverZoom] = useState(null)
  const wakeLockRef = useRef(null)

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

      // Restore saved settings for this path, or use defaults
      const saved = loadSettings(inputDir)
      if (saved) {
        setCropTop(saved.cropTop ?? 297)
        setTrackHeight(saved.trackHeight ?? 3070)
        setCropLeft(saved.cropLeft ?? 849)
        setCropRight(saved.cropRight ?? 1191)
        setRotate(saved.rotate ?? 0)
        setNegative(saved.negative ?? false)
        setDminValue(saved.dminValue ?? 1.0)
        setDminHeadroom(saved.dminHeadroom ?? 0.2)
        setBinaryMask(saved.binaryMask ?? false)
        setBinaryLb(saved.binaryLb ?? 96)
        setBinaryUb(saved.binaryUb ?? 255)
        setFps(saved.fps ?? data.fps ?? 24.0)
        setSampleRate(saved.sampleRate ?? 48000)
        setHpf(saved.hpf ?? 40.0)
        setLpf(saved.lpf ?? 13500.0)
        setOverlap(saved.overlap ?? 0.05)
        setSoundtrackColor(saved.soundtrackColor ?? 'B&W')
        setReverse(saved.reverse ?? false)
        setStereo(saved.stereo ?? true)
        setShowStereoGuides(saved.showStereoGuides ?? true)
        setShowZoom(saved.showZoom ?? true)
        setZoomLevel(saved.zoomLevel ?? 6)
        setStartFrame(saved.startFrame ?? 0)
        setEndFrame(saved.endFrame ?? data.num_frames - 1)
      } else {
        if (data.fps) setFps(data.fps)
        setStartFrame(0)
        setEndFrame(data.num_frames - 1)
      }

      setLoaded(true)
      setShowLoad(false)
      const label = data.fps ? 'video' : 'image sequence'
      setStatus(`Loaded ${data.num_frames} frames (${data.frame_width}×${data.frame_height}, ${label})`)
    } catch (e) {
      setLoadError(e.message)
    }
  }, [inputDir])

  // --- Auto-save settings to localStorage whenever they change ---
  useEffect(() => {
    if (!loaded) return
    saveSettings(inputDir, {
      cropTop, trackHeight, cropLeft, cropRight,
      rotate, negative,
      dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb,
      fps, sampleRate, hpf, lpf, overlap, soundtrackColor, reverse, stereo, showStereoGuides,
      showZoom, zoomLevel,
      startFrame, endFrame,
    })
  }, [loaded, inputDir, cropTop, trackHeight, cropLeft, cropRight,
      rotate, negative,
      dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb,
      fps, sampleRate, hpf, lpf, overlap, soundtrackColor, reverse, stereo, showStereoGuides,
      showZoom, zoomLevel,
      startFrame, endFrame])

  useEffect(() => {
    setDminPickPoint(null)
    setPickingDmin(false)
    setHoverZoom(null)
  }, [frameIndex])

  useEffect(() => {
    if (!showZoom) setHoverZoom(null)
  }, [showZoom])

  // Keep the screen awake on supported browsers while a project is loaded.
  useEffect(() => {
    if (!loaded || !('wakeLock' in navigator)) return

    let disposed = false

    const requestWakeLock = async () => {
      if (document.visibilityState !== 'visible') return
      if (wakeLockRef.current) return

      try {
        const sentinel = await navigator.wakeLock.request('screen')
        if (disposed) {
          await sentinel.release()
          return
        }

        wakeLockRef.current = sentinel
        sentinel.addEventListener('release', () => {
          if (wakeLockRef.current === sentinel) wakeLockRef.current = null
        })
      } catch (err) {
        // Wake Lock can fail due to policy, power mode, or browser support nuances.
        console.warn('Wake Lock unavailable:', err)
      }
    }

    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') requestWakeLock()
    }

    requestWakeLock()
    document.addEventListener('visibilitychange', onVisibilityChange)

    return () => {
      disposed = true
      document.removeEventListener('visibilitychange', onVisibilityChange)
      const sentinel = wakeLockRef.current
      wakeLockRef.current = null
      if (sentinel) sentinel.release().catch(() => {})
    }
  }, [loaded])

  // --- Image URLs (server returns already-rotated images) ---
  const rawUrl = loaded
    ? `${API}/api/frame/${frameIndex}/raw?rotate=${rotate}`
    : null

  const correctedParams = new URLSearchParams({
    rotate,
    negative,
    soundtrack_color: soundtrackColor,
    dmin_value: dminValue,
    dmin_headroom: dminHeadroom,
    binary_mask: binaryMask,
    binary_lb: binaryLb,
    binary_ub: binaryUb,
  }).toString()
  const correctedUrl = loaded
    ? `${API}/api/frame/${frameIndex}/corrected?${correctedParams}`
    : null

  // Debounced + abort-aware image sources
  const rawSrc = useDebouncedImageUrl(rawUrl)
  const correctedSrc = useDebouncedImageUrl(correctedUrl)

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
  const stereoMidPct = (leftPct + rightPct) / 2
  const stereoLeftGuidePct = leftPct + ((rightPct - leftPct) / 4)
  const stereoRightGuidePct = leftPct + (((rightPct - leftPct) * 3) / 4)

  // Overlap zone percentages
  const overlapTopPct = screenHeight > 0 ? (overlapTopY / screenHeight * 100) : 0
  const overlapBottomPct = screenHeight > 0 ? (overlapBottomY / screenHeight * 100) : 0
  const zoomPanelSize = 220
  const zoomFocusSize = Math.max(18, Math.min(90, zoomPanelSize / Math.max(zoomLevel, 1)))
  const zoomPanelMargin = 12
  const zoomPanelOffset = 24
  const zoomPanelLeft = hoverZoom
    ? Math.min(
        Math.max(
          hoverZoom.relX + zoomPanelOffset + zoomPanelSize <= hoverZoom.renderedWidth
            ? hoverZoom.relX + zoomPanelOffset
            : hoverZoom.relX - zoomPanelSize - zoomPanelOffset,
          zoomPanelMargin,
        ),
        Math.max(zoomPanelMargin, hoverZoom.renderedWidth - zoomPanelSize - zoomPanelMargin),
      )
    : zoomPanelMargin
  const zoomPanelTop = hoverZoom
    ? Math.min(
        Math.max(
          hoverZoom.relY + zoomPanelOffset + zoomPanelSize <= hoverZoom.renderedHeight
            ? hoverZoom.relY + zoomPanelOffset
            : hoverZoom.relY - zoomPanelSize - zoomPanelOffset,
          zoomPanelMargin,
        ),
        Math.max(zoomPanelMargin, hoverZoom.renderedHeight - zoomPanelSize - zoomPanelMargin),
      )
    : zoomPanelMargin
  const zoomTranslateX = hoverZoom ? (zoomPanelSize / 2) - (hoverZoom.relX * zoomLevel) : 0
  const zoomTranslateY = hoverZoom ? (zoomPanelSize / 2) - (hoverZoom.relY * zoomLevel) : 0

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

  const handleExportSettings = useCallback(() => {
    const payload = {
      app: 'Optical2Digital',
      version: 1,
      exportedAt: new Date().toISOString(),
      inputDir,
      settings: {
        cropTop,
        trackHeight,
        cropLeft,
        cropRight,
        rotate,
        negative,
        dminValue,
        dminHeadroom,
        binaryMask,
        binaryLb,
        binaryUb,
        fps,
        sampleRate,
        hpf,
        lpf,
        overlap,
        soundtrackColor,
        reverse,
        stereo,
        showStereoGuides,
        showZoom,
        zoomLevel,
        startFrame,
        endFrame,
      },
    }

    const safeBase = (inputDir.split(/[\\/]/).filter(Boolean).pop() || 'optical2digital')
      .replace(/[^a-z0-9._-]+/gi, '_')
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${safeBase}-settings.json`
    a.click()
    URL.revokeObjectURL(url)
    setStatus(`Saved settings file: ${safeBase}-settings.json`)
  }, [inputDir, cropTop, trackHeight, cropLeft, cropRight, rotate, negative, dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb, fps, sampleRate, hpf, lpf, overlap, soundtrackColor, reverse, stereo, showStereoGuides, showZoom, zoomLevel, startFrame, endFrame])

  const handleImportSettingsFile = useCallback(async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    try {
      const text = await file.text()
      const payload = JSON.parse(text)
      const saved = payload?.settings ?? payload
      if (!saved || typeof saved !== 'object') {
        throw new Error('Invalid settings file')
      }

      if (!loaded && typeof payload?.inputDir === 'string' && payload.inputDir.trim()) {
        setInputDir(payload.inputDir)
      }

      const maxFrame = Math.max(numFrames - 1, 0)
      setCropTop(Number(saved.cropTop ?? 297))
      setTrackHeight(Number(saved.trackHeight ?? 3070))
      setCropLeft(Number(saved.cropLeft ?? 849))
      setCropRight(Number(saved.cropRight ?? 1191))
      setRotate(Number(saved.rotate ?? 0))
      setNegative(Boolean(saved.negative ?? false))
      setDminValue(Number(saved.dminValue ?? 1.0))
      setDminHeadroom(Number(saved.dminHeadroom ?? 0.2))
      setBinaryMask(Boolean(saved.binaryMask ?? false))
      setBinaryLb(Number(saved.binaryLb ?? 96))
      setBinaryUb(Number(saved.binaryUb ?? 255))
      setFps(Number(saved.fps ?? 24.0))
      setSampleRate(Number(saved.sampleRate ?? 48000))
      setHpf(Number(saved.hpf ?? 40.0))
      setLpf(Number(saved.lpf ?? 13500.0))
      setOverlap(Number(saved.overlap ?? 0.05))
      setSoundtrackColor(saved.soundtrackColor ?? 'B&W')
      setReverse(Boolean(saved.reverse ?? false))
      setStereo(Boolean(saved.stereo ?? true))
      setShowStereoGuides(Boolean(saved.showStereoGuides ?? true))
      setShowZoom(Boolean(saved.showZoom ?? true))
      setZoomLevel(Number(saved.zoomLevel ?? 6))
      setStartFrame(Math.max(0, Math.min(Number(saved.startFrame ?? 0), maxFrame)))
      setEndFrame(Math.max(0, Math.min(Number(saved.endFrame ?? maxFrame), maxFrame)))
      setStatus(`Loaded settings from ${file.name}`)
    } catch (err) {
      setStatus(`Error loading settings: ${err.message}`)
    } finally {
      e.target.value = ''
    }
  }, [loaded, numFrames])

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

  const handlePreviewMouseMove = useCallback((e) => {
    if (!showZoom || !imgRef.current) return

    const rect = imgRef.current.getBoundingClientRect()
    const relX = e.clientX - rect.left
    const relY = e.clientY - rect.top
    if (relX < 0 || relY < 0 || relX > rect.width || relY > rect.height) {
      setHoverZoom(null)
      return
    }

    const screenX = Math.round((relX / Math.max(rect.width, 1)) * Math.max(screenWidth - 1, 0))
    const screenY = Math.round((relY / Math.max(rect.height, 1)) * Math.max(screenHeight - 1, 0))

    setHoverZoom({
      relX,
      relY,
      renderedWidth: rect.width,
      renderedHeight: rect.height,
      screenX,
      screenY,
    })
  }, [showZoom, screenWidth, screenHeight])

  const handlePreviewMouseLeave = useCallback(() => {
    setHoverZoom(null)
  }, [])

  // --- Extract ---
  const handleEstimateDmin = useCallback(() => {
    if (!loaded || extracting) return
    setPickingDmin((active) => {
      const next = !active
      setStatus(next
        ? 'DMIN picker active — click a point inside the crop region.'
        : 'DMIN picker cancelled.')
      return next
    })
  }, [loaded, extracting])

  const handlePreviewClick = useCallback(async (e) => {
    if (!pickingDmin || !loaded || !imgRef.current) return

    const rect = imgRef.current.getBoundingClientRect()
    const relX = e.clientX - rect.left
    const relY = e.clientY - rect.top
    if (relX < 0 || relY < 0 || relX > rect.width || relY > rect.height) return

    const screenX = Math.round((relX / rect.width) * screenWidth)
    const screenY = Math.round((relY / rect.height) * screenHeight)

    if (screenX < cropLeft || screenX > cropRight || screenY < cropTop || screenY > cropBottom) {
      setStatus('Click inside the soundtrack crop region to sample DMIN.')
      return
    }

    try {
      const imgCrop = screenToImageCrop(cropTop, cropBottom, cropLeft, cropRight)
      const sampleX = Math.max(0, Math.min(Math.round(screenX - cropLeft), Math.max(cropRight - cropLeft - 1, 0)))
      const sampleY = Math.max(0, Math.min(Math.round(screenY - cropTop), Math.max(cropBottom - cropTop - 1, 0)))
      const params = new URLSearchParams({
        top: imgCrop.top,
        bottom: imgCrop.bottom,
        left: imgCrop.left,
        right: imgCrop.right,
        rotate,
        negative,
        soundtrack_color: soundtrackColor,
        sample_x: sampleX,
        sample_y: sampleY,
      }).toString()
      const res = await fetch(`${API}/api/frame/${frameIndex}/estimate-dmin?${params}`)
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Failed to estimate DMIN')
      }
      const data = await res.json()
      setDminValue(Number(data.dmin))
      setDminPickPoint({ x: screenX, y: screenY })
      setPickingDmin(false)
      setStatus(`Estimated DMIN=${Number(data.dmin).toFixed(4)} from picked point (${data.point_x}, ${data.point_y})`)
    } catch (e) {
      setPickingDmin(false)
      setStatus(`Error estimating DMIN: ${e.message}`)
    }
  }, [pickingDmin, loaded, cropTop, cropBottom, cropLeft, cropRight, rotate, soundtrackColor, frameIndex, screenWidth, screenHeight])

  const handleExtract = useCallback(async () => {
    setExtracting(true)
    setExtractProgress(null)

    const rangeStart = Math.max(0, Math.min(startFrame, endFrame))
    const rangeEnd = Math.min(numFrames - 1, Math.max(startFrame, endFrame))
    setFrameIndex(reverse ? rangeEnd : rangeStart)
    setStatus(`Starting extraction for frames ${rangeStart}-${rangeEnd}...`)

    try {
      const imgCrop = screenToImageCrop(cropTop, cropBottom, cropLeft, cropRight)
      const res = await fetch(`${API}/api/extract`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          top: imgCrop.top, bottom: imgCrop.bottom, left: imgCrop.left, right: imgCrop.right,
          rotate, negative,
          dmin_value: dminValue,
          dmin_headroom: dminHeadroom,
          binary_mask: binaryMask,
          binary_lb: binaryLb,
          binary_ub: binaryUb,
          fps, sample_rate: sampleRate, hpf, lpf, overlap, reverse,
          soundtrack_color: soundtrackColor,
          stereo,
          start_frame: startFrame,
          end_frame: endFrame,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Extraction failed')
      }

      // Listen for SSE progress (auto-reconnects on transient drops)
      await new Promise((resolve, reject) => {
        let resolved = false
        const connect = () => {
          const es = new EventSource(`${API}/api/extract/progress`)
          es.onmessage = (ev) => {
            const data = JSON.parse(ev.data)
            setExtractProgress(data)

            const completed = Math.max(0, Math.min(data.current ?? 0, data.total ?? 0))
            const currentFrame = reverse
              ? Math.max(rangeStart, rangeEnd - Math.max(completed - 1, 0))
              : Math.min(rangeEnd, rangeStart + Math.max(completed - 1, 0))

            if (data.total > 0 && data.current < data.total) {
              const pct = Math.round((completed / data.total) * 100)
              setStatus(`${data.phase}: frame ${currentFrame} of range ${rangeStart}-${rangeEnd} • ${completed} / ${data.total} (${pct}%)`)
              setFrameIndex(currentFrame)
            } else if (data.phase && !data.done) {
              setStatus(`${data.phase}: frame ${currentFrame} of range ${rangeStart}-${rangeEnd}...`)
              setFrameIndex(currentFrame)
            }
            if (data.done) {
              es.close()
              if (!resolved) {
                resolved = true
                data.error ? reject(new Error(data.error)) : resolve()
              }
            }
          }
          es.onerror = () => {
            es.close()
            if (resolved) return
            // Reconnect after a short delay — the job may still be running
            setTimeout(() => {
              if (resolved) return
              // Check if job is still running before reconnecting
              fetch(`${API}/api/extract/progress`)
                .then(r => {
                  if (!r.ok) throw new Error('Server gone')
                  // If we got a response, reconnect the SSE stream
                  connect()
                })
                .catch(() => {
                  if (!resolved) {
                    resolved = true
                    reject(new Error('Lost connection to server'))
                  }
                })
            }, 1000)
          }
        }
        connect()
      })

      // Download the result
      const wavRes = await fetch(`${API}/api/extract/result`)
      if (!wavRes.ok) {
        const err = await wavRes.json()
        throw new Error(err.detail || 'Failed to download result')
      }
      const blob = await wavRes.blob()
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
      setExtractProgress(null)
    }
  }, [cropTop, trackHeight, cropLeft, cropRight, rotate, negative, dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb, fps, sampleRate, hpf, lpf, overlap, soundtrackColor, reverse, stereo, startFrame, endFrame, numFrames])

  return (
    <div className="app">
      {/* Load dialog */}
      {showLoad && (
        <div className="load-overlay">
          <div className="load-dialog">
            <h2>Load Frames</h2>
            <input
              type="text"
              value={inputDir}
              onChange={e => setInputDir(e.target.value)}
              placeholder="Path to image directory or video file..."
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
        <h1>Optical2Digital</h1>
        {loaded && (
          <>
            <span className="project-info">{numFrames} frames • {frameWidth}×{frameHeight}</span>
            <div className="header-actions">
              <button className="btn-secondary btn-small" onClick={handleExportSettings}>
                Save Settings
              </button>
              <button className="btn-secondary btn-small" onClick={() => importSettingsRef.current?.click()}>
                Load Settings
              </button>
              <button className="btn-secondary btn-small" onClick={() => setShowLoad(true)}>Change</button>
            </div>
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
              <div className="checkbox-row">
                <input type="checkbox" id="show-zoom" checked={showZoom} onChange={e => setShowZoom(e.target.checked)} />
                <label htmlFor="show-zoom">Show Hover Zoom</label>
              </div>
              <SliderInput label="Zoom ×" value={zoomLevel} onChange={setZoomLevel} min={2} max={12} step={0.5} />
            </div>
          </section>

          <input
            ref={importSettingsRef}
            type="file"
            accept=".json,application/json"
            onChange={handleImportSettingsFile}
            style={{ display: 'none' }}
          />

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
              <NumberInput label="Dmin Value" value={dminValue} onChange={setDminValue} min={0.001} max={2.0} step={0.001} />
              <button className="btn-secondary btn-small" onClick={handleEstimateDmin} disabled={!loaded || extracting}>
                {pickingDmin ? 'Cancel DMIN Picker' : 'Pick DMIN from Image'}
              </button>
              {pickingDmin && (
                <p className="hint">Click inside the crop region to sample DMIN.</p>
              )}
              <SliderInput label="Dmin Headroom" value={dminHeadroom} onChange={setDminHeadroom} min={0} max={0.5} step={0.01} />
              <div className="checkbox-row">
                <input type="checkbox" id="binary-mask" checked={binaryMask} onChange={e => setBinaryMask(e.target.checked)} />
                <label htmlFor="binary-mask">Binary mask cleanup</label>
              </div>
              <NumberInput label="Binary LB" value={binaryLb} onChange={setBinaryLb} min={0} max={255} />
              <NumberInput label="Binary UB" value={binaryUb} onChange={setBinaryUb} min={0} max={255} />
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
              <div className="control-row">
                <label>Soundtrack Color</label>
                <select value={soundtrackColor} onChange={e => setSoundtrackColor(e.target.value)}>
                  <option value="B&W">B&W</option>
                  <option value="High-Magenta">High-Magenta</option>
                  <option value="Cyan">Cyan</option>
                </select>
              </div>
              <div className="checkbox-row">
                <input type="checkbox" id="rev" checked={reverse} onChange={e => setReverse(e.target.checked)} />
                <label htmlFor="rev">Reverse frame order</label>
              </div>
              <div className="checkbox-row">
                <input type="checkbox" id="stereo" checked={stereo} onChange={e => setStereo(e.target.checked)} />
                <label htmlFor="stereo">Stereo (split L/R)</label>
              </div>
              <div className="checkbox-row">
                <input type="checkbox" id="stereo-guides" checked={showStereoGuides} onChange={e => setShowStereoGuides(e.target.checked)} />
                <label htmlFor="stereo-guides">Show Centerlines</label>
              </div>
              <NumberInput label="Start Frame" value={startFrame} onChange={setStartFrame} min={0} max={numFrames - 1} />
              <NumberInput label="End Frame" value={endFrame} onChange={setEndFrame} min={0} max={numFrames - 1} />
            </div>
          </section>

          {/* Extract */}
          <section className="extract-section">
            <h3>Extract</h3>
            <button className="btn-primary" onClick={handleExtract} disabled={!loaded || extracting}>
              {extracting ? 'Extracting...' : 'Extract Audio'}
            </button>
            <p className="hint" style={{ marginTop: 8 }}>
              Channel in use: {soundtrackChannelLabel(soundtrackColor)}
            </p>
            {extracting && extractProgress && extractProgress.total > 0 && (
              <div className="progress-bar">
                <div
                  className="progress-bar-fill"
                  style={{ width: `${Math.round((extractProgress.current / extractProgress.total) * 100)}%` }}
                />
              </div>
            )}
          </section>
        </div>

        {/* Preview with interactive crop overlay */}
        <div className="preview-area">
          <div className="crop-canvas">
            {loaded && rawUrl ? (
              <div
                className="image-wrapper"
                onClick={handlePreviewClick}
                onMouseMove={handlePreviewMouseMove}
                onMouseLeave={handlePreviewMouseLeave}
                style={{ cursor: pickingDmin ? 'crosshair' : undefined }}
              >
                <img ref={imgRef} src={rawSrc} alt={`Frame ${frameIndex}`} className="base-image" />
                {/* Corrected image clipped to crop region */}
                {correctedSrc && <img
                  src={correctedSrc} alt="" className="corrected-image"
                  style={{ clipPath: `inset(${topPct}% ${100 - rightPct}% ${100 - bottomPct}% ${leftPct}%)` }}
                />}
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
                {/* Channel guide lines */}
                {stereo && (
                  <div className="stereo-center-line" style={{
                    top: `${topPct}%`, left: `${stereoMidPct}%`,
                    height: `${bottomPct - topPct}%`,
                  }} />
                )}
                {showStereoGuides && (
                  <>
                    {stereo ? (
                      <>
                        <div className="stereo-guide-line" style={{
                          top: `${topPct}%`, left: `${stereoLeftGuidePct}%`,
                          height: `${bottomPct - topPct}%`,
                        }} />
                        <div className="stereo-guide-line" style={{
                          top: `${topPct}%`, left: `${stereoRightGuidePct}%`,
                          height: `${bottomPct - topPct}%`,
                        }} />
                      </>
                    ) : (
                      <div className="stereo-guide-line" style={{
                        top: `${topPct}%`, left: `${stereoMidPct}%`,
                        height: `${bottomPct - topPct}%`,
                      }} />
                    )}
                  </>
                )}
                {/* Crop border */}
                <div className="crop-border" style={{
                  top: `${topPct}%`, left: `${leftPct}%`,
                  width: `${rightPct - leftPct}%`, height: `${bottomPct - topPct}%`,
                }} />
                {showZoom && hoverZoom && rawSrc && (
                  <>
                    <div
                      className="zoom-focus-box"
                      style={{
                        top: `${(hoverZoom.screenY / Math.max(screenHeight, 1)) * 100}%`,
                        left: `${(hoverZoom.screenX / Math.max(screenWidth, 1)) * 100}%`,
                        width: `${zoomFocusSize}px`,
                        height: `${zoomFocusSize}px`,
                      }}
                    />
                    <div
                      className="zoom-panel"
                      style={{
                        left: `${zoomPanelLeft}px`,
                        top: `${zoomPanelTop}px`,
                      }}
                    >
                      <div
                        className="zoom-scene"
                        style={{
                          width: `${hoverZoom.renderedWidth}px`,
                          height: `${hoverZoom.renderedHeight}px`,
                          transform: `translate(${zoomTranslateX}px, ${zoomTranslateY}px) scale(${zoomLevel})`,
                        }}
                      >
                        <img src={rawSrc} alt="" className="zoom-image" />
                        {correctedSrc && (
                          <img
                            src={correctedSrc}
                            alt=""
                            className="corrected-image"
                            style={{ clipPath: `inset(${topPct}% ${100 - rightPct}% ${100 - bottomPct}% ${leftPct}%)` }}
                          />
                        )}
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
                        <div className="crop-dim" style={{ top: 0, left: 0, right: 0, height: `${topPct}%` }} />
                        <div className="crop-dim" style={{ bottom: 0, left: 0, right: 0, height: `${100 - bottomPct}%` }} />
                        <div className="crop-dim" style={{ top: `${topPct}%`, left: 0, width: `${leftPct}%`, bottom: `${100 - bottomPct}%` }} />
                        <div className="crop-dim" style={{ top: `${topPct}%`, right: 0, width: `${100 - rightPct}%`, bottom: `${100 - bottomPct}%` }} />
                        <div className="frame-line" style={{ top: `${topPct}%` }} />
                        <div className="frame-line" style={{ top: `${bottomPct}%` }} />
                        {stereo && (
                          <div className="stereo-center-line" style={{
                            top: `${topPct}%`, left: `${stereoMidPct}%`,
                            height: `${bottomPct - topPct}%`,
                          }} />
                        )}
                        {showStereoGuides && (
                          <>
                            {stereo ? (
                              <>
                                <div className="stereo-guide-line" style={{
                                  top: `${topPct}%`, left: `${stereoLeftGuidePct}%`,
                                  height: `${bottomPct - topPct}%`,
                                }} />
                                <div className="stereo-guide-line" style={{
                                  top: `${topPct}%`, left: `${stereoRightGuidePct}%`,
                                  height: `${bottomPct - topPct}%`,
                                }} />
                              </>
                            ) : (
                              <div className="stereo-guide-line" style={{
                                top: `${topPct}%`, left: `${stereoMidPct}%`,
                                height: `${bottomPct - topPct}%`,
                              }} />
                            )}
                          </>
                        )}
                        <div className="crop-border" style={{
                          top: `${topPct}%`, left: `${leftPct}%`,
                          width: `${rightPct - leftPct}%`, height: `${bottomPct - topPct}%`,
                        }} />
                        {dminPickPoint && (
                          <div
                            style={{
                              position: 'absolute',
                              top: `${(dminPickPoint.y / screenHeight) * 100}%`,
                              left: `${(dminPickPoint.x / screenWidth) * 100}%`,
                              width: 14,
                              height: 14,
                              borderRadius: '50%',
                              border: '2px solid #ffd166',
                              boxShadow: '0 0 0 1px rgba(0, 0, 0, 0.65)',
                              transform: 'translate(-50%, -50%)',
                              pointerEvents: 'none',
                            }}
                          />
                        )}
                      </div>
                      <div className="zoom-crosshair zoom-crosshair-h" />
                      <div className="zoom-crosshair zoom-crosshair-v" />
                      <div className="zoom-label">
                        Zoom ×{zoomLevel.toFixed(1)} • x {hoverZoom.screenX}, y {hoverZoom.screenY}
                      </div>
                    </div>
                  </>
                )}
                {dminPickPoint && (
                  <div
                    style={{
                      position: 'absolute',
                      top: `${(dminPickPoint.y / screenHeight) * 100}%`,
                      left: `${(dminPickPoint.x / screenWidth) * 100}%`,
                      width: 14,
                      height: 14,
                      borderRadius: '50%',
                      border: '2px solid #ffd166',
                      boxShadow: '0 0 0 1px rgba(0, 0, 0, 0.65)',
                      transform: 'translate(-50%, -50%)',
                      pointerEvents: 'none',
                    }}
                  />
                )}
                {/* Draggable move area */}
                <div
                  className="crop-move-area"
                  style={{ top: `${topPct}%`, left: `${leftPct}%`, width: `${rightPct - leftPct}%`, height: `${bottomPct - topPct}%` }}
                  onMouseDown={e => {
                    if (pickingDmin) return
                    e.preventDefault()
                    setDragState({ type: 'move', startX: e.clientX, startY: e.clientY, origTop: cropTop, origBottom: cropBottom, origLeft: cropLeft, origRight: cropRight })
                  }}
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
                    onMouseDown={e => {
                      if (pickingDmin) return
                      e.preventDefault()
                      e.stopPropagation()
                      setDragState({ type: h.type, startX: e.clientX, startY: e.clientY, origTop: cropTop, origBottom: cropBottom, origLeft: cropLeft, origRight: cropRight })
                    }}
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
        <span>By Kyle Mikolajczyk</span>
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
