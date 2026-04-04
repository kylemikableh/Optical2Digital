"""
Web server for Kyle's Optical Decoder.

Run:  python server.py
Then open http://localhost:8000 in your browser.

This file is part of Kyle's Optical Decoder.

Copyright (C) 2026 Kyle Mikolajczyk

Kyle's Optical Decoder is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

Kyle's Optical Decoder is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Kyle's Optical Decoder; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""

import json
import os
import pathlib
import threading
import time
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import KylesOpticalDecoder as decoder

app = FastAPI(title="Kyle's Optical Decoder")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# State — currently loaded project
# ---------------------------------------------------------------------------

_state = {
    "source": None,
}

# Extraction job state
_extract_job = {
    "running": False,
    "current": 0,
    "total": 0,
    "phase": "",
    "done": False,
    "error": None,
    "wav_bytes": None,
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
    fps: float = 24.0
    sample_rate: int = 48000
    hpf: float = 40.0
    lpf: float = 13500.0
    overlap: float = 0.25
    soundtrack_color: Literal["B&W", "High-Magenta", "Cyan"] = "B&W"
    reverse: bool = False
    stereo: bool = False
    start_frame: int = 0
    end_frame: int | None = None


@app.post("/api/extract")
def extract(req: ExtractRequest):
    """Start the extraction pipeline in a background thread."""
    _check_loaded()

    if _extract_job["running"]:
        raise HTTPException(409, "Extraction already in progress")

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
    _extract_job["wav_bytes"] = None

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
                fps=req.fps,
                sample_rate=req.sample_rate,
                hpf=req.hpf,
                lpf=req.lpf,
                overlap=req.overlap,
                soundtrack_color=req.soundtrack_color,
                stereo=req.stereo,
                reverse=req.reverse,
                start_frame=req.start_frame,
                end_frame=req.end_frame,
                progress_callback=progress_cb,
                phase_callback=phase_cb,
            )
            _extract_job["wav_bytes"] = wav_bytes
            _extract_job["phase"] = "Complete"
        except Exception as e:
            _extract_job["error"] = str(e)
            _extract_job["phase"] = "Error"
        finally:
            _extract_job["done"] = True
            _extract_job["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started", "total": frame_count}


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
def extract_result():
    """Download the completed WAV file."""
    if _extract_job["running"]:
        raise HTTPException(409, "Extraction still in progress")
    if _extract_job["error"]:
        raise HTTPException(500, _extract_job["error"])
    if _extract_job["wav_bytes"] is None:
        raise HTTPException(404, "No extraction result available")
    wav_bytes = _extract_job["wav_bytes"]
    _extract_job["wav_bytes"] = None  # free memory
    return Response(
        content=wav_bytes,
        media_type="audio/wav",
        headers={"Content-Disposition": "attachment; filename=output.wav"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_loaded():
    if _state["source"] is None:
        raise HTTPException(400, "No project loaded. POST /api/load first.")



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
