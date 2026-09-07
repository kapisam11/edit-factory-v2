import importlib
import multiprocessing
import threading
import time


def _load_dashboard(monkeypatch, tmp_path):
    monkeypatch.setenv("AIVF_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("AIVF_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("AIVF_OUTPUT_DIR", str(tmp_path / "output"))
    import web_app_v2
    importlib.reload(web_app_v2)
    return web_app_v2


def test_sqlite_concurrent_log_writes(monkeypatch, tmp_path):
    appmod = _load_dashboard(monkeypatch, tmp_path)
    appmod.db_insert_job("job-test", "topic", {"topic": "topic"})
    failures = []

    def writer(worker_id):
        try:
            for i in range(50):
                appmod.db_append_log("job-test", "INFO", f"{worker_id}:{i}")
        except Exception as exc:
            failures.append(exc)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert len(appmod.db_logs_since("job-test")) == 400


def test_startup_reconciles_non_terminal_jobs(monkeypatch, tmp_path):
    appmod = _load_dashboard(monkeypatch, tmp_path)
    appmod.db_insert_job("queued", "queued", {"topic": "queued"})
    appmod.db_insert_job("running", "running", {"topic": "running"})
    appmod.db_update_job("running", status="running")
    importlib.reload(appmod)
    assert appmod.db_get_job("queued")["status"] == "interrupted"
    assert appmod.db_get_job("running")["status"] == "interrupted"


def test_real_worker_process_can_be_terminated(tmp_path):
    from dashboard_compat import _terminate_process_tree
    ctx = multiprocessing.get_context("spawn")
    process = ctx.Process(target=time.sleep, args=(60,), daemon=False)
    process.start()
    try:
        assert process.is_alive()
        _terminate_process_tree(process)
        assert not process.is_alive()
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=5)


def test_cancellation_does_not_overwrite_terminal_job(monkeypatch, tmp_path):
    appmod = _load_dashboard(monkeypatch, tmp_path)
    appmod.db_insert_job("job-done", "topic", {"topic": "topic"})
    appmod.db_update_job("job-done", status="done", step="Complete")

    from dashboard_compat import cancel_process

    with appmod.app.test_request_context("/api/jobs/job-done/cancel", method="POST"):
        response, status = cancel_process("job-done")

    assert status == 409
    assert response.get_json()["status"] == "done"
    assert appmod.db_get_job("job-done")["status"] == "done"
