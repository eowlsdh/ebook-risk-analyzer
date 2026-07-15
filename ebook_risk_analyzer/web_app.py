"""Local-only Flask interface for the ebook risk analyzer."""
from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

from flask import Flask, Response, abort, jsonify, render_template, request, send_file, url_for
from werkzeug.datastructures import FileStorage

from .analyzer import analyze_source
from .report_generator import generate_reports, render_report_html, report_record

_ARTIFACTS = ("report.json", "report.html", "findings.csv", "extracted_text.txt", "metadata.json")
_ALLOWED_EXTENSIONS = {".epub", ".html", ".htm", ".xhtml", ".txt"}
_DEFAULT_FILE_LIMIT = 50 * 1024 * 1024
_DEFAULT_TOTAL_LIMIT = 500 * 1024 * 1024
_DEFAULT_COUNT_LIMIT = 2_000


def _error(message: str, status: int = 400) -> Response:
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify(error=message), status
    return Response(message, status=status, content_type="text/html; charset=utf-8")


_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.IGNORECASE)
_ROOT_MARKER = ".ebook-risk-root"
_ROOT_MARKER_CONTENT = "ebook-risk-analyzer temporary root\n"
_PRIVATE_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|/(?:Users|home|private|var/folders|tmp)/)")


def _relative_path(value: str) -> Path:
    if not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} or _WINDOWS_RESERVED.fullmatch(part) for part in path.parts):
        raise ValueError
    return Path(*path.parts)


def _target_under(destination: Path, relative: Path) -> Path:
    base = destination.resolve()
    target = (destination / relative).resolve(strict=False)
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError("안전하지 않은 파일 경로는 업로드할 수 없습니다.") from None
    return target


def _safe_uploads(files: list[FileStorage], relative_paths: list[str], destination: Path, app: Flask) -> Path:
    if not files:
        raise ValueError("분석할 파일을 선택하세요.")
    if len(files) > int(app.config["MAX_UPLOAD_FILES"]):
        raise ValueError("업로드 가능한 파일 수를 초과했습니다.")
    if relative_paths and len(relative_paths) != len(files):
        raise ValueError("파일 경로 정보가 올바르지 않습니다.")
    paths = relative_paths or [item.filename or "" for item in files]
    validated: list[Path] = []
    for value in paths:
        try:
            relative = _relative_path(value)
        except ValueError:
            raise ValueError("안전하지 않은 파일 경로는 업로드할 수 없습니다.") from None
        if relative.suffix.lower() not in _ALLOWED_EXTENSIONS:
            raise ValueError("EPUB, HTML, XHTML 또는 TXT 파일만 업로드할 수 있습니다.")
        validated.append(relative)
    if len(set(validated)) != len(validated):
        raise ValueError("중복된 파일 경로는 업로드할 수 없습니다.")
    if len(files) > 1 and any(path.suffix.lower() == ".epub" for path in validated):
        raise ValueError("EPUB 파일은 단독으로 업로드하세요.")
    total = 0
    for upload, relative in zip(files, validated, strict=True):
        target = _target_under(destination, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Resolve again after mkdir so a pre-existing symlink cannot redirect the open.
        target = _target_under(destination, relative)
        written = 0
        with target.open("xb") as stream:
            while chunk := upload.stream.read(64 * 1024):
                written += len(chunk)
                total += len(chunk)
                if written > int(app.config["MAX_UPLOAD_FILE_SIZE"]):
                    raise ValueError("파일 하나가 허용된 크기를 초과했습니다.")
                if total > int(app.config["MAX_UPLOAD_TOTAL_SIZE"]):
                    raise ValueError("전체 업로드 크기가 허용 범위를 초과했습니다.")
                stream.write(chunk)
    return _target_under(destination, validated[0]) if len(validated) == 1 else destination




def _sanitize_structure(value: Any, private_paths: tuple[str, ...]) -> Any:
    """Sanitize report data before JSON serialization, retaining its schema."""
    if isinstance(value, str):
        return "업로드한 파일" if any(private and private in value for private in private_paths) else value
    if isinstance(value, list):
        return [_sanitize_structure(item, private_paths) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_structure(item, private_paths) for key, item in value.items()}
    return value
def _record_private_paths(value: Any) -> set[str]:
    """Collect absolute host paths present in a raw structured report."""
    if isinstance(value, str):
        return {value} if _PRIVATE_PATH.search(value) else set()
    if isinstance(value, list):
        return set().union(*(_record_private_paths(item) for item in value))
    if isinstance(value, dict):
        return set().union(*(_record_private_paths(item) for item in value.values()))
    return set()




def _sanitize_artifacts(artifacts: Path, private_paths: tuple[str, ...]) -> None:
    """Structurally rewrite JSON artifacts and redact plain-text artifact fields."""
    for name in ("report.json", "metadata.json"):
        path = artifacts / name
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        path.write_text(json.dumps(_sanitize_structure(data, private_paths), ensure_ascii=False,
                                   sort_keys=True, indent=2) + "\n", encoding="utf-8")
    for name in ("findings.csv", "extracted_text.txt"):
        path = artifacts / name
        text = path.read_text(encoding="utf-8", errors="replace")
        for private in private_paths:
            text = text.replace(private, "업로드한 파일")
            text = text.replace(json.dumps(private, ensure_ascii=False)[1:-1], "업로드한 파일")
        path.write_text(text, encoding="utf-8")




def _tree_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file() and not item.is_symlink())


_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_INVALID_PARAMETER = 87
_IS_WINDOWS = os.name == "nt"


def _windows_process_creation_identity(pid: int) -> tuple[str, int | None]:
    """Return whether a Windows PID is live, stale, or cannot be inspected."""
    if pid <= 0:
        return "stale", None
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ("stale", None) if ctypes.get_last_error() == _ERROR_INVALID_PARAMETER else ("unknown", None)
    try:
        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel_time = wintypes.FILETIME()
        user_time = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(creation),
            ctypes.byref(exit_time),
            ctypes.byref(kernel_time),
            ctypes.byref(user_time),
        ):
            return "unknown", None
        return "alive", (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    finally:
        kernel32.CloseHandle(handle)


def _process_is_alive(pid: int) -> bool:
    """Probe POSIX process liveness without signaling it."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _root_process_state(pid: int, identity: str) -> str:
    if _IS_WINDOWS:
        state, current_identity = _windows_process_creation_identity(pid)
        if state != "alive":
            return state
        return "alive" if identity == f"windows:{current_identity}" else "stale"
    return "alive" if _process_is_alive(pid) else "stale"


def _mark_temporary_root(root: Path) -> None:
    if _IS_WINDOWS:
        state, creation_identity = _windows_process_creation_identity(os.getpid())
        if state != "alive" or creation_identity is None:
            raise OSError("Unable to identify the current Windows process.")
        identity = f"windows:{creation_identity}"
    else:
        identity = "posix"
    marker = root / _ROOT_MARKER
    descriptor, temporary_marker = tempfile.mkstemp(prefix=f"{_ROOT_MARKER}.", dir=root)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as stream:
            stream.write(f"{_ROOT_MARKER_CONTENT}{os.getpid()}\n{identity}\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_marker, marker)
    except BaseException:
        try:
            os.unlink(temporary_marker)
        except OSError:
            pass
        raise


def _read_temporary_root_marker(candidate: Path) -> tuple[int, str] | None:
    marker = candidate / _ROOT_MARKER
    if marker.is_symlink() or not marker.is_file():
        return None
    try:
        lines = marker.read_text(encoding="ascii").splitlines()
        pid = int(lines[1])
    except (OSError, ValueError, IndexError):
        return None
    if len(lines) != 3 or lines[0] != _ROOT_MARKER_CONTENT.rstrip() or pid <= 0:
        return None
    identity = lines[2]
    if identity == "posix" or (identity.startswith("windows:") and identity[8:].isdigit()):
        return pid, identity
    return None


def _sweep_stale_temporary_roots(current: Path) -> None:
    for candidate in current.parent.glob("ebook-risk-*"):
        if candidate == current or not candidate.is_dir() or candidate.is_symlink():
            continue
        marker = _read_temporary_root_marker(candidate)
        if marker is not None and _root_process_state(*marker) == "stale":
            shutil.rmtree(candidate, ignore_errors=True)


def create_app(work_root: Path | None = None, testing: bool = False) -> Flask:
    """Create the capability-protected, loopback-only local web application."""
    app = Flask(__name__)
    temporary_root = work_root is None
    root = Path(work_root) if work_root is not None else Path(tempfile.mkdtemp(prefix="ebook-risk-"))
    root.mkdir(parents=True, exist_ok=True)
    if temporary_root:
        _mark_temporary_root(root)
        _sweep_stale_temporary_roots(root)
        atexit.register(shutil.rmtree, root, ignore_errors=True)
    app.config.update(
        TESTING=testing, WORK_ROOT=root, LOCAL_PORT=None,
        LOCAL_CAPABILITY=secrets.token_urlsafe(32),
        MAX_UPLOAD_FILES=_DEFAULT_COUNT_LIMIT, MAX_UPLOAD_FILE_SIZE=_DEFAULT_FILE_LIMIT,
        MAX_UPLOAD_TOTAL_SIZE=_DEFAULT_TOTAL_LIMIT, MAX_CONTENT_LENGTH=_DEFAULT_TOTAL_LIMIT + 1024 * 1024,
        MAX_CONCURRENT_ANALYSES=2, MAX_RETAINED_JOBS=20, MAX_RETAINED_BYTES=1024 * 1024 * 1024,
        JOB_TTL_SECONDS=60 * 60,
    )
    admission = threading.BoundedSemaphore(int(app.config["MAX_CONCURRENT_ANALYSES"]))
    quota_lock = threading.Lock()
    reservations: dict[str, int] = {}

    def cleanup() -> None:
        cutoff = time.time() - float(app.config["JOB_TTL_SECONDS"])
        with quota_lock:
            for job in root.iterdir():
                if job.is_dir() and not job.is_symlink() and job.stat().st_mtime < cutoff:
                    shutil.rmtree(job, ignore_errors=True)
                    reservations.pop(job.name, None)

    def valid_job(job_id: str) -> Path | None:
        cleanup()
        if not secrets.compare_digest(job_id, Path(job_id).name):
            return None
        job = root / job_id
        return job if (job / "artifacts" / "report.json").is_file() else None

    def capability() -> bool:
        supplied = request.headers.get("X-Local-Capability") or request.values.get("cap", "")
        return bool(supplied) and secrets.compare_digest(supplied, app.config["LOCAL_CAPABILITY"])

    @app.before_request
    def protect_local_boundary() -> Response | None:
        host = request.host.split(":", 1)
        hostname = host[0].lower()
        expected_port = app.config["LOCAL_PORT"]
        if hostname not in {"127.0.0.1", "::1", "localhost"} or (expected_port is not None and request.host != f"127.0.0.1:{expected_port}"):
            return _error("로컬 앱 요청만 허용됩니다.", 403)
        origin = request.headers.get("Origin")
        allowed_origins = {f"http://{request.host}"}
        if expected_port is not None:
            allowed_origins = {f"http://127.0.0.1:{expected_port}", f"http://localhost:{expected_port}"}
        if origin and origin not in allowed_origins:
            return _error("안전하지 않은 요청입니다.", 403)
        if request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site":
            return _error("안전하지 않은 요청입니다.", 403)
        if request.endpoint in {"analyze", "result", "download", "shutdown"} and not capability():
            return _error("로컬 앱 권한이 필요합니다.", 403)
        return None

    @app.errorhandler(413)
    def upload_too_large(_exception: Exception) -> Response:
        return _error("전체 업로드 크기가 허용 범위를 초과했습니다.", 413)

    @app.get("/health")
    def health() -> Response:
        return jsonify(status="ok")

    @app.get("/")
    def index() -> Response:
        return render_template("web_index.html", cap=app.config["LOCAL_CAPABILITY"])

    @app.post("/shutdown")
    def shutdown() -> Response:
        callback = app.extensions.get("web_shutdown")
        if callback is not None:
            threading.Thread(target=callback, daemon=True).start()
        return Response("종료 중입니다.", status=200, content_type="text/html; charset=utf-8")

    @app.post("/analyze")
    def analyze() -> Response:
        cleanup()
        incoming_bytes = min(request.content_length or int(app.config["MAX_UPLOAD_TOTAL_SIZE"]),
                             int(app.config["MAX_UPLOAD_TOTAL_SIZE"]))
        job_id = secrets.token_urlsafe(18)
        with quota_lock:
            jobs = {item.name for item in root.iterdir() if item.is_dir() and not item.is_symlink()}
            used_bytes = sum(_tree_size(root / name) for name in jobs)
            retained_ids = jobs | reservations.keys()
            if (len(retained_ids) >= int(app.config["MAX_RETAINED_JOBS"]) or
                    used_bytes + sum(reservations.values()) + incoming_bytes >
                    int(app.config["MAX_RETAINED_BYTES"])):
                return _error("현재 작업이 많습니다. 잠시 후 다시 시도하세요.", 429)
            reservations[job_id] = incoming_bytes
        if not admission.acquire(blocking=False):
            with quota_lock:
                reservations.pop(job_id, None)
            return _error("현재 분석이 진행 중입니다. 잠시 후 다시 시도하세요.", 429)
        job: Path | None = None
        succeeded = False
        try:
            language = request.form.get("language", "auto")
            if language not in {"auto", "ko", "en"}:
                raise ValueError
            raw_limit = request.form.get("max_file_size", "").strip()
            max_file_size = int(raw_limit) if raw_limit else int(app.config["MAX_UPLOAD_FILE_SIZE"])
            if not 0 < max_file_size <= int(app.config["MAX_UPLOAD_FILE_SIZE"]):
                raise ValueError
            raw_paths = request.form.get("relative_paths", "").strip()
            relative_paths = json.loads(raw_paths) if raw_paths else []
            if not isinstance(relative_paths, list) or not all(isinstance(item, str) for item in relative_paths):
                raise ValueError
            job = root / job_id
            job.mkdir(mode=0o700)
            source = _safe_uploads(request.files.getlist("files"), relative_paths, job / "input", app)
            report = analyze_source(source, language=language, verify_links=request.form.get("verify_links") == "on", max_file_size=max_file_size)
            artifacts = job / "artifacts"
            generate_reports(report, artifacts)
            raw_record = report_record(report)
            private_paths = tuple({
                str(root.resolve()), str(job.resolve()), str(source.resolve()),
                str((job / "input").resolve()), tempfile.gettempdir(),
                *_record_private_paths(raw_record),
            })
            _sanitize_artifacts(artifacts, private_paths)
            raw_record["book"]["source_file"] = "업로드한 파일"
            record = _sanitize_structure(raw_record, private_paths)
            (artifacts / "report.html").write_text(render_report_html(record), encoding="utf-8")
            with quota_lock:
                # Retained work has exact, committed size; the reservation protected it while running.
                reservations[job_id] = 0
                if sum(_tree_size(item) for item in root.iterdir()
                       if item.is_dir() and not item.is_symlink()) + sum(reservations.values()) > int(app.config["MAX_RETAINED_BYTES"]):
                    raise ValueError
            succeeded = True
            succeeded = True
            result_url = url_for("result", job_id=job_id, cap=app.config["LOCAL_CAPABILITY"])
            if request.accept_mimetypes.best == "application/json":
                return jsonify(job_id=job_id, report=record, artifact_names=list(_ARTIFACTS), result_url=result_url,
                    downloads={name: url_for("download", job_id=job_id, artifact=name, cap=app.config["LOCAL_CAPABILITY"]) for name in _ARTIFACTS})
            return Response("", status=303, headers={"Location": result_url})
        except (ValueError, json.JSONDecodeError):
            return _error("업로드 정보를 확인하세요. 안전한 지원 파일만 분석할 수 있습니다.")
        except Exception:
            return _error("분석 중 문제가 발생했습니다. 파일 형식과 크기를 확인한 뒤 다시 시도하세요.", 500)
        finally:
            if not succeeded and job is not None:
                shutil.rmtree(job, ignore_errors=True)
            with quota_lock:
                reservations.pop(job_id, None)
            admission.release()

    @app.get("/result/<job_id>")
    def result(job_id: str) -> Response:
        job = valid_job(job_id)
        if job is None:
            abort(404)
        record = json.loads((job / "artifacts" / "report.json").read_text(encoding="utf-8"))
        record["book"]["source_file"] = "업로드한 파일"
        return render_template("web_result.html", job_id=job_id, report=record, artifact_names=_ARTIFACTS, cap=app.config["LOCAL_CAPABILITY"])

    @app.get("/download/<job_id>/<artifact>")
    def download(job_id: str, artifact: str) -> Response:
        job = valid_job(job_id)
        if job is None or artifact not in _ARTIFACTS:
            abort(404)
        path = job / "artifacts" / artifact
        if not path.is_file() or path.is_symlink():
            abort(404)
        return send_file(path, as_attachment=True, download_name=artifact)

    return app


def main(argv: Sequence[str] | None = None) -> int:
    from .web_launcher import main as launcher_main
    return launcher_main(argv)
