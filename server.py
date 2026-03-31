"""
Web server for Kyle's Optical Decoder.

Run:  python server.py
Then open http://localhost:8000 in your browser.
"""

import json
import os
import pathlib
import threading
import time

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
    "input_dir": None,
    "filenames": [],
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

@app.post("/api/load", response_model=LoadProjectResponse)
def load_project(req: LoadProjectRequest):
    """Point the server at a directory of scanned frame images."""
    d = os.path.abspath(req.input_dir)
    if not os.path.isdir(d):
        raise HTTPException(404, f"Directory not found: {d}")

    filenames = decoder.list_frames(d)
    if not filenames:
        raise HTTPException(400, "No image files found in directory")

    # Read first frame for dimensions
    first = decoder.load_frame(d, filenames[0])
    if first is None:
        raise HTTPException(500, "Could not read first frame image")

    _state["input_dir"] = d
    _state["filenames"] = filenames

    h, w = first.shape
    return LoadProjectResponse(num_frames=len(filenames), frame_width=w, frame_height=h)


@app.get("/api/frames")
def get_frame_list():
    """Return the sorted list of frame filenames."""
    if not _state["filenames"]:
        raise HTTPException(400, "No project loaded")
    return {"filenames": _state["filenames"]}


@app.get("/api/frame/{index}/raw")
def get_raw_frame(index: int, rotate: int = Query(0)):
    """Return the raw (uncropped) frame as a JPEG for preview."""
    _check_loaded()
    fname = _get_filename(index)
    img = decoder.load_frame(_state["input_dir"], fname)
    if img is None:
        raise HTTPException(500, f"Could not read frame: {fname}")
    img = decoder.rotate_image(img, rotate)
    return Response(content=decoder.frame_to_jpeg(img), media_type="image/jpeg")


@app.get("/api/frame/{index}/corrected")
def get_corrected_frame(
    index: int,
    rotate: int = Query(0),
    negative: bool = Query(False),
    lift: float = Query(0.0),
    gamma: float = Query(1.0),
    gain: float = Query(1.0),
    threshold: float = Query(0.0),
):
    """Return full frame with corrections applied (no crop), rotated, as JPEG."""
    _check_loaded()
    fname = _get_filename(index)
    img = decoder.load_frame(_state["input_dir"], fname)
    if img is None:
        raise HTTPException(500, f"Could not read frame: {fname}")
    corrected = decoder.correct_full_frame(img, negative, lift, gamma, gain, threshold)
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
    lift: float = Query(0.0),
    gamma: float = Query(1.0),
    gain: float = Query(1.0),
    threshold: float = Query(0.0),
):
    """Return a cropped+corrected frame as JPEG (for live preview)."""
    _check_loaded()
    fname = _get_filename(index)
    img = decoder.load_frame(_state["input_dir"], fname)
    if img is None:
        raise HTTPException(500, f"Could not read frame: {fname}")

    corrected = decoder.crop_and_correct(
        img, top, bottom, left, right, rotate,
        negative, lift, gamma, gain, threshold,
    )
    return Response(content=decoder.corrected_to_jpeg(corrected), media_type="image/jpeg")


class ExtractRequest(BaseModel):
    top: int
    bottom: int
    left: int
    right: int
    rotate: int = 0
    negative: bool = False
    lift: float = 0.0
    gamma: float = 1.0
    gain: float = 1.0
    threshold: float = 0.0
    fps: float = 24.0
    sample_rate: int = 48000
    hpf: float = 40.0
    lpf: float = 13500.0
    overlap: float = 0.25
    reverse: bool = False
    stereo: bool = False


@app.post("/api/extract")
def extract(req: ExtractRequest):
    """Start the extraction pipeline in a background thread."""
    _check_loaded()

    if _extract_job["running"]:
        raise HTTPException(409, "Extraction already in progress")

    filenames = list(_state["filenames"])
    if req.reverse:
        filenames = filenames[::-1]

    _extract_job["running"] = True
    _extract_job["current"] = 0
    _extract_job["total"] = len(filenames)
    _extract_job["phase"] = "Processing frames"
    _extract_job["done"] = False
    _extract_job["error"] = None
    _extract_job["wav_bytes"] = None

    def _run():
        try:
            def progress_cb(current, total):
                _extract_job["current"] = current
                _extract_job["total"] = total

            wav_bytes = decoder.extract_audio_to_wav_bytes(
                _state["input_dir"], filenames,
                top=req.top, bottom=req.bottom, left=req.left, right=req.right,
                rotate=req.rotate, negative=req.negative, lift=req.lift,
                gamma=req.gamma, gain=req.gain, threshold=req.threshold,
                fps=req.fps, sample_rate=req.sample_rate,
                hpf=req.hpf, lpf=req.lpf, overlap=req.overlap,
                stereo=req.stereo,
                progress_callback=progress_cb,
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
    return {"status": "started", "total": len(filenames)}


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

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    if not _state["input_dir"] or not _state["filenames"]:
        raise HTTPException(400, "No project loaded. POST /api/load first.")


def _get_filename(index: int) -> str:
    if index < 0 or index >= len(_state["filenames"]):
        raise HTTPException(404, f"Frame index {index} out of range (0–{len(_state['filenames'])-1})")
    return _state["filenames"][index]


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
