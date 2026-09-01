/*
 * This file is part of Optical2Digital.
 *
 * Copyright (C) 2026 Kyle Mikolajczyk
 *
 * Optical2Digital is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * Optical2Digital is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with Optical2Digital; if not, write to the Free Software
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

/** Same debounce/abort behavior as useDebouncedImageUrl but for a JSON
 *  endpoint — returns [data, error], surfacing the server's error detail
 *  (e.g. "Overlap must be greater than 0...") so callers can render an
 *  explanatory empty state instead of failing silently. */
function useDebouncedJson(url, delay = 150) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const abortRef = useRef(null)

  useEffect(() => {
    if (!url) {
      if (abortRef.current) abortRef.current.abort()
      setData(null)
      setError(null)
      return
    }

    const timer = setTimeout(() => {
      if (abortRef.current) abortRef.current.abort()
      const ac = new AbortController()
      abortRef.current = ac

      fetch(url, { signal: ac.signal })
        .then(async r => {
          const body = await r.json()
          if (!r.ok) throw new Error(body.detail || 'Request failed')
          return body
        })
        .then(body => {
          if (ac.signal.aborted) return
          setData(body)
          setError(null)
        })
        .catch(e => {
          if (e.name === 'AbortError' || ac.signal.aborted) return
          setData(null)
          setError(e.message)
        })
    }, delay)

    return () => clearTimeout(timer)
  }, [url, delay])

  useEffect(() => () => {
    if (abortRef.current) abortRef.current.abort()
  }, [])

  return [data, error]
}

/** Same debounce/abort behavior as useDebouncedImageUrl but for a JSON
 *  endpoint — returns [data, error], surfacing the server's error detail
 *  (e.g. "Overlap must be greater than 0...") so callers can render an
 *  explanatory empty state instead of failing silently. */
function useDebouncedJson(url, delay = 150) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const abortRef = useRef(null)

  useEffect(() => {
    if (!url) {
      if (abortRef.current) abortRef.current.abort()
      setData(null)
      setError(null)
      return
    }

    const timer = setTimeout(() => {
      if (abortRef.current) abortRef.current.abort()
      const ac = new AbortController()
      abortRef.current = ac

      fetch(url, { signal: ac.signal })
        .then(async r => {
          const body = await r.json()
          if (!r.ok) throw new Error(body.detail || 'Request failed')
          return body
        })
        .then(body => {
          if (ac.signal.aborted) return
          setData(body)
          setError(null)
        })
        .catch(e => {
          if (e.name === 'AbortError' || ac.signal.aborted) return
          setData(null)
          setError(e.message)
        })
    }, delay)

    return () => clearTimeout(timer)
  }, [url, delay])

  useEffect(() => () => {
    if (abortRef.current) abortRef.current.abort()
  }, [])

  return [data, error]
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

// Non-drop-frame HH:MM:SS:FF timecode, using the nominal (rounded) fps as
// the frames-per-second component — this tool doesn't need broadcast-grade
// drop-frame accounting, just a human-readable alternative to a raw frame
// number.
function timecodeFps(fps) {
  return Math.max(1, Math.round(fps) || 24)
}

function framesToTimecode(frame, fps) {
  const fpsInt = timecodeFps(fps)
  const total = Math.max(0, Math.trunc(frame) || 0)
  const ff = total % fpsInt
  const totalSecs = Math.floor(total / fpsInt)
  const ss = totalSecs % 60
  const mm = Math.floor(totalSecs / 60) % 60
  const hh = Math.floor(totalSecs / 3600)
  const pad = n => String(n).padStart(2, '0')
  return `${pad(hh)}:${pad(mm)}:${pad(ss)}:${pad(ff)}`
}

// Returns the frame number for "HH:MM:SS:FF" (or ...;FF), or null if the
// text isn't a valid timecode for the given fps.
function timecodeToFrames(text, fps) {
  const m = String(text).trim().match(/^(\d{1,3}):(\d{1,2}):(\d{1,2})[:;](\d{1,3})$/)
  if (!m) return null
  const [hh, mm, ss, ff] = m.slice(1).map(Number)
  const fpsInt = timecodeFps(fps)
  if (mm >= 60 || ss >= 60 || ff >= fpsInt) return null
  return (hh * 3600 + mm * 60 + ss) * fpsInt + ff
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
  const [hasNativeBrowse, setHasNativeBrowse] = useState(false)

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
  const [integrate, setIntegrate] = useState(true)

  // Extraction settings
  const [fps, setFps] = useState(24.0)
  const [sampleRate, setSampleRate] = useState(48000)
  const [bitDepth, setBitDepth] = useState('int16')
  const [hpf, setHpf] = useState(40.0)
  const [lpf, setLpf] = useState(13500.0)
  const [overlap, setOverlap] = useState(0.05)
  const [audioOffset, setAudioOffset] = useState(21)
  const [soundtrackColor, setSoundtrackColor] = useState('B&W')
  const [reverse, setReverse] = useState(false)
  const [stereo, setStereo] = useState(true)
  const [channelOrder, setChannelOrder] = useState('LR')
  const [showStereoGuides, setShowStereoGuides] = useState(true)
  const [showZoom, setShowZoom] = useState(true)
  const [zoomLevel, setZoomLevel] = useState(6)
  const [startFrame, setStartFrame] = useState(0)
  const [endFrame, setEndFrame] = useState(0)
  const [showOverlapPreview, setShowOverlapPreview] = useState(false)
  const [showOverlapPreview, setShowOverlapPreview] = useState(false)

  // Crop overlay interaction
  const imgRef = useRef(null)
  const importSettingsRef = useRef(null)
  const loadProjectRef = useRef(null)
  const [dragState, setDragState] = useState(null)
  const [extracting, setExtracting] = useState(false)
  const [cancelRequested, setCancelRequested] = useState(false)
  const [status, setStatus] = useState('')
  const [extractProgress, setExtractProgress] = useState(null)
  const [isVideoSource, setIsVideoSource] = useState(false)
  const [exportingVideo, setExportingVideo] = useState(false)
  const [exportVideoStatus, setExportVideoStatus] = useState('')
  const [exportVideoProgress, setExportVideoProgress] = useState(null)
  const [pickingDmin, setPickingDmin] = useState(false)
  const [dminPickPoint, setDminPickPoint] = useState(null)
  const [hoverZoom, setHoverZoom] = useState(null)
  const wakeLockRef = useRef(null)

  // Sidebar panel selection
  const [activePanel, setActivePanel] = useState('crop')

  // --- Detect the pywebview native-dialog bridge (packaged app only) ---
  useEffect(() => {
    if (window.pywebview?.api) {
      setHasNativeBrowse(true)
      return
    }
    const onReady = () => setHasNativeBrowse(true)
    window.addEventListener('pywebviewready', onReady)
    return () => window.removeEventListener('pywebviewready', onReady)
  }, [])

  // --- Load project ---
  const loadProject = useCallback(async (path = inputDir) => {
    setLoadError('')
    try {
      const res = await fetch(`${API}/api/load`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input_dir: path }),
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
      const saved = loadSettings(path)
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
        setIntegrate(saved.integrate ?? true)
        setFps(saved.fps ?? data.fps ?? 24.0)
        setSampleRate(saved.sampleRate ?? 48000)
        setBitDepth(saved.bitDepth ?? 'int16')
        setHpf(saved.hpf ?? 40.0)
        setLpf(saved.lpf ?? 13500.0)
        setOverlap(saved.overlap ?? 0.05)
        setAudioOffset(saved.audioOffset ?? 21)
        setSoundtrackColor(saved.soundtrackColor ?? 'B&W')
        setReverse(saved.reverse ?? false)
        setStereo(saved.stereo ?? true)
        setChannelOrder(saved.channelOrder === 'RL' ? 'RL' : 'LR')
        setShowStereoGuides(saved.showStereoGuides ?? true)
        setShowZoom(saved.showZoom ?? true)
        setZoomLevel(saved.zoomLevel ?? 6)
        setStartFrame(saved.startFrame ?? 0)
        setEndFrame(saved.endFrame ?? data.num_frames - 1)
        setShowOverlapPreview(saved.showOverlapPreview ?? false)
        setShowOverlapPreview(saved.showOverlapPreview ?? false)
      } else {
        if (data.fps != null) setFps(data.fps)
        setStartFrame(0)
        setEndFrame(data.num_frames - 1)
        // No saved crop for this path — default the soundtrack region to
        // the full frame height (top 0, track height = frame height)
        // rather than leaving whatever crop was left over from a
        // previously-loaded project (or the component's initial
        // placeholder values). Those are calibrated to one reference scan
        // size, so on a shorter frame cropTop+trackHeight could exceed the
        // frame entirely, pushing the crop box off-screen and making it
        // hard to drag back into view.
        setCropTop(0)
        setTrackHeight(data.frame_height)
      }

      setLoaded(true)
      setShowLoad(false)
      setIsVideoSource(data.fps != null)
      const label = data.fps != null ? 'video' : 'image sequence'
      setStatus(`Loaded ${data.num_frames} frames (${data.frame_width}×${data.frame_height}, ${label})`)
      return data
    } catch (e) {
      setLoadError(e.message)
    }
  }, [inputDir])

  // --- Native folder/video pickers (packaged app only, via pywebview) ---
  const handleBrowseFolder = useCallback(async () => {
    const path = await window.pywebview.api.choose_folder()
    if (!path) return
    setInputDir(path)
    loadProject(path)
  }, [loadProject])

  const handleBrowseVideo = useCallback(async () => {
    const path = await window.pywebview.api.choose_video_file()
    if (!path) return
    setInputDir(path)
    loadProject(path)
  }, [loadProject])

  // --- Auto-save settings to localStorage whenever they change ---
  useEffect(() => {
    if (!loaded) return
    saveSettings(inputDir, {
      cropTop, trackHeight, cropLeft, cropRight,
      rotate, negative,
      dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb, integrate,
      fps, sampleRate, bitDepth, hpf, lpf, overlap, audioOffset, soundtrackColor, reverse, stereo, channelOrder, showStereoGuides,
      showZoom, zoomLevel,
      startFrame, endFrame,
      showOverlapPreview,
      showOverlapPreview,
    })
  }, [loaded, inputDir, cropTop, trackHeight, cropLeft, cropRight,
      rotate, negative,
      dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb, integrate,
      fps, sampleRate, bitDepth, hpf, lpf, overlap, audioOffset, soundtrackColor, reverse, stereo, channelOrder, showStereoGuides,
      showZoom, zoomLevel,
      startFrame, endFrame,
      showOverlapPreview])
      startFrame, endFrame,
      showOverlapPreview])

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
    integrate,
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

  // --- Overlap/splice preview (bottom of current frame spliced against the
  // top of the next frame, plus a waveform of the same join) ---
  const overlapPreviewParams = (showOverlapPreview && loaded) ? (() => {
    const imgCrop = screenToImageCrop(cropTop, cropBottom, cropLeft, cropRight)
    return new URLSearchParams({
      top: imgCrop.top, bottom: imgCrop.bottom, left: imgCrop.left, right: imgCrop.right,
      rotate, negative,
      soundtrack_color: soundtrackColor,
      dmin_value: dminValue,
      dmin_headroom: dminHeadroom,
      binary_mask: binaryMask,
      binary_lb: binaryLb,
      binary_ub: binaryUb,
      integrate,
      overlap,
    })
  })() : null

  const overlapSpliceImageUrl = overlapPreviewParams
    ? `${API}/api/frame/${frameIndex}/overlap-splice-image?${overlapPreviewParams.toString()}`
    : null

  const overlapWaveformUrl = overlapPreviewParams
    ? (() => {
        const p = new URLSearchParams(overlapPreviewParams)
        p.set('stereo', stereo)
        p.set('channel_order', channelOrder)
        return `${API}/api/frame/${frameIndex}/overlap-waveform?${p.toString()}`
      })()
    : null

  const overlapSpliceSrc = useDebouncedImageUrl(overlapSpliceImageUrl)
  const [overlapWaveform, overlapWaveformError] = useDebouncedJson(overlapWaveformUrl)

  const handleExportSettings = useCallback(async () => {
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
        integrate,
        fps,
        sampleRate,
        bitDepth,
        hpf,
        lpf,
        overlap,
        audioOffset,
        soundtrackColor,
        reverse,
        stereo,
        channelOrder,
        showStereoGuides,
        showZoom,
        zoomLevel,
        startFrame,
        endFrame,
        showOverlapPreview,
        showOverlapPreview,
      },
    }

    const safeBase = (inputDir.split(/[\\/]/).filter(Boolean).pop() || 'optical2digital')
      .replace(/[^a-z0-9._-]+/gi, '_')
    const filename = `${safeBase}-settings.o2d`
    const content = JSON.stringify(payload, null, 2)

    if (hasNativeBrowse) {
      // Blob + <a download> navigates the packaged app's webview to the
      // blob: URL instead of downloading it, breaking the UI — use the
      // native Save panel instead.
      const path = await window.pywebview.api.save_text_file(filename, content)
      setStatus(path ? `Saved settings file: ${path}` : 'Save cancelled')
      return
    }

    const blob = new Blob([content], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    setStatus(`Saved settings file: ${filename}`)
  }, [hasNativeBrowse, inputDir, cropTop, trackHeight, cropLeft, cropRight, rotate, negative, dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb, integrate, fps, sampleRate, bitDepth, hpf, lpf, overlap, audioOffset, soundtrackColor, reverse, stereo, channelOrder, showStereoGuides, showZoom, zoomLevel, startFrame, endFrame, showOverlapPreview])
  }, [hasNativeBrowse, inputDir, cropTop, trackHeight, cropLeft, cropRight, rotate, negative, dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb, integrate, fps, sampleRate, bitDepth, hpf, lpf, overlap, audioOffset, soundtrackColor, reverse, stereo, channelOrder, showStereoGuides, showZoom, zoomLevel, startFrame, endFrame, showOverlapPreview])

  // Shared by handleImportSettingsFile (settings-only import) and
  // handleLoadProjectFile (.o2d project load) so both apply the same
  // field-by-field coercion/defaults instead of duplicating this block.
  const applyImportedSettings = useCallback((saved, maxFrame) => {
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
    setIntegrate(Boolean(saved.integrate ?? true))
    setFps(Number(saved.fps ?? 24.0))
    setSampleRate(Number(saved.sampleRate ?? 48000))
    setBitDepth(['int16', 'int24', 'int32', 'float32'].includes(saved.bitDepth) ? saved.bitDepth : 'int16')
    setHpf(Number(saved.hpf ?? 40.0))
    setLpf(Number(saved.lpf ?? 13500.0))
    setOverlap(Number(saved.overlap ?? 0.05))
    setAudioOffset(Number(saved.audioOffset ?? 21))
    setSoundtrackColor(saved.soundtrackColor ?? 'B&W')
    setReverse(Boolean(saved.reverse ?? false))
    setStereo(Boolean(saved.stereo ?? true))
    setChannelOrder(saved.channelOrder === 'RL' ? 'RL' : 'LR')
    setShowStereoGuides(Boolean(saved.showStereoGuides ?? true))
    setShowZoom(Boolean(saved.showZoom ?? true))
    setZoomLevel(Number(saved.zoomLevel ?? 6))
    setStartFrame(Math.max(0, Math.min(Number(saved.startFrame ?? 0), maxFrame)))
    setEndFrame(Math.max(0, Math.min(Number(saved.endFrame ?? maxFrame), maxFrame)))
    setShowOverlapPreview(Boolean(saved.showOverlapPreview ?? false))
    setShowOverlapPreview(Boolean(saved.showOverlapPreview ?? false))
  }, [])

  // Parses+applies settings JSON text regardless of where it came from (web
  // <input type=file> vs. the native picker below) — see the native-picker
  // comment for why there are two sources.
  const processSettingsText = useCallback((text, sourceName) => {
    try {
      const payload = JSON.parse(text)
      const saved = payload?.settings ?? payload
      if (!saved || typeof saved !== 'object') {
        throw new Error('Invalid settings file')
      }

      if (!loaded && typeof payload?.inputDir === 'string' && payload.inputDir.trim()) {
        setInputDir(payload.inputDir)
      }

      applyImportedSettings(saved, Math.max(numFrames - 1, 0))
      setStatus(`Loaded settings from ${sourceName}`)
    } catch (err) {
      setStatus(`Error loading settings: ${err.message}`)
    }
  }, [loaded, numFrames, applyImportedSettings])

  const handleImportSettingsFile = useCallback(async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      processSettingsText(await file.text(), file.name)
    } finally {
      e.target.value = ''
    }
  }, [processSettingsText])

  // --- Load an entire .o2d project file: opens the referenced folder/video
  // and applies its settings in one step (initial-screen "Load Project"). ---
  const processProjectText = useCallback(async (text, sourceName) => {
    try {
      const payload = JSON.parse(text)
      const saved = payload?.settings
      if (typeof payload?.inputDir !== 'string' || !payload.inputDir.trim() || !saved || typeof saved !== 'object') {
        throw new Error('Invalid project file')
      }

      setInputDir(payload.inputDir)
      const data = await loadProject(payload.inputDir)
      if (!data) return  // loadProject already set loadError

      applyImportedSettings(saved, Math.max(data.num_frames - 1, 0))
      setStatus(`Loaded project from ${sourceName}`)
    } catch (err) {
      setLoadError(err.message)
    }
  }, [loadProject, applyImportedSettings])

  const handleLoadProjectFile = useCallback(async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      await processProjectText(await file.text(), file.name)
    } finally {
      e.target.value = ''
    }
  }, [processProjectText])

  // --- Native .o2d/.json picker (packaged desktop app only) ---
  //
  // WKWebView (the native window's engine on macOS) maps <input accept> to
  // an NSOpenPanel filter via each extension's registered Uniform Type
  // Identifier. ".json" has a system UTI so it filters fine, but ".o2d" is
  // a custom, unregistered extension — WKWebView silently drops it from the
  // filter instead of matching it, so .o2d files never appear in the panel
  // even though .json ones do. This is the exact same limitation
  // choose_video_file() in launcher.py already works around for arbitrary
  // video extensions, by going through pywebview's own native file dialog
  // (Cocoa file_types filtering) instead of the HTML accept attribute. The
  // Api has no filesystem access from the JS side, so open_o2d_file() reads
  // the chosen file server-side and returns its content directly, mirroring
  // save_text_file()'s "native panel + direct read/write, no backend round
  // trip" pattern. Only used when hasNativeBrowse is true; the dev/browser
  // build keeps the plain <input type=file> above, since Chromium/Firefox
  // filter custom extensions correctly.
  const handleImportSettingsNative = useCallback(async () => {
    const result = await window.pywebview.api.open_o2d_file()
    if (!result) return
    processSettingsText(result.content, result.path.split(/[\\/]/).pop())
  }, [processSettingsText])

  const handleLoadProjectNative = useCallback(async () => {
    const result = await window.pywebview.api.open_o2d_file()
    if (!result) return
    await processProjectText(result.content, result.path.split(/[\\/]/).pop())
  }, [processProjectText])

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
    // Ask where to save before doing any work — the packaged app's native
    // Save panel already exists, it just used to appear after the job
    // finished, which reads as broken (silent lag) and confuses users
    // about when the conversion actually started.
    let savePath = null
    if (hasNativeBrowse) {
      setStatus('Choose where to save...')
      savePath = await window.pywebview.api.choose_save_path('output.wav', ['WAV Audio (*.wav)'])
      if (!savePath) {
        setStatus('Save cancelled')
        return
      }
    }

    setExtracting(true)
    setCancelRequested(false)
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
          integrate,
          fps, sample_rate: sampleRate, bit_depth: bitDepth, hpf, lpf, overlap, audio_offset: audioOffset, reverse,
          soundtrack_color: soundtrackColor,
          stereo,
          channel_order: channelOrder,
          start_frame: startFrame,
          end_frame: endFrame,
          save_path: savePath,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Extraction failed')
      }

      // Listen for SSE progress (auto-reconnects on transient drops)
      const extractResult = await new Promise((resolve, reject) => {
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
                if (data.error) reject(new Error(data.error))
                else resolve({ cancelled: !!data.cancelled })
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

      if (extractResult.cancelled) {
        setStatus('Extraction cancelled')
        return
      }

      if (hasNativeBrowse) {
        // savePath was chosen before the job started and the backend
        // already wrote the file directly to it as the job's last step —
        // no result round trip needed here.
        setStatus(`Extraction complete — saved to ${savePath}`)
      } else {
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
      }
    } catch (e) {
      setStatus(`Error: ${e.message}`)
    } finally {
      setExtracting(false)
      setCancelRequested(false)
      setExtractProgress(null)
    }
  }, [hasNativeBrowse, cropTop, trackHeight, cropLeft, cropRight, rotate, negative, dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb, integrate, fps, sampleRate, bitDepth, hpf, lpf, overlap, audioOffset, soundtrackColor, reverse, stereo, channelOrder, startFrame, endFrame, numFrames])

  const handleCancelExtract = useCallback(async () => {
    setCancelRequested(true)
    setStatus('Cancelling extraction...')
    try {
      await fetch(`${API}/api/extract/cancel`, { method: 'POST' })
    } catch {
      // The SSE stream's own error handling will surface a real connection
      // failure; this request failing to send just means the button click
      // is a no-op, not a new error state.
    }
  }, [])

  const handleExportVideo = useCallback(async () => {
    // Ask where to save before doing any work — see handleExtract for why.
    let savePath = null
    if (hasNativeBrowse) {
      setStatus('Choose where to save...')
      savePath = await window.pywebview.api.choose_save_path('output.mp4', ['MP4 Video (*.mp4)'])
      if (!savePath) {
        setStatus('Save cancelled')
        return
      }
    }

    setExportingVideo(true)
    setCancelRequested(false)
    setExportVideoStatus('Starting...')
    setExportVideoProgress(null)
    setStatus('Starting video export...')

    const rangeStart = Math.max(0, Math.min(startFrame, endFrame))
    const rangeEnd = Math.min(numFrames - 1, Math.max(startFrame, endFrame))
    setFrameIndex(reverse ? rangeEnd : rangeStart)

    try {
      const imgCrop = screenToImageCrop(cropTop, cropBottom, cropLeft, cropRight)
      const res = await fetch(`${API}/api/export/video`, {
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
          integrate,
          fps, sample_rate: sampleRate, bit_depth: bitDepth, hpf, lpf, overlap, audio_offset: audioOffset, reverse,
          soundtrack_color: soundtrackColor,
          stereo,
          channel_order: channelOrder,
          start_frame: startFrame,
          end_frame: endFrame,
          save_path: savePath,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'Video export failed to start')
      }

      // Listen for SSE progress (auto-reconnects on transient drops)
      const exportResult = await new Promise((resolve, reject) => {
        let resolved = false
        const connect = () => {
          const es = new EventSource(`${API}/api/export/video/progress`)
          es.onmessage = (ev) => {
            const data = JSON.parse(ev.data)
            setExportVideoProgress(data)

            // Only the "Extracting audio" phase reports real per-frame
            // progress (current/total) — the ffmpeg mux/render phase that
            // follows has none (server.py zeroes both once that starts),
            // so the frame viewer simply stays parked whichever frame
            // extraction last landed on during that phase.
            if (data.total > 0 && data.current < data.total) {
              const completed = Math.max(0, Math.min(data.current, data.total))
              const currentFrame = reverse
                ? Math.max(rangeStart, rangeEnd - Math.max(completed - 1, 0))
                : Math.min(rangeEnd, rangeStart + Math.max(completed - 1, 0))
              const pct = Math.round((data.current / data.total) * 100)
              const text = `${data.phase}: ${data.current} / ${data.total} (${pct}%)`
              setExportVideoStatus(text)
              setStatus(text)
              setFrameIndex(currentFrame)
            } else if (data.phase && !data.done) {
              setExportVideoStatus(data.phase)
              setStatus(data.phase)
            }
            if (data.done) {
              es.close()
              if (!resolved) {
                resolved = true
                if (data.error) reject(new Error(data.error))
                else resolve({ cancelled: !!data.cancelled })
              }
            }
          }
          es.onerror = () => {
            es.close()
            if (resolved) return
            setTimeout(() => {
              if (resolved) return
              fetch(`${API}/api/export/video/progress`)
                .then(r => {
                  if (!r.ok) throw new Error('Server gone')
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

      if (exportResult.cancelled) {
        setStatus('Video export cancelled')
        setExportVideoStatus('Cancelled')
        return
      }

      if (hasNativeBrowse) {
        // savePath was chosen before the job started and the backend
        // already wrote the file directly to it as the job's last step —
        // no result round trip needed here.
        setStatus(`Video export complete — saved to ${savePath}`)
      } else {
        // Download the result
        const videoRes = await fetch(`${API}/api/export/video/result`)
        if (!videoRes.ok) {
          const err = await videoRes.json()
          throw new Error(err.detail || 'Failed to download result')
        }
        const blob = await videoRes.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = 'output.mp4'
        a.click()
        URL.revokeObjectURL(url)
        setStatus('Video export complete — MP4 downloaded')
      }
    } catch (e) {
      setStatus(`Error: ${e.message}`)
      setExportVideoStatus(`Error: ${e.message}`)
    } finally {
      setExportingVideo(false)
      setCancelRequested(false)
      setExportVideoProgress(null)
    }
  }, [hasNativeBrowse, cropTop, trackHeight, cropLeft, cropRight, rotate, negative, dminValue, dminHeadroom, binaryMask, binaryLb, binaryUb, integrate, fps, sampleRate, bitDepth, hpf, lpf, overlap, audioOffset, soundtrackColor, reverse, stereo, channelOrder, startFrame, endFrame, numFrames])

  const handleCancelExportVideo = useCallback(async () => {
    setCancelRequested(true)
    setStatus('Cancelling video export...')
    setExportVideoStatus('Cancelling...')
    try {
      await fetch(`${API}/api/export/video/cancel`, { method: 'POST' })
    } catch {
      // As with handleCancelExtract: a failed cancel request just means
      // the click was a no-op, not a new error state.
    }
  }, [])

  return (
    <div className="app">
      {/* Load dialog */}
      {showLoad && (
        <div className="load-overlay">
          <div className="load-dialog">
            <h2>Load Frames</h2>
            <div className="browse-actions">
              <button className="btn-secondary" onClick={hasNativeBrowse ? handleLoadProjectNative : () => loadProjectRef.current?.click()}>Load Project…</button>
              {hasNativeBrowse && (
                <>
                  <button className="btn-secondary" onClick={handleBrowseFolder}>Browse Folder…</button>
                  <button className="btn-secondary" onClick={handleBrowseVideo}>Browse Video File…</button>
                </>
              )}
            </div>
            <input
              ref={loadProjectRef}
              type="file"
              accept=".o2d,.json,application/json"
              onChange={handleLoadProjectFile}
              style={{ display: 'none' }}
            />
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
              <button className="btn-primary" onClick={() => loadProject()}>Load</button>
            </div>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="header">
        <div className="header-top">
          <h1>Optical2Digital</h1>
          {loaded && (
            <>
              <span className="project-info">{numFrames} frames • {frameWidth}×{frameHeight}</span>
              <div className="header-actions">
                <button className="btn-secondary btn-small" onClick={handleExportSettings}>
                  Save Settings
                </button>
                <button className="btn-secondary btn-small" onClick={hasNativeBrowse ? handleImportSettingsNative : () => importSettingsRef.current?.click()}>
                  Load Settings
                </button>
                <button className="btn-secondary btn-small" onClick={() => setShowLoad(true)}>Change</button>
              </div>
            </>
          )}
        </div>
        <div className="header-tabs tab-bar">
          <button type="button" className={activePanel === 'crop' ? 'active' : undefined} onClick={() => setActivePanel('crop')}>Crop Region</button>
          <button type="button" className={activePanel === 'corrections' ? 'active' : undefined} onClick={() => setActivePanel('corrections')}>Image Corrections</button>
          <button type="button" className={activePanel === 'audio' ? 'active' : undefined} onClick={() => setActivePanel('audio')}>Audio Settings</button>
          <button type="button" className={activePanel === 'export' ? 'active' : undefined} onClick={() => setActivePanel('export')}>Export</button>
        </div>
      </div>

      <div className="main">
        {/* Sidebar */}
        <div className="sidebar">
          {/* Pixel value mode — always visible, shared across all panels */}
          <div className="mode-toggle" role="radiogroup" aria-label="Pixel value mode">
            <button
              type="button"
              role="radio"
              aria-checked={integrate}
              className={integrate ? 'active' : undefined}
              onClick={() => setIntegrate(true)}
            >
              Average Pixel Value
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={!integrate}
              className={!integrate ? 'active' : undefined}
              onClick={() => setIntegrate(false)}
            >
              Binary Pixel Value
            </button>
          </div>

          {/* Crop */}
          {activePanel === 'crop' && (
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
                <SliderInput label="Overlap/Jitter" value={overlap} onChange={setOverlap} min={0} max={0.5} step={0.01} />
              </div>
            </section>
          )}

          <input
            ref={importSettingsRef}
            type="file"
            accept=".o2d,.json,application/json"
            onChange={handleImportSettingsFile}
            style={{ display: 'none' }}
          />

          {/* Rotation */}
          {activePanel === 'crop' && (
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
          )}

          {/* Corrections */}
          {activePanel === 'corrections' && (
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
                {!integrate && (
                  <>
                    <div className="checkbox-row">
                      <input type="checkbox" id="binary-mask" checked={binaryMask} onChange={e => setBinaryMask(e.target.checked)} />
                      <label htmlFor="binary-mask">Binary mask cleanup</label>
                    </div>
                    <NumberInput label="Binary LB" value={binaryLb} onChange={setBinaryLb} min={0} max={255} />
                    <NumberInput label="Binary UB" value={binaryUb} onChange={setBinaryUb} min={0} max={255} />
                  </>
                )}
              </div>
            </section>
          )}

          {/* Audio / Extraction */}
          {activePanel === 'audio' && (
            <section>
              <h3>Audio Settings</h3>
              <div className="control-group">
                <NumberInput label="FPS" value={fps} onChange={setFps} min={1} max={120} step={0.001} />
                <NumberInput label="Sample Rate" value={sampleRate} onChange={setSampleRate} min={8000} max={192000} />
                <div className="control-row">
                  <label>Bit Depth</label>
                  <select value={bitDepth} onChange={e => setBitDepth(e.target.value)}>
                    <option value="int16">16-bit</option>
                    <option value="int24">24-bit</option>
                    <option value="int32">32-bit</option>
                    <option value="float32">32-bit float</option>
                  </select>
                </div>
                <SliderInput label="HPF (Hz)" value={hpf} onChange={setHpf} min={0} max={500} step={1} />
                <SliderInput label="LPF (Hz)" value={lpf} onChange={setLpf} min={1000} max={24000} step={100} />
                <NumberInput label="Audio Offset (frames)" value={audioOffset} onChange={setAudioOffset} min={-500} max={500} />
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
                <div className="control-row">
                  <label htmlFor="channel-order">Channel Order</label>
                  <select
                    id="channel-order"
                    value={channelOrder}
                    onChange={e => setChannelOrder(e.target.value)}
                    disabled={!stereo}
                  >
                    <option value="LR">L, R (default)</option>
                    <option value="RL">R, L (flipped)</option>
                  </select>
                </div>
                <div className="checkbox-row">
                  <input type="checkbox" id="stereo-guides" checked={showStereoGuides} onChange={e => setShowStereoGuides(e.target.checked)} />
                  <label htmlFor="stereo-guides">Show Centerlines</label>
                </div>
              </div>
            </section>
          )}

          {/* Start/End frame — always visible, shared across all panels */}
          <div className="control-group">
            <FrameTimecodeInput label="Start Frame" value={startFrame} onChange={setStartFrame} min={0} max={numFrames - 1} fps={fps} />
            <FrameTimecodeInput label="End Frame" value={endFrame} onChange={setEndFrame} min={0} max={numFrames - 1} fps={fps} />
          </div>

          {/* Export */}
          {activePanel === 'export' && (
            <section className="extract-section">
              <h3>Export WAV</h3>
              <div className="button-row">
                <button className="btn-primary" onClick={handleExtract} disabled={!loaded || extracting || exportingVideo}>
                  {extracting ? 'Extracting...' : 'Export Audio (WAV)'}
                </button>
                {extracting && (
                  <button className="btn-secondary" onClick={handleCancelExtract} disabled={cancelRequested}>
                    {cancelRequested ? 'Cancelling…' : 'Cancel'}
                  </button>
                )}
              </div>
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
          )}

          {activePanel === 'export' && (
            <section className="extract-section">
              <h3>Export Video</h3>
              <p className="hint">
                {isVideoSource
                  ? 'Replaces the audio track of the original video with the extracted soundtrack, trimmed to the Start/End Frame range above. The picture is copied without re-encoding.'
                  : 'Renders the full original scan frames (Start/End Frame range, at the FPS above, with Rotation applied) into a new video with the extracted soundtrack as its audio.'}
              </p>
              <div className="button-row">
                <button className="btn-primary" onClick={handleExportVideo} disabled={!loaded || extracting || exportingVideo}>
                  {exportingVideo ? 'Exporting...' : 'Export Video (MP4)'}
                </button>
                {exportingVideo && (
                  <button className="btn-secondary" onClick={handleCancelExportVideo} disabled={cancelRequested}>
                    {cancelRequested ? 'Cancelling…' : 'Cancel'}
                  </button>
                )}
              </div>
              {exportingVideo && (
                <p className="hint" style={{ marginTop: 8 }}>{exportVideoStatus}</p>
              )}
              {exportingVideo && exportVideoProgress && exportVideoProgress.total > 0 && (
                <div className="progress-bar">
                  <div
                    className="progress-bar-fill"
                    style={{ width: `${Math.round((exportVideoProgress.current / exportVideoProgress.total) * 100)}%` }}
                  />
                </div>
              )}
            </section>
          )}
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
              <button
                className="btn-secondary btn-small"
                aria-pressed={showOverlapPreview}
                title="Preview the audio splice between this frame and the next"
                onClick={() => setShowOverlapPreview(v => !v)}
              >
                {showOverlapPreview ? 'Hide' : 'Show'} Splice Preview
              </button>
              <button
                className="btn-secondary btn-small"
                aria-pressed={showOverlapPreview}
                title="Preview the audio splice between this frame and the next"
                onClick={() => setShowOverlapPreview(v => !v)}
              >
                {showOverlapPreview ? 'Hide' : 'Show'} Splice Preview
              </button>
            </div>
          )}
          {showOverlapPreview && loaded && (
            <div className="overlap-preview-panel">
              <div className="overlap-preview-header">
                <span>Splice Preview — Frame {frameIndex + 1} → {frameIndex + 2}</span>
                {overlapWaveform && overlapWaveform.offset > 0 && (
                  <span
                    className="overlap-preview-offset-note"
                    title="Rows of audio cross-faded between this frame and the next, out of the rows available to search (controlled by the Overlap % setting). A small number here isn't necessarily bad — it often means the two frames already lined up well and needed little blending."
                  >
                    {` — overlap ${overlapWaveform.offset} of ${overlapWaveform.max_overlap} rows searched`}
                  </span>
                )}
              </div>
              {overlapWaveformError ? (
                <p className="overlap-preview-empty">{overlapWaveformError}</p>
              ) : (
                <>
                  <div className="overlap-splice-image-wrap">
                    {overlapSpliceSrc
                      ? <img src={overlapSpliceSrc} alt="Splice between current and next frame" className="overlap-splice-image" />
                      : <p className="overlap-preview-empty">Loading splice preview…</p>}
                    <div className="overlap-splice-join-line" />
                    {overlapWaveform && overlapWaveform.offset > 0 && (
                      <div
                        className="overlap-splice-marker"
                        style={{
                          top: `${((overlapWaveform.max_overlap - overlapWaveform.offset) / (overlapWaveform.max_overlap * 2)) * 100}%`,
                          height: `${(overlapWaveform.offset / overlapWaveform.max_overlap) * 100}%`,
                        }}
                        title={`Selected overlap: ${overlapWaveform.offset} of ${overlapWaveform.max_overlap} rows — the rows cross-faded together at the actual splice point.`}
                      />
                    )}
                  </div>
                  {overlapWaveform && (
                    <div className="overlap-waveform-charts">
                      <div className="overlap-waveform-legend">
                        <span
                          className="legend-item"
                          title="The current frame's last audio rows, unmodified — the raw signal under the shaded overlap zone at the bottom of the frame you're viewing."
                        >
                          <span className="legend-swatch legend-prev" />Current frame (tail)
                        </span>
                        <span
                          className="legend-item"
                          title="The next frame's first audio rows, unmodified — the raw signal under the shaded overlap zone at the top of the next frame."
                        >
                          <span className="legend-swatch legend-next" />Next frame (head)
                        </span>
                        <span
                          className="legend-item"
                          title="What actually gets written to the output track at this join: identical to the raw signal outside the shaded band, cross-faded between the two frames inside it."
                        >
                          <span className="legend-swatch legend-stitched" />Stitched output
                        </span>
                      </div>
                      {overlapWaveform.stereo ? (
                        <>
                          <OverlapWaveformChart
                            label="Left channel" data={overlapWaveform.channels.left}
                            offset={overlapWaveform.offset} maxOverlap={overlapWaveform.max_overlap}
                          />
                          <OverlapWaveformChart
                            label="Right channel" data={overlapWaveform.channels.right}
                            offset={overlapWaveform.offset} maxOverlap={overlapWaveform.max_overlap}
                          />
                        </>
                      ) : (
                        <OverlapWaveformChart
                          label="Mono" data={overlapWaveform.channels.mono}
                          offset={overlapWaveform.offset} maxOverlap={overlapWaveform.max_overlap}
                        />
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Status bar */}
      <div className="status-bar">
        <span>{status}</span>
        <a href="https://optical2digital.org" target="_blank" rel="noopener noreferrer">optical2digital.org</a>
      </div>
    </div>
  )
}

// Alignment-error thresholds, as a % mismatch of full-scale amplitude.
// Below ERROR_GOOD_PCT: negligible, inaudible. Below ERROR_WARN_PCT: may be
// audible on a quiet passage. Above that: likely an audible pop/click.
const ERROR_GOOD_PCT = 2
const ERROR_WARN_PCT = 5

function alignmentErrorLevel(errorPct) {
  if (errorPct < ERROR_GOOD_PCT) return 'good'
  if (errorPct < ERROR_WARN_PCT) return 'warn'
  return 'bad'
}

/** Plots the overlap join between two frames' audio as three overlaid
 *  polylines — the current frame's tail, the next frame's head, and the
 *  actual cross-faded stitched output — so a bad splice (the prev/next
 *  lines diverging inside the shaded overlap band) is visible at a glance. */
function OverlapWaveformChart({ label, data, offset, maxOverlap }) {
  if (!data || maxOverlap <= 0) return null

  const width = 400
  const height = 90
  const pad = 4
  const n = maxOverlap * 2

  // Punch into just the cross-fade band (±offset rows around the join) plus
  // a ~50% margin, instead of the full frame-length context — the join is
  // what matters, and at the full width it's a few pixels wide.
  const bandMargin = offset > 0 ? Math.max(1, offset * 0.5) : 0
  const bandStart = offset > 0 ? Math.max(0, maxOverlap - offset - bandMargin) : 0
  const bandEnd = offset > 0 ? Math.min(n, maxOverlap + offset + bandMargin) : n

  // On top of that, show a slice of the untouched raw waveform outside the
  // merge zone too — 10% of the zoomed window's width, added to each side —
  // so the blended region can be seen in the context of what precedes/
  // follows it rather than filling the whole chart on its own.
  const contextMargin = offset > 0 ? (bandEnd - bandStart) * 0.1 : 0
  let domainStart = Math.max(0, bandStart - contextMargin)
  let domainEnd = Math.min(n, bandEnd + contextMargin)

  // The above is all proportional to offset, so a very small offset (a
  // near-perfect alignment needing almost no blending) produces a window
  // just a handful of samples wide — technically correct, but too sparse
  // to read as a waveform. Floor the window to a minimum sample count,
  // re-centered on the join, regardless of how small offset is.
  const MIN_VISIBLE_SAMPLES = 24
  if (domainEnd - domainStart < MIN_VISIBLE_SAMPLES) {
    const center = (domainStart + domainEnd) / 2
    domainStart = Math.max(0, center - MIN_VISIBLE_SAMPLES / 2)
    domainEnd = Math.min(n, domainStart + MIN_VISIBLE_SAMPLES)
    domainStart = Math.max(0, domainEnd - MIN_VISIBLE_SAMPLES)
  }

  const domainWidth = Math.max(domainEnd - domainStart, 1)

  const xFor = i => pad + ((i - domainStart) / domainWidth) * (width - pad * 2)
  const yFor = v => pad + (1 - Math.min(Math.max(v, 0), 1)) * (height - pad * 2)
  const pointsFor = (arr, xOffset) => arr.map((v, i) => `${xFor(i + xOffset)},${yFor(v)}`).join(' ')
  // One <circle> per actual sample — these are discrete audio-sample rows,
  // not a continuous signal, so mark each one rather than only implying
  // them through the connecting line.
  const dotsFor = (arr, xOffset, className) =>
    arr.map((v, i) => (
      <circle key={i} cx={xFor(i + xOffset)} cy={yFor(v)} r={1.6} className={className} />
    ))

  const prevPoints = pointsFor(data.context_prev, 0)
  const nextPoints = pointsFor(data.context_next, maxOverlap)
  const stitchedPoints = pointsFor(data.stitched, 0)
  const joinX = xFor(maxOverlap)
  const bandX1 = xFor(maxOverlap - offset)
  const bandX2 = xFor(maxOverlap + offset)

  const errorPct = data.error * 100
  const errorLevel = alignmentErrorLevel(errorPct)

  return (
    <div className="overlap-waveform-chart">
      <div className="overlap-waveform-chart-label">
        {label} — alignment error{' '}
        <span
          className={`alignment-error alignment-error-${errorLevel}`}
          title={`Mean brightness mismatch between the current frame's tail and the next frame's head, over the ${offset}-row cross-fade window, as a % of full-scale amplitude. Below ${ERROR_GOOD_PCT}% is a clean, inaudible splice; ${ERROR_GOOD_PCT}–${ERROR_WARN_PCT}% may be faintly audible; above ${ERROR_WARN_PCT}% is likely an audible pop or click.`}
        >
          {errorPct.toFixed(1)}%
        </span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="overlap-waveform-svg">
        {offset > 0 && (
          <rect x={bandX1} y={0} width={bandX2 - bandX1} height={height} className="overlap-waveform-band">
            <title>{`Cross-fade window — the ${offset} of ${maxOverlap} searched rows the algorithm blends between the two frames to make the join seamless. Outside this band the stitched line is just the raw signal.`}</title>
          </rect>
        )}
        <line x1={joinX} y1={0} x2={joinX} y2={height} className="overlap-waveform-join">
          <title>Frame boundary — where the current frame's tail and the next frame's head meet before any alignment or blending is applied.</title>
        </line>
        <polyline points={prevPoints} className="overlap-waveform-line overlap-waveform-line-prev">
          <title>Current frame's tail (raw, unmodified audio)</title>
        </polyline>
        <polyline points={nextPoints} className="overlap-waveform-line overlap-waveform-line-next">
          <title>Next frame's head (raw, unmodified audio)</title>
        </polyline>
        <polyline points={stitchedPoints} className="overlap-waveform-line overlap-waveform-line-stitched">
          <title>Stitched output — the actual audio written to the track at this join (cross-faded inside the shaded band, raw outside it)</title>
        </polyline>
        <g className="overlap-waveform-points">
          {dotsFor(data.context_prev, 0, 'overlap-waveform-dot overlap-waveform-dot-prev')}
          {dotsFor(data.context_next, maxOverlap, 'overlap-waveform-dot overlap-waveform-dot-next')}
          {dotsFor(data.stitched, 0, 'overlap-waveform-dot overlap-waveform-dot-stitched')}
        </g>
      </svg>
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

function NumberInput({ label, value, onChange, min, max, step, disabled }) {
  return (
    <div className="control-row" style={disabled ? { opacity: 0.4 } : undefined}>
      <label>{label}</label>
      <input type="number" min={min} max={max} step={step || 1} value={value}
        onChange={e => onChange(Number(e.target.value))} disabled={disabled} />
    </div>
  )
}

// Frame-number input paired with an editable HH:MM:SS:FF timecode field for
// the same value — either one can be used to set the frame; they stay in
// sync via the shared `value`/`onChange`.
function FrameTimecodeInput({ label, value, onChange, min, max, fps }) {
  const [tcText, setTcText] = useState(() => framesToTimecode(value, fps))

  // Re-derive the displayed timecode whenever the underlying frame (or fps)
  // changes — including right after a successful commit below, which
  // reformats/clamps whatever the user typed into canonical form. This
  // never fights the user's typing because `value` doesn't change on each
  // keystroke here, only on commit or on external frame changes.
  useEffect(() => {
    setTcText(framesToTimecode(value, fps))
  }, [value, fps])

  const commitTimecode = () => {
    const parsed = timecodeToFrames(tcText, fps)
    if (parsed == null) {
      setTcText(framesToTimecode(value, fps))  // invalid text — revert
      return
    }
    onChange(Math.max(min, Math.min(parsed, max)))
  }

  return (
    <div className="control-row">
      <label>{label}</label>
      <input type="number" min={min} max={max} step={1} value={value}
        onChange={e => onChange(Number(e.target.value))} />
      <input
        type="text"
        className="timecode-input"
        value={tcText}
        onChange={e => setTcText(e.target.value)}
        onBlur={commitTimecode}
        onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
        placeholder="HH:MM:SS:FF"
        title="HH:MM:SS:FF timecode"
      />
    </div>
  )
}

export default App
