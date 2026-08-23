"""
Desktop launcher for the packaged macOS app: starts the existing FastAPI
server in a background thread and opens a native window pointed at it.

This is the PyInstaller entry point (see packaging/optical2digital.spec).
It is NOT used by the dev workflow (start-dev.sh) or the CLI
(KylesOpticalDecoder.py) — server.py's own `if __name__ == "__main__"`
block still runs `uvicorn.run(...)` directly for those, unchanged.
"""
import pathlib
import sys
import threading
import time
import urllib.error
import urllib.request

# When run directly (`python packaging/launcher.py`), Python only puts this
# script's own directory on sys.path — add the repo root too so `import
# server` (and server.py's own `import KylesOpticalDecoder`) resolve. This
# is a no-op once frozen by PyInstaller.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import uvicorn
import webview
from webview import FileDialog

import server as server_module

HOST = "127.0.0.1"
PORT = 8000


class Api:
    """Bound to the webview window as `js_api` so the frontend can invoke
    native file/folder pickers via `window.pywebview.api.<method>()`.

    pywebview has no dialog mode that lets a user pick either a file or a
    folder at once, so the frontend exposes two separate entry points
    instead — one per source type `KylesOpticalDecoder.open_source()`
    accepts (an image-sequence directory, or a video file).
    """

    def choose_folder(self):
        result = webview.windows[0].create_file_dialog(FileDialog.FOLDER)
        return result[0] if result else None

    def choose_video_file(self):
        result = webview.windows[0].create_file_dialog(
            FileDialog.OPEN,
            file_types=("Video Files (*.mp4;*.mov;*.avi;*.mkv)",),
        )
        return result[0] if result else None

    def choose_save_path(self, default_filename="", file_types=()):
        """Native Save panel — returns the chosen destination path, or
        None if cancelled. Used for large binary results (WAV/MP4) whose
        bytes stay server-side; only the path crosses the JS bridge."""
        result = webview.windows[0].create_file_dialog(
            FileDialog.SAVE,
            save_filename=default_filename,
            file_types=tuple(file_types),
        )
        return result[0] if result else None

    def save_text_file(self, default_filename, content):
        """Save panel + direct write, for small client-generated text
        (settings JSON) — no backend round trip needed."""
        path = self.choose_save_path(default_filename)
        if not path:
            return None
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path


def start_server_thread(app, host=HOST, port=PORT):
    """Start uvicorn serving *app* in a background thread.

    Returns (thread, uvicorn.Server). To shut down cleanly, set
    `uv_server.should_exit = True` then join the thread.
    """
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    uv_server = uvicorn.Server(config)

    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    return thread, uv_server


def wait_for_server(url, timeout=10.0, interval=0.1):
    """Poll *url* until the server responds (any HTTP status, even an
    error one) or *timeout* seconds elapse. Returns True if it responded."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except urllib.error.HTTPError:
            return True  # server is up; the endpoint just didn't return 2xx
        except Exception:
            time.sleep(interval)
    return False


def main():
    thread, uv_server = start_server_thread(server_module.app)
    url = f"http://{HOST}:{PORT}/"
    if not wait_for_server(url):
        raise RuntimeError(f"Server did not start within timeout at {url}")

    webview.create_window("Optical2Digital", url, width=1280, height=860, js_api=Api())
    webview.start()

    # Window closed — shut the server down cleanly so no process is left
    # holding the port.
    uv_server.should_exit = True
    thread.join(timeout=5)


if __name__ == "__main__":
    main()
