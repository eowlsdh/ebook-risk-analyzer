"""Loopback-only launcher for the local ebook analysis browser application."""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import tempfile
import threading
import webbrowser
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

from werkzeug.serving import BaseWSGIServer, make_server

from .web_app import create_app


def _available_port() -> int:
    """Ask the operating system for an unused loopback TCP port."""
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _windows_instance_lock() -> tuple[object | None, Path | None]:
    """Acquire a non-blocking Windows lock, returning a clear failure sentinel."""
    if os.name != "nt":
        return None, None
    import msvcrt

    path = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "ebook-risk-analyzer.lock"
    handle = path.open("a+b")
    try:
        handle.seek(0)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return None, path
    return handle, None


def main(argv: Sequence[str] | None = None) -> int:
    """Start a non-debug local server, open its browser page, and stop cleanly."""
    parser = argparse.ArgumentParser(description="전자책 위험 신호 분석기 로컬 웹 화면")
    parser.add_argument("--port", type=int, default=0, help="127.0.0.1 포트 (기본값: 임의 포트)")
    args = parser.parse_args(argv)
    port = args.port or _available_port()
    if not 1 <= port <= 65535:
        parser.error("포트는 1에서 65535 사이여야 합니다.")
    lock, blocked_lock = _windows_instance_lock()
    if blocked_lock is not None:
        parser.error("이미 실행 중입니다. 열린 분석기 창에서 앱 종료를 선택하세요.")

    app = create_app()
    root = Path(app.config["WORK_ROOT"])
    server: BaseWSGIServer | None = None
    previous_int = previous_term = None
    try:
        server = make_server("127.0.0.1", port, app, threaded=True)
        app.config["LOCAL_PORT"] = server.server_port
        app.extensions["web_shutdown"] = server.shutdown
        url = f"http://127.0.0.1:{server.server_port}/?cap={app.config['LOCAL_CAPABILITY']}"
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()

        def stop(_signum: int, _frame: object) -> None:
            threading.Thread(target=server.shutdown, daemon=True).start()

        previous_int = signal.signal(signal.SIGINT, stop)
        previous_term = signal.signal(signal.SIGTERM, stop)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    finally:
        if previous_int is not None:
            signal.signal(signal.SIGINT, previous_int)
        if previous_term is not None:
            signal.signal(signal.SIGTERM, previous_term)
        if server is not None:
            server.server_close()
        shutil.rmtree(root, ignore_errors=True)
        if lock is not None:
            lock.close()
    return 0
