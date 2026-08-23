#!/usr/bin/env python3
"""Standalone check for launcher's server-thread lifecycle. Does NOT invoke
webview.start() (that blocks and needs a real display) — only the
non-GUI pieces are covered here; the actual window is checked manually
in Task 4's verification.

Run directly with python3:
    python3 packaging/tests/test_launcher_server.py
"""
import os
import socket
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, os.path.join(ROOT_DIR, "packaging"))

import launcher  # bare module import — NOT "from packaging import launcher".
                  # `packaging` also happens to be the name of a real PyPI
                  # package (used by pip/setuptools); importing this dir as
                  # a package could silently resolve to that one instead if
                  # it's ever installed in this venv. Adding packaging/ to
                  # sys.path and importing the bare `launcher` module name
                  # sidesteps the collision entirely.
import server as server_module

TEST_PORT = 8199


def test_server_starts_and_responds():
    thread, uv_server = launcher.start_server_thread(server_module.app, port=TEST_PORT)
    try:
        ok = launcher.wait_for_server(f"http://127.0.0.1:{TEST_PORT}/", timeout=10)
        assert ok, "server did not come up within timeout"
    finally:
        uv_server.should_exit = True
        thread.join(timeout=5)

    assert not thread.is_alive(), "server thread did not shut down cleanly"


def test_port_is_free_after_shutdown():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        result = s.connect_ex(("127.0.0.1", TEST_PORT))
        assert result != 0, f"port {TEST_PORT} still accepting connections after shutdown"


if __name__ == "__main__":
    test_server_starts_and_responds()
    test_port_is_free_after_shutdown()
    print("OK: launcher server-thread lifecycle checks passed")
