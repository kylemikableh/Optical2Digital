"""
Web server for Optical2Digital.

Run:  python server.py
Then open http://localhost:8000 in your browser.

This file is part of Optical2Digital.

Copyright (C) 2026 Kyle Mikolajczyk

Optical2Digital is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

Optical2Digital is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Optical2Digital; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""

import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import KylesOpticalDecoder as decoder

app = FastAPI(title="Optical2Digital")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if shutil.which("ffmpeg") is None:
    print(
        "WARNING: ffmpeg not found on PATH — video export will be unavailable "
        "until it is installed.",
        file=sys.stderr,
    )

# ---------------------------------------------------------------------------
# State — currently loaded project
# ---------------------------------------------------------------------------

_state = {
    "source": None,
    "input_dir": None,
}

# Extraction job state
_extract_job = {
    "running": False,
    "current": 0,
    "total": 0,
    "phase": "",
    "done": False,
    "error": None,
    "cancelled": False,
    "cancel_event": None,
    "wav_bytes": None,
    "stats": None,
}

# Video export job state
_export_video_job = {
    "running": False,
    "current": 0,
    "total": 0,
    "phase": "",
    "done": False,
    "error": None,
    "cancelled": False,
    "cancel_event": None,
    "video_bytes": None,
    "stats": None,
}


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

class LoadProjectRequest(BaseModel):
    input_dir: str

class LoadProjectResponse(BaseModel):
    num_frames: int
    frame_width: int
    frame_height: int
    fps: float | None = None

@app.post("/api/load", response_model=LoadProjectResponse)
def load_project(req: LoadProjectRequest):
    """Point the server at a directory of frame images or a video file."""
    try:
        source = decoder.open_source(req.input_dir)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    _state["source"] = source
    _state["input_dir"] = req.input_dir

    return LoadProjectResponse(
        num_frames=source.num_frames,
        frame_width=source.frame_width,
        frame_height=source.frame_height,
        fps=source.fps,
    )


@app.get("/api/frame/{index}/raw")
def get_raw_frame(index: int, rotate: int = Query(0)):
    """Return the raw (uncropped) frame as a JPEG for preview."""
    _check_loaded()
    source = _state["source"]
    if index < 0 or index >= source.num_frames:
        raise HTTPException(404, f"Frame index {index} out of range (0–{source.num_frames - 1})")
    img = source.load_frame(index)
    if img is None:
        raise HTTPException(500, f"Could not read frame {index}")
    img = decoder.rotate_image(img, rotate)
    return Response(content=decoder.frame_to_jpeg(img), media_type="image/jpeg")


@app.get("/api/frame/{index}/corrected")
def get_corrected_frame(
    index: int,
    rotate: int = Query(0),
    negative: bool = Query(False),
    soundtrack_color: Literal["B&W", "High-Magenta", "Cyan"] = Query("B&W"),
    dmin_percentile: float = Query(99.5),
    dmin_value: float | None = Query(None),
    dmin_headroom: float = Query(0.2),
    binary_mask: bool = Query(False),
    binary_lb: int = Query(96),
    binary_ub: int = Query(255),
    integrate: bool = Query(True),
):
    """Return full frame with corrections applied (no crop), rotated, as JPEG."""
    _check_loaded()
    source = _state["source"]
    if index < 0 or index >= source.num_frames:
        raise HTTPException(404, f"Frame index {index} out of range (0–{source.num_frames - 1})")
    img = source.load_frame(index)
    if img is None:
        raise HTTPException(500, f"Could not read frame {index}")
    corrected = decoder.correct_full_frame(
        img,
        negative=negative,
        soundtrack_color=soundtrack_color,
        dmin_percentile=dmin_percentile,
        dmin_headroom=dmin_headroom,
        binary_mask=binary_mask,
        binary_lb=binary_lb,
        binary_ub=binary_ub,
        dmin_value=dmin_value,
        integrate=integrate,
    )
    corrected = decoder.rotate_image(corrected, rotate)
    return Response(content=decoder.corrected_to_jpeg(corrected), media_type="image/jpeg")


@app.get("/api/frame/{index}/preview")
def get_preview_frame(
    index: int,
    top: int = Query(0),
    bottom: int = Query(0),
    left: int = Query(0),
    right: int = Query(0),
    rotate: int = Query(0),
    negative: bool = Query(False),
    soundtrack_color: Literal["B&W", "High-Magenta", "Cyan"] = Query("B&W"),
    dmin_percentile: float = Query(99.5),
    dmin_value: float | None = Query(None),
    dmin_headroom: float = Query(0.2),
    binary_mask: bool = Query(False),
    binary_lb: int = Query(96),
    binary_ub: int = Query(255),
    integrate: bool = Query(True),
):
    """Return a cropped+corrected frame as JPEG (for live preview)."""
    _check_loaded()
    source = _state["source"]
    if index < 0 or index >= source.num_frames:
        raise HTTPException(404, f"Frame index {index} out of range (0–{source.num_frames - 1})")
    img = source.load_frame(index)
    if img is None:
        raise HTTPException(500, f"Could not read frame {index}")

    corrected = decoder.crop_and_correct(
        img,
        top,
        bottom,
        left,
        right,
        rotate=rotate,
        negative=negative,
        soundtrack_color=soundtrack_color,
        dmin_percentile=dmin_percentile,
        dmin_headroom=dmin_headroom,
        binary_mask=binary_mask,
        binary_lb=binary_lb,
        binary_ub=binary_ub,
        dmin_value=dmin_value,
        integrate=integrate,
    )
    return Response(content=decoder.corrected_to_jpeg(corrected), media_type="image/jpeg")


@app.get("/api/frame/{index}/estimate-dmin")
def estimate_dmin(
    index: int,
    top: int = Query(0),
    bottom: int = Query(0),
    left: int = Query(0),
    right: int = Query(0),
    rotate: int = Query(0),
    negative: bool = Query(False),
    soundtrack_color: Literal["B&W", "High-Magenta", "Cyan"] = Query("B&W"),
    sample_x: int | None = Query(None),
    sample_y: int | None = Query(None),
):
    """Estimate Dmin from the crop center or a user-selected point."""
    _check_loaded()
    source = _state["source"]
    if index < 0 or index >= source.num_frames:
        raise HTTPException(404, f"Frame index {index} out of range (0–{source.num_frames - 1})")
    img = source.load_frame(index)
    if img is None:
        raise HTTPException(500, f"Could not read frame {index}")
    try:
        dmin, point_x, point_y, point_u8 = decoder.estimate_dmin_from_track_point(
            img, top, bottom, left, right, rotate, soundtrack_color, sample_x, sample_y, negative
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {
        "dmin": dmin,
        "point_x": point_x,
        "point_y": point_y,
        "point_u8": point_u8,
        "center_x": point_x,
        "center_y": point_y,
        "center_u8": point_u8,
    }


@app.get("/api/frame/{index}/overlap-splice-image")
def get_overlap_splice_image(
    index: int,
    top: int = Query(0),
    bottom: int = Query(0),
    left: int = Query(0),
    right: int = Query(0),
    rotate: int = Query(0),
    negative: bool = Query(False),
    soundtrack_color: Literal["B&W", "High-Magenta", "Cyan"] = Query("B&W"),
    dmin_percentile: float = Query(99.5),
    dmin_value: float | None = Query(None),
    dmin_headroom: float = Query(0.2),
    binary_mask: bool = Query(False),
    binary_lb: int = Query(96),
    binary_ub: int = Query(255),
    integrate: bool = Query(True),
    overlap: float = Query(0.05),
):
    """Return a JPEG of the bottom of the current frame's crop stacked
    against the top of the next frame's crop, spanning the overlap
    search window, for visual inspection of the splice."""
    _check_loaded()
    source = _state["source"]
    try:
        corrected_a, corrected_b, _, _ = decoder._load_overlap_frame_pair(
            source, index, top, bottom, left, right,
            rotate=rotate, negative=negative, soundtrack_color=soundtrack_color,
            dmin_percentile=dmin_percentile, dmin_headroom=dmin_headroom,
            binary_mask=binary_mask, binary_lb=binary_lb, binary_ub=binary_ub,
            dmin_value=dmin_value, integrate=integrate,
        )
        splice_img = decoder.build_overlap_splice_image(corrected_a, corrected_b, overlap)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return Response(content=decoder.corrected_to_jpeg(splice_img), media_type="image/jpeg")


@app.get("/api/frame/{index}/overlap-waveform")
def get_overlap_waveform(
    index: int,
    top: int = Query(0),
    bottom: int = Query(0),
    left: int = Query(0),
    right: int = Query(0),
    rotate: int = Query(0),
    negative: bool = Query(False),
    soundtrack_color: Literal["B&W", "High-Magenta", "Cyan"] = Query("B&W"),
    dmin_percentile: float = Query(99.5),
    dmin_value: float | None = Query(None),
    dmin_headroom: float = Query(0.2),
    binary_mask: bool = Query(False),
    binary_lb: int = Query(96),
    binary_ub: int = Query(255),
    integrate: bool = Query(True),
    overlap: float = Query(0.05),
    stereo: bool = Query(False),
    channel_order: Literal["LR", "RL"] = Query("LR"),
    forced_offset: int | None = Query(None),
):
    """Return the sample data for the overlap join between the current and
    next frame, so the UI can plot it and flag a non-seamless splice.

    *forced_offset*, if given, skips the auto-search and applies this fixed
    offset instead -- used by the frontend's "Locked" overlap mode so paging
    through frame pairs shows what the single locked offset does to each one."""
    _check_loaded()
    source = _state["source"]
    try:
        corrected_a, corrected_b, prev_idx, next_idx = decoder._load_overlap_frame_pair(
            source, index, top, bottom, left, right,
            rotate=rotate, negative=negative, soundtrack_color=soundtrack_color,
            dmin_percentile=dmin_percentile, dmin_headroom=dmin_headroom,
            binary_mask=binary_mask, binary_lb=binary_lb, binary_ub=binary_ub,
            dmin_value=dmin_value, integrate=integrate,
        )
        result = decoder.compute_overlap_waveform(
            corrected_a, corrected_b, overlap, stereo=stereo, channel_order=channel_order,
            forced_offset=forced_offset,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    result["prev_frame"] = prev_idx
    result["next_frame"] = next_idx
    return result


class ExtractRequest(BaseModel):
    top: int
    bottom: int
    left: int
    right: int
    rotate: int = 0
    negative: bool = False
    dmin_percentile: float = 99.5
    dmin_value: float | None = None
    dmin_headroom: float = 0.2
    binary_mask: bool = False
    binary_lb: int = 96
    binary_ub: int = 255
    integrate: bool = True
    fps: float = 24.0
    sample_rate: int = 48000
    hpf: float = 40.0
    lpf: float = 13500.0
    overlap: float = 0.25
    overlap_mode: Literal["auto", "locked"] = "auto"
    locked_offset: int = 0
    audio_offset: int = 21
    soundtrack_color: Literal["B&W", "High-Magenta", "Cyan"] = "B&W"
    reverse: bool = False
    stereo: bool = False
    channel_order: Literal["LR", "RL"] = "LR"
    start_frame: int = 0
    end_frame: int | None = None
    bit_depth: Literal["int16", "int24", "int32", "float32"] = "int16"
    save_path: str | None = None


@app.post("/api/extract")
def extract(req: ExtractRequest):
    """Start the extraction pipeline in a background thread."""
    _check_loaded()

    if _extract_job["running"]:
        raise HTTPException(409, "Extraction already in progress")
    if _export_video_job["running"]:
        raise HTTPException(409, "Cannot extract while a video export is in progress")

    source = _state["source"]

    start = max(0, req.start_frame)
    end = req.end_frame if req.end_frame is not None else source.num_frames - 1
    end = min(end, source.num_frames - 1)
    frame_count = end - start + 1

    _extract_job["running"] = True
    _extract_job["current"] = 0
    _extract_job["total"] = frame_count
    _extract_job["phase"] = "Processing frames"
    _extract_job["done"] = False
    _extract_job["error"] = None
    _extract_job["cancelled"] = False
    _extract_job["cancel_event"] = threading.Event()
    _extract_job["wav_bytes"] = None
    _extract_job["saved_path"] = None
    _extract_job["stats"] = None
    save_path = req.save_path
    start_time = time.time()

    def _run():
        try:
            def progress_cb(current, total):
                _extract_job["current"] = current
                _extract_job["total"] = total

            def phase_cb(phase):
                _extract_job["phase"] = phase

            wav_bytes = decoder.extract_audio_to_wav_bytes(
                source,
                top=req.top,
                bottom=req.bottom,
                left=req.left,
                right=req.right,
                rotate=req.rotate,
                negative=req.negative,
                dmin_percentile=req.dmin_percentile,
                dmin_value=req.dmin_value,
                dmin_headroom=req.dmin_headroom,
                binary_mask=req.binary_mask,
                binary_lb=req.binary_lb,
                binary_ub=req.binary_ub,
                integrate=req.integrate,
                fps=req.fps,
                sample_rate=req.sample_rate,
                hpf=req.hpf,
                lpf=req.lpf,
                overlap=req.overlap,
                overlap_mode=req.overlap_mode,
                locked_offset=req.locked_offset,
                audio_offset=req.audio_offset,
                soundtrack_color=req.soundtrack_color,
                stereo=req.stereo,
                channel_order=req.channel_order,
                reverse=req.reverse,
                start_frame=req.start_frame,
                end_frame=req.end_frame,
                bit_depth=req.bit_depth,
                cancel_event=_extract_job["cancel_event"],
                progress_callback=progress_cb,
                phase_callback=phase_cb,
            )
            if save_path:
                # Native Save panel flow — the path was already chosen
                # before this job started, so write straight to disk
                # instead of round-tripping the bytes back through
                # /api/extract/result.
                try:
                    with open(save_path, "wb") as f:
                        f.write(wav_bytes)
                    _extract_job["saved_path"] = save_path
                except OSError as e:
                    if os.path.exists(save_path):
                        try:
                            os.remove(save_path)
                        except OSError:
                            pass
                    raise RuntimeError(f"Failed to save file: {e}") from e
            else:
                _extract_job["wav_bytes"] = wav_bytes
            _extract_job["stats"] = _completion_stats(
                start_time, frame_count, len(wav_bytes), save_path, wav_bytes=wav_bytes
            )
            _extract_job["phase"] = "Complete"
        except decoder.ExtractionCancelled:
            _extract_job["cancelled"] = True
            _extract_job["phase"] = "Cancelled"
            if save_path and os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except OSError:
                    pass
        except Exception as e:
            _extract_job["error"] = str(e)
            _extract_job["phase"] = "Error"
        finally:
            _extract_job["done"] = True
            _extract_job["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "total": frame_count}


@app.post("/api/extract/cancel")
def extract_cancel():
    """Signal the in-progress extraction to stop. Cancellation is
    cooperative (checked once per frame, and once more at the stitch/
    resample/filter boundary) rather than instantaneous — the job finishes
    shortly after, marked cancelled rather than errored."""
    if not _extract_job["running"]:
        raise HTTPException(409, "No extraction in progress")
    if _extract_job["cancel_event"] is not None:
        _extract_job["cancel_event"].set()
    return {"status": "cancelling"}


@app.get("/api/extract/progress")
def extract_progress():
    """SSE stream of extraction progress."""
    def event_stream():
        while True:
            data = {
                "current": _extract_job["current"],
                "total": _extract_job["total"],
                "phase": _extract_job["phase"],
                "done": _extract_job["done"],
                "error": _extract_job["error"],
                "cancelled": _extract_job["cancelled"],
                "stats": _extract_job["stats"],
            }
            yield f"data: {json.dumps(data)}\n\n"
            if _extract_job["done"]:
                break
            time.sleep(0.3)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/extract/result")
def extract_result(save_path: str | None = Query(None)):
    """Return the completed WAV file, or (if `save_path` is given, from
    the packaged app's native Save panel) write it directly to disk."""
    if _extract_job["running"]:
        raise HTTPException(409, "Extraction still in progress")
    if _extract_job["error"]:
        raise HTTPException(500, _extract_job["error"])
    if _extract_job["wav_bytes"] is None:
        raise HTTPException(404, "No extraction result available")
    wav_bytes = _extract_job["wav_bytes"]
    _extract_job["wav_bytes"] = None  # free memory
    return _respond_with_result(wav_bytes, "output.wav", "audio/wav", save_path)


@app.post("/api/export/video")
def export_video(req: ExtractRequest):
    """Start video export (mux with source video, or render from image sequence)."""
    _check_loaded()
    _check_ffmpeg()

    if _export_video_job["running"]:
        raise HTTPException(409, "Video export already in progress")
    if _extract_job["running"]:
        raise HTTPException(409, "Cannot export video while audio extraction is in progress")

    source = _state["source"]
    is_video = source.fps is not None

    start = max(0, req.start_frame)
    end = req.end_frame if req.end_frame is not None else source.num_frames - 1
    end = min(end, source.num_frames - 1)
    frame_count = end - start + 1

    _export_video_job["running"] = True
    _export_video_job["current"] = 0
    _export_video_job["total"] = frame_count
    _export_video_job["phase"] = "Starting"
    _export_video_job["done"] = False
    _export_video_job["error"] = None
    _export_video_job["cancelled"] = False
    _export_video_job["cancel_event"] = threading.Event()
    _export_video_job["video_bytes"] = None
    _export_video_job["saved_path"] = None
    _export_video_job["stats"] = None
    save_path = req.save_path
    start_time = time.time()

    def _run():
        cancel_event = _export_video_job["cancel_event"]
        try:
            with tempfile.TemporaryDirectory(prefix="o2d_export_") as tmpdir:
                def phase_cb(msg):
                    _export_video_job["phase"] = msg

                def progress_cb(current, total):
                    _export_video_job["current"] = current
                    _export_video_job["total"] = total

                phase_cb("Extracting audio")
                wav_bytes = decoder.extract_audio_to_wav_bytes(
                    source,
                    top=req.top,
                    bottom=req.bottom,
                    left=req.left,
                    right=req.right,
                    rotate=req.rotate,
                    negative=req.negative,
                    dmin_percentile=req.dmin_percentile,
                    dmin_value=req.dmin_value,
                    dmin_headroom=req.dmin_headroom,
                    binary_mask=req.binary_mask,
                    binary_lb=req.binary_lb,
                    binary_ub=req.binary_ub,
                    integrate=req.integrate,
                    fps=req.fps,
                    sample_rate=req.sample_rate,
                    hpf=req.hpf,
                    lpf=req.lpf,
                    overlap=req.overlap,
                    overlap_mode=req.overlap_mode,
                    locked_offset=req.locked_offset,
                    audio_offset=req.audio_offset,
                    soundtrack_color=req.soundtrack_color,
                    stereo=req.stereo,
                    channel_order=req.channel_order,
                    reverse=req.reverse,
                    start_frame=req.start_frame,
                    end_frame=req.end_frame,
                    bit_depth=req.bit_depth,
                    cancel_event=cancel_event,
                    progress_callback=progress_cb,
                )
                wav_path = os.path.join(tmpdir, "audio.wav")
                with open(wav_path, "wb") as f:
                    f.write(wav_bytes)

                out_path = os.path.join(tmpdir, "output.mp4")

                # Reset before the mux/render phase -- its progress is now
                # real (ffmpeg's own -progress output, see
                # _run_subprocess_cancellable), but starts back at 0 rather
                # than continuing from the audio-extraction phase's frame
                # count, which was a different unit entirely.
                _export_video_job["current"] = 0
                _export_video_job["total"] = 0

                if is_video:
                    phase_cb("Muxing video")
                    _mux_video_source(
                        source.path, wav_path, out_path, req.fps or source.fps, start, end,
                        cancel_event, progress_callback=progress_cb,
                    )
                else:
                    phase_cb("Rendering video")
                    _render_image_sequence(
                        source, wav_path, out_path, req.fps, req.rotate, start, end, tmpdir,
                        cancel_event, progress_callback=progress_cb,
                    )

                phase_cb("Finalizing")
                if save_path:
                    # Native Save panel flow — the path was already chosen
                    # before this job started. ffmpeg already wrote the
                    # finished file to out_path, so just move it straight
                    # to the destination rather than reading it back into
                    # memory and round-tripping through /api/export/video/result.
                    try:
                        shutil.move(out_path, save_path)
                        _export_video_job["saved_path"] = save_path
                        output_bytes_len = os.path.getsize(save_path)
                    except OSError as e:
                        if os.path.exists(save_path):
                            try:
                                os.remove(save_path)
                            except OSError:
                                pass
                        raise RuntimeError(f"Failed to save file: {e}") from e
                else:
                    with open(out_path, "rb") as f:
                        _export_video_job["video_bytes"] = f.read()
                    output_bytes_len = len(_export_video_job["video_bytes"])
                _export_video_job["stats"] = _completion_stats(
                    start_time, frame_count, output_bytes_len, save_path, wav_bytes=wav_bytes
                )
                _export_video_job["phase"] = "Complete"
        except decoder.ExtractionCancelled:
            _export_video_job["cancelled"] = True
            _export_video_job["phase"] = "Cancelled"
            if save_path and os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except OSError:
                    pass
        except subprocess.CalledProcessError as e:
            stderr_tail = (e.stderr or b"").decode(errors="replace")[-800:]
            _export_video_job["error"] = f"ffmpeg failed: {stderr_tail or e}"
            _export_video_job["phase"] = "Error"
        except Exception as e:
            _export_video_job["error"] = str(e)
            _export_video_job["phase"] = "Error"
        finally:
            _export_video_job["done"] = True
            _export_video_job["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}


@app.post("/api/export/video/cancel")
def export_video_cancel():
    """Signal the in-progress video export to stop — during frame
    extraction this is checked cooperatively (see /api/extract/cancel);
    during the ffmpeg mux/render step it terminates the ffmpeg process
    (see _run_subprocess_cancellable)."""
    if not _export_video_job["running"]:
        raise HTTPException(409, "No video export in progress")
    if _export_video_job["cancel_event"] is not None:
        _export_video_job["cancel_event"].set()
    return {"status": "cancelling"}


@app.get("/api/export/video/progress")
def export_video_progress():
    """SSE stream of video export phase/status."""
    def event_stream():
        while True:
            data = {
                "current": _export_video_job["current"],
                "total": _export_video_job["total"],
                "phase": _export_video_job["phase"],
                "done": _export_video_job["done"],
                "error": _export_video_job["error"],
                "cancelled": _export_video_job["cancelled"],
                "stats": _export_video_job["stats"],
            }
            yield f"data: {json.dumps(data)}\n\n"
            if _export_video_job["done"]:
                break
            time.sleep(0.3)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/export/video/result")
def export_video_result(save_path: str | None = Query(None)):
    """Return the completed MP4 file, or (if `save_path` is given, from
    the packaged app's native Save panel) write it directly to disk."""
    if _export_video_job["running"]:
        raise HTTPException(409, "Video export still in progress")
    if _export_video_job["error"]:
        raise HTTPException(500, _export_video_job["error"])
    if _export_video_job["video_bytes"] is None:
        raise HTTPException(404, "No video export result available")
    video_bytes = _export_video_job["video_bytes"]
    _export_video_job["video_bytes"] = None  # free memory
    return _respond_with_result(video_bytes, "output.mp4", "video/mp4", save_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_loaded():
    if _state["source"] is None:
        raise HTTPException(400, "No project loaded. POST /api/load first.")


def _wav_audio_stats(wav_bytes):
    """Read duration/sample-rate/channels/bit-depth back out of a WAV
    file's own header rather than threading them through as separate
    return values from extract_audio_to_wav_bytes() -- the `wave` module
    handles the hand-rolled int24 header from _write_wav_int24() the same
    as any other standard PCM WAV, since it reads generically by
    sample-width rather than special-casing bit depths."""
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        n_channels = wf.getnchannels()
        framerate = wf.getframerate()
        n_frames = wf.getnframes()
        sampwidth = wf.getsampwidth()
    return {
        "duration_seconds": (n_frames / framerate) if framerate else 0.0,
        "sample_rate": framerate,
        "channels": n_channels,
        "bit_depth": sampwidth * 8,
    }


def _completion_stats(start_time, frame_count, output_bytes_len, output_path, wav_bytes=None):
    """Build the stats payload shown in the frontend's completion popup.

    *output_path* is the save destination if the native Save panel was
    used, else None (meaning the result was downloaded/held in memory).
    *wav_bytes*, if given, contributes duration/sample-rate/channels/
    bit-depth read from the WAV header (video exports that don't expose
    the intermediate WAV -- e.g. read from a temp file already written to
    disk -- can omit this and the audio_* fields are simply left out).
    """
    elapsed = max(time.time() - start_time, 1e-9)  # guard divide-by-zero for near-instant jobs
    stats = {
        "elapsed_seconds": elapsed,
        "frame_count": frame_count,
        "fps": frame_count / elapsed,
        "output_bytes": output_bytes_len,
        "output_path": output_path,
    }
    if wav_bytes is not None:
        stats.update(_wav_audio_stats(wav_bytes))
    return stats


def _respond_with_result(data, filename, media_type, save_path):
    """Either write *data* directly to *save_path* (native Save panel in
    the packaged app — see packaging/launcher.py's Api.choose_save_path)
    or fall back to a browser-download Response (dev mode)."""
    if save_path:
        try:
            with open(save_path, "wb") as f:
                f.write(data)
        except OSError as e:
            raise HTTPException(500, f"Failed to save file: {e}")
        return {"status": "saved", "path": save_path}
    return Response(
        content=data,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _resolve_ffmpeg_path():
    """Return the ffmpeg executable to use.

    When running as a frozen PyInstaller app (sys.frozen is set), prefer the
    binary bundled alongside the app by packaging/optical2digital.spec.
    Otherwise (normal `python server.py`, dev/CLI mode), fall back to
    whatever's on PATH — exactly the behavior this project had before the
    packaged-app feature existed.
    """
    if getattr(sys, "frozen", False):
        binary_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        bundled = pathlib.Path(getattr(sys, "_MEIPASS", "")) / binary_name
        if bundled.is_file() and os.access(bundled, os.X_OK):
            return str(bundled)
    return shutil.which("ffmpeg")


def _check_ffmpeg():
    if _resolve_ffmpeg_path() is None:
        raise HTTPException(
            500,
            "ffmpeg was not found. Install ffmpeg (e.g. `brew install ffmpeg` "
            "on macOS, or see ffmpeg.org) and restart the server to enable "
            "video export.",
        )


_ROTATE_FILTERS = {
    0: None,
    90: "transpose=1",               # 90° clockwise
    180: "transpose=2,transpose=2",  # 180°
    270: "transpose=2",              # 270° clockwise (== 90° counter-clockwise)
}

# libx264 + yuv420p requires even width/height; scan frames are frequently
# odd-dimensioned, so always trim to the nearest even size regardless of rotation.
_EVEN_DIMS_FILTER = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def _run_subprocess_cancellable(cmd, cancel_event, progress_callback=None, total_duration_seconds=None):
    """subprocess.run(cmd, check=True, capture_output=True) that can be
    interrupted mid-flight: polls the process with a short timeout instead
    of blocking uninterruptibly on a single call, so *cancel_event* being
    set is noticed within ~0.3s and the process is terminated (falling
    back to kill() if it doesn't exit promptly) rather than run to
    completion regardless of a cancel request.

    If *progress_callback* and *total_duration_seconds* are given, *cmd* is
    expected to include `-progress pipe:1` (see _mux_video_source() /
    _render_image_sequence()) -- its machine-readable `out_time=` lines on
    stdout are parsed and reported via progress_callback(elapsed_seconds,
    total_duration_seconds), the same (current, total) contract used
    everywhere else in this app. Reading `out_time=` (an "HH:MM:SS.ffffff"
    string) rather than `out_time_ms=` deliberately sidesteps a
    long-standing ffmpeg quirk where out_time_ms's actual unit has varied
    across versions (it's genuinely microseconds despite the name, on most
    but not all builds) -- out_time is unambiguous.

    stdout/stderr are now drained continuously by background threads
    (rather than buffered until process exit via communicate()) so a
    long-running mux/render can't fill either pipe's OS buffer and
    deadlock ffmpeg while this function is busy polling for cancellation.
    """
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stderr_lines = []

    def _drain_stderr():
        try:
            for line in proc.stderr:
                stderr_lines.append(line)
        except ValueError:
            pass  # pipe closed out from under us (process killed) -- fine, nothing left to read

    def _drain_stdout():
        try:
            for line in proc.stdout:
                if progress_callback is None or not total_duration_seconds:
                    continue
                line = line.strip()
                if not line.startswith("out_time="):
                    continue
                try:
                    h, m, s = line[len("out_time="):].split(":")
                    elapsed = int(h) * 3600 + int(m) * 60 + float(s)
                except ValueError:
                    continue
                progress_callback(min(elapsed, total_duration_seconds), total_duration_seconds)
        except ValueError:
            pass

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stdout_thread = threading.Thread(target=_drain_stdout, daemon=True)
    stderr_thread.start()
    stdout_thread.start()

    while True:
        try:
            proc.wait(timeout=0.3)
            break
        except subprocess.TimeoutExpired:
            if cancel_event is not None and cancel_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                stdout_thread.join(timeout=2)
                stderr_thread.join(timeout=2)
                raise decoder.ExtractionCancelled()

    stdout_thread.join(timeout=2)
    stderr_thread.join(timeout=2)
    stderr = "".join(stderr_lines).encode()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=b"", stderr=stderr)
    return subprocess.CompletedProcess(cmd, proc.returncode, b"", stderr)


def _mux_video_source(video_path, wav_path, out_path, fps, start_frame, end_frame,
                       cancel_event=None, progress_callback=None):
    """Mux extracted WAV audio onto a trimmed copy of the original video (stream-copy video).

    The video input is trimmed to [start_frame, end_frame] here. The WAV is
    NOT the same length: extract_audio() pads it with audio_offset frames of
    leading silence and audio_offset frames of real trailing audio beyond
    end_frame (see its docstring) — so it always ends up a bit longer than
    the trimmed video. No -shortest here: the output is intentionally
    allowed to run past the video's end with audio-only content, rather than
    silently clipping that trailing real audio to match the shorter video.
    """
    start_time = start_frame / fps
    end_time = (end_frame + 1) / fps
    duration = end_time - start_time
    cmd = [
        _resolve_ffmpeg_path(), "-y",
        # -ss/-t are per-input options in ffmpeg — they apply to whichever -i
        # follows them, so they must precede the *video* -i, not sit between
        # the two -i flags (which would trim the WAV input instead).
        "-ss", f"{start_time:.6f}",
        "-t", f"{duration:.6f}",
        "-i", video_path,
        "-i", wav_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-dn",
        "-write_tmcd", "false",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        # Machine-readable progress on stdout (key=value lines, see
        # _run_subprocess_cancellable) instead of ffmpeg's normal
        # human-readable stats banner on stderr.
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]
    # ffmpeg's out_time tracks encoded *output* duration, which -- with no
    # -shortest -- runs past `duration` (the trimmed video length) to match
    # the WAV's own length (audio_offset padding makes it longer, see this
    # function's docstring). Use the WAV's real duration as the progress
    # total so the percentage doesn't hit 100% before muxing actually ends.
    with wave.open(wav_path) as wf:
        total_duration = (wf.getnframes() / wf.getframerate()) if wf.getframerate() else duration
    _run_subprocess_cancellable(cmd, cancel_event, progress_callback, total_duration)


def _render_image_sequence(source, wav_path, out_path, fps, rotate, start_frame, end_frame, tmpdir,
                            cancel_event=None, progress_callback=None):
    """Build a concat-demuxer list from the full original scan frames and render to MP4.

    The picture track spans exactly [start_frame, end_frame]. The WAV is
    longer than that (see extract_audio()'s docstring: audio_offset frames
    of leading silence plus audio_offset frames of real trailing audio
    beyond end_frame), so the picture stream intentionally ends before the
    audio does. No -shortest here: that would silently clip the real
    trailing audio to match the shorter picture track.
    """
    frame_duration = 1.0 / fps
    list_path = os.path.join(tmpdir, "frames.txt")
    with open(list_path, "w") as f:
        last_path = None
        for idx in range(start_frame, end_frame + 1):
            path = source.frame_path(idx)
            if path is None:
                continue
            # ffmpeg concat demuxer requires paths to be escaped for its mini-language
            escaped = path.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
            f.write(f"duration {frame_duration:.6f}\n")
            last_path = escaped
        # Per ffmpeg concat-demuxer doc: repeat the last file once more WITHOUT
        # a duration line, or the final frame's duration is ignored.
        if last_path is not None:
            f.write(f"file '{last_path}'\n")

    cmd = [
        _resolve_ffmpeg_path(), "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-i", wav_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
    ]
    rotate_filter = _ROTATE_FILTERS.get(rotate)
    vf = f"{rotate_filter},{_EVEN_DIMS_FILTER}" if rotate_filter else _EVEN_DIMS_FILTER
    cmd += ["-vf", vf]
    cmd += [
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", f"{fps}",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        # See _mux_video_source()'s matching flags for why: machine-readable
        # progress on stdout instead of ffmpeg's stats banner on stderr.
        "-progress", "pipe:1", "-nostats",
        out_path,
    ]
    # Same reasoning as _mux_video_source(): use the WAV's own (longer, due
    # to audio_offset padding) duration as the progress total rather than
    # the picture track's shorter duration.
    with wave.open(wav_path) as wf:
        total_duration = (wf.getnframes() / wf.getframerate()) if wf.getframerate() else (end_frame - start_frame + 1) / fps
    _run_subprocess_cancellable(cmd, cancel_event, progress_callback, total_duration)



# ---------------------------------------------------------------------------
# Serve the React build (production) or just the API (development)
# ---------------------------------------------------------------------------

_frontend_dist = pathlib.Path(__file__).parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    # Serve React build artifacts
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
