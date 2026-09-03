import multiprocessing as mp


def _child_import_worker():
    import worker  # noqa: F401


def test_worker_import_is_spawn_safe():
    ctx = mp.get_context("spawn")
    process = ctx.Process(target=_child_import_worker)
    process.start()
    process.join(timeout=30)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
        raise AssertionError("spawned worker import did not finish")
    assert process.exitcode == 0
