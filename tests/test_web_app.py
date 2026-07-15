from __future__ import annotations

from io import BytesIO
import json
from types import SimpleNamespace
from pathlib import Path
import threading
import time

import pytest

import ebook_risk_analyzer.web_app as web_app
import ebook_risk_analyzer.web_launcher as web_launcher


ARTIFACTS = ("report.json", "report.html", "findings.csv", "extracted_text.txt", "metadata.json")


@pytest.fixture
def app(tmp_path, monkeypatch):
    calls: list[dict[str, object]] = []
    record = {
        "book": {
            "title": "<script>untrusted</script>",
            "source_file": r"C:\Users\alice\Books\private.epub",
            "metadata": {"source": "/Users/alice/Books/private.epub"},
        },
        "summary": {"risk_score": 0, "finding_count": 0},
        "category_scores": {},
        "findings": [{"location": {"file": r"C:\Users\alice\Books\private.epub"}}],
    }

    def fake_analyze(source, *, language, verify_links, max_file_size):
        calls.append({"source": source, "language": language, "verify_links": verify_links, "max_file_size": max_file_size})
        return object()

    def fake_reports(_report, output):
        output.mkdir(parents=True)
        for artifact in ARTIFACTS:
            content = json.dumps(record) if artifact in {"report.json", "metadata.json"} else json.dumps(record)
            (output / artifact).write_text(content, encoding="utf-8")
        return {name: output / name for name in ARTIFACTS}

    monkeypatch.setattr(web_app, "analyze_source", fake_analyze)
    monkeypatch.setattr(web_app, "generate_reports", fake_reports)
    monkeypatch.setattr(web_app, "report_record", lambda _report: json.loads(json.dumps(record)))
    application = web_app.create_app(tmp_path / "jobs", testing=True)
    application.extensions["web_test_calls"] = calls
    return application


def upload(client, name="book.txt", content=b"local manuscript", **fields):
    data = {"files": (BytesIO(content), name), "language": "auto", "cap": client.application.config["LOCAL_CAPABILITY"], **fields}
    return client.post("/analyze", data=data, content_type="multipart/form-data", headers={"Accept": "application/json"})


def test_launcher_binds_only_loopback(monkeypatch):
    captured = {}

    class Server:
        server_port = 43123

        def serve_forever(self):
            raise KeyboardInterrupt
        def shutdown(self):
            pass

        def server_close(self):
            pass

    monkeypatch.setattr(web_launcher, "make_server", lambda host, port, app, threaded: captured.update(host=host, port=port, threaded=threaded) or Server())
    monkeypatch.setattr(web_launcher, "_available_port", lambda: 43123)
    monkeypatch.setattr(web_launcher.webbrowser, "open", lambda _url: True)
    assert web_launcher.main([]) == 0
    assert captured == {"host": "127.0.0.1", "port": 43123, "threaded": True}


def test_health_and_index_explain_local_non_diagnostic_use(app):
    client = app.test_client()
    assert client.get("/health").get_json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200
    assert "AI 진단 결과가 아닙니다" in page.get_data(as_text=True)
    assert "기본값은 꺼짐" in page.get_data(as_text=True)


def test_safe_upload_creates_private_job_and_five_downloads(app):
    response = upload(app.test_client(), relative_paths=json.dumps(["book/chapter.txt"]))
    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload["artifact_names"]) == set(ARTIFACTS)
    assert Path(app.config["WORK_ROOT"], payload["job_id"], "input", "book", "chapter.txt").read_bytes() == b"local manuscript"
    assert app.extensions["web_test_calls"] == [{"source": Path(app.config["WORK_ROOT"], payload["job_id"], "input", "book", "chapter.txt"), "language": "auto", "verify_links": False, "max_file_size": 50 * 1024 * 1024}]
    for artifact in ARTIFACTS:
        downloaded = app.test_client().get(payload["downloads"][artifact])
        assert downloaded.status_code == 200
        assert f'filename={artifact}' in downloaded.headers["Content-Disposition"]


def test_upload_rejects_traversal_extensions_size_and_count(app):
    client = app.test_client()
    assert upload(client, relative_paths=json.dumps(["../secret.txt"])).status_code == 400
    assert upload(client, name="malware.exe").status_code == 400
    app.config["MAX_UPLOAD_FILE_SIZE"] = 3
    assert upload(client, content=b"four").status_code == 400
    app.config["MAX_UPLOAD_FILES"] = 1
    response = client.post(f"/analyze?cap={app.config['LOCAL_CAPABILITY']}", data={"files": [(BytesIO(b"a"), "one.txt"), (BytesIO(b"b"), "two.txt")]}, content_type="multipart/form-data")
    assert response.status_code == 400
    for unsafe in ("C:/private.txt", "//server/share.txt", "CON.txt", "LPT1.txt", "folder:stream.txt"):
        assert upload(client, relative_paths=json.dumps([unsafe])).status_code == 400


def test_result_escapes_content_and_rejects_source_or_symlink_access(app):
    client = app.test_client()
    payload = upload(client).get_json()
    page = client.get(payload["result_url"])
    text = page.get_data(as_text=True)
    assert "&lt;script&gt;untrusted&lt;/script&gt;" in text
    assert "<script>untrusted</script>" not in text
    assert client.get(f'/download/{payload["job_id"]}/input/book.txt?cap={app.config["LOCAL_CAPABILITY"]}').status_code == 404
    artifact = Path(app.config["WORK_ROOT"], payload["job_id"], "artifacts", "report.html")
    artifact.unlink()
    artifact.symlink_to(Path(app.config["WORK_ROOT"], payload["job_id"], "artifacts", "report.json"))
    assert client.get(f'/download/{payload["job_id"]}/report.html?cap={app.config["LOCAL_CAPABILITY"]}').status_code == 404


def test_jobs_are_isolated_and_link_verification_requires_checkbox(app):
    client = app.test_client()
    first = upload(client, name="first.txt", content=b"first").get_json()
    second = upload(client, name="second.txt", content=b"second", verify_links="on", language="ko").get_json()
    assert first["job_id"] != second["job_id"]
    root = Path(app.config["WORK_ROOT"])
    assert (root / first["job_id"] / "input" / "first.txt").read_bytes() == b"first"
    assert not (root / first["job_id"] / "input" / "second.txt").exists()
    assert app.extensions["web_test_calls"][-2:][0]["verify_links"] is False
    assert app.extensions["web_test_calls"][-1]["verify_links"] is True
    assert app.extensions["web_test_calls"][-1]["language"] == "ko"
def test_capability_host_origin_and_shutdown_boundary(app):
    client = app.test_client()
    cap = app.config["LOCAL_CAPABILITY"]
    assert client.post("/analyze").status_code == 403
    assert client.get("/", headers={"Host": "example.invalid"}).status_code == 403
    assert client.post(f"/analyze?cap={cap}", headers={"Origin": "https://example.invalid"}).status_code == 403
    assert client.post(f"/analyze?cap={cap}", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    stopped = threading.Event()
    app.extensions["web_shutdown"] = stopped.set
    assert client.post("/shutdown").status_code == 403
    assert client.post(f"/shutdown?cap={cap}").status_code == 200
    assert stopped.wait(1)


def test_retention_quota_ttl_and_artifact_sanitizing(app):
    client = app.test_client()
    first = upload(client).get_json()
    root = str(Path(app.config["WORK_ROOT"]).resolve())
    private_paths = (root, r"C:\Users\alice\Books\private.epub", "/Users/alice/Books/private.epub")
    for artifact in ARTIFACTS:
        text = client.get(first["downloads"][artifact]).get_data(as_text=True)
        for private in private_paths:
            assert private not in text
            assert json.dumps(private)[1:-1] not in text
    app.config["MAX_RETAINED_JOBS"] = 1
    assert upload(client).status_code == 429
    app.config["JOB_TTL_SECONDS"] = 0
    time.sleep(0.01)
    assert client.get(first["result_url"]).status_code == 404
def test_concurrent_analysis_admission_returns_overload(app, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    count = 0
    count_lock = threading.Lock()

    def slow_analyze(*_args, **_kwargs):
        nonlocal count
        with count_lock:
            count += 1
            if count == 2:
                started.set()
        release.wait(1)
        return object()

    monkeypatch.setattr(web_app, "analyze_source", slow_analyze)
    threads = [threading.Thread(target=lambda: upload(app.test_client())) for _ in range(2)]
    for thread in threads:
        thread.start()
    assert started.wait(1)
    assert upload(app.test_client()).status_code == 429
    release.set()
    for thread in threads:
        thread.join()
def test_simultaneous_quota_reservations_enforce_count_and_bytes(app, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def slow_analyze(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(1)
        return object()

    def empty_reports(_report, output):
        output.mkdir(parents=True)
        for artifact in ARTIFACTS:
            (output / artifact).write_text("", encoding="utf-8")
        return {name: output / name for name in ARTIFACTS}

    monkeypatch.setattr(web_app, "analyze_source", slow_analyze)
    monkeypatch.setattr(web_app, "generate_reports", empty_reports)
    monkeypatch.setattr(web_app, "render_report_html", lambda _record: "")
    app.config.update(MAX_CONCURRENT_ANALYSES=2, MAX_RETAINED_JOBS=1, MAX_RETAINED_BYTES=1_000)
    first_result: list[object] = []
    first = threading.Thread(target=lambda: first_result.append(upload(app.test_client())))
    first.start()
    assert started.wait(1)
    assert upload(app.test_client()).status_code == 429
    release.set()
    first.join()
    assert first_result[0].status_code == 200
    assert calls == 1


def _write_root_marker(root: Path, pid: int, identity: str) -> None:
    root.mkdir()
    (root / web_app._ROOT_MARKER).write_text(
        f"{web_app._ROOT_MARKER_CONTENT}{pid}\n{identity}\n", encoding="ascii"
    )


def _mock_windows_process_api(monkeypatch, *, handle=123, error=0, creation=456, times=True):
    calls: list[tuple[object, ...]] = []

    class Kernel32:
        def OpenProcess(self, access, inherit, pid):
            calls.append(("open", access, inherit, pid))
            return handle

        def GetProcessTimes(self, process, created, exited, kernel, user):
            calls.append(("times", process))
            if times:
                created._obj.dwHighDateTime = creation >> 32
                created._obj.dwLowDateTime = creation & 0xFFFFFFFF
            return times

        def CloseHandle(self, process):
            calls.append(("close", process))
            return True

    monkeypatch.setattr(web_app, "_IS_WINDOWS", True)
    monkeypatch.setattr(web_app.ctypes, "windll", SimpleNamespace(kernel32=Kernel32()), raising=False)
    monkeypatch.setattr(web_app.ctypes, "get_last_error", lambda: error, raising=False)
    return calls


def test_windows_root_sweep_uses_process_identity_without_signaling(tmp_path, monkeypatch):
    current = tmp_path / "ebook-risk-current"
    current.mkdir()
    live = tmp_path / "ebook-risk-live"
    stale = tmp_path / "ebook-risk-stale"
    reused = tmp_path / "ebook-risk-reused"
    _write_root_marker(live, 100, "windows:456")
    _write_root_marker(stale, 101, "windows:111")
    _write_root_marker(reused, 102, "windows:111")
    calls = _mock_windows_process_api(monkeypatch, creation=456)
    monkeypatch.setattr(web_app.os, "kill", lambda *_args: pytest.fail("Windows cleanup must not signal processes"))

    web_app._sweep_stale_temporary_roots(current)

    assert live.exists()
    assert not stale.exists()
    assert not reused.exists()
    assert ("open", web_app._PROCESS_QUERY_LIMITED_INFORMATION, False, 100) in calls
    assert ("open", web_app._PROCESS_QUERY_LIMITED_INFORMATION, False, 101) in calls
    assert ("open", web_app._PROCESS_QUERY_LIMITED_INFORMATION, False, 102) in calls
    assert sum(call[0] == "close" for call in calls) == 3


def test_windows_root_sweep_removes_only_confirmed_stale_processes(tmp_path, monkeypatch):
    current = tmp_path / "ebook-risk-current"
    current.mkdir()
    stale = tmp_path / "ebook-risk-stale"
    _write_root_marker(stale, 100, "windows:456")
    calls = _mock_windows_process_api(monkeypatch, handle=0, error=web_app._ERROR_INVALID_PARAMETER)
    monkeypatch.setattr(web_app.os, "kill", lambda *_args: pytest.fail("Windows cleanup must not signal processes"))

    web_app._sweep_stale_temporary_roots(current)

    assert not stale.exists()
    assert calls == [("open", web_app._PROCESS_QUERY_LIMITED_INFORMATION, False, 100)]


@pytest.mark.parametrize("handle,error", [(0, 5), (123, 0)])
def test_windows_root_sweep_fails_closed_when_process_cannot_be_inspected(tmp_path, monkeypatch, handle, error):
    current = tmp_path / "ebook-risk-current"
    current.mkdir()
    protected = tmp_path / "ebook-risk-protected"
    _write_root_marker(protected, 100, "windows:456")
    _mock_windows_process_api(monkeypatch, handle=handle, error=error, times=handle != 123)
    monkeypatch.setattr(web_app.os, "kill", lambda *_args: pytest.fail("Windows cleanup must not signal processes"))

    web_app._sweep_stale_temporary_roots(current)

    assert protected.exists()


def test_posix_root_sweep_uses_kill_zero_only(tmp_path, monkeypatch):
    current = tmp_path / "ebook-risk-current"
    current.mkdir()
    alive = tmp_path / "ebook-risk-alive"
    stale = tmp_path / "ebook-risk-stale"
    _write_root_marker(alive, 100, "posix")
    _write_root_marker(stale, 101, "posix")
    calls: list[tuple[int, int]] = []

    monkeypatch.setattr(web_app, "_IS_WINDOWS", False)

    def fake_kill(pid, signal):
        calls.append((pid, signal))
        if pid == 101:
            raise ProcessLookupError

    monkeypatch.setattr(web_app.os, "kill", fake_kill)
    web_app._sweep_stale_temporary_roots(current)

    assert alive.exists()
    assert not stale.exists()
    assert sorted(calls) == [(100, 0), (101, 0)]
