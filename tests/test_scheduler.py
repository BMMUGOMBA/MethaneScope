"""Lesson 2.9 — isolated concurrency, retry and opt-in tests. No Docker required."""
from pathlib import Path
import pytest
from methanescope import scheduler


def make_project(tmp_path, mode="real"):
    (tmp_path / "data").mkdir()
    (tmp_path / "methanescope").mkdir()
    (tmp_path / "methanescope" / "monitor.py").write_text("# placeholder")
    return tmp_path


def fake_plan(mode="real"):
    return {"mode": mode, "accepted_rows": 1, "accepted_granules": ["TEST"],
            "candidate_rasters": 1, "unmatched_rasters": 0}


def test_backoff_is_exponential_and_capped():
    assert scheduler.exponential_wait(1, 2) == 2
    assert scheduler.exponential_wait(2, 2) == 4
    assert scheduler.exponential_wait(6, 2) == 30


def test_local_lock_prevents_overlapping_runs(tmp_path):
    with scheduler.exclusive_project_lock(tmp_path):
        with pytest.raises(scheduler.LockBusyError):
            with scheduler.exclusive_project_lock(tmp_path):
                pass
    assert not (tmp_path / "outputs/scheduler/.ingestion.lock").exists()


def test_crash_lock_is_not_automatically_removed(tmp_path):
    lockdir = tmp_path / "outputs/scheduler"
    lockdir.mkdir(parents=True)
    p = lockdir / ".ingestion.lock"
    p.write_text('{"pid": 999999}', encoding="utf-8")
    with pytest.raises(scheduler.LockBusyError):
        with scheduler.exclusive_project_lock(tmp_path):
            pass
    assert p.exists()


def test_dry_run_never_executes_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "plan", lambda _: fake_plan())
    def fail(_):
        raise AssertionError("run_once should not be called")
    got = scheduler.run_safely(tmp_path, execute=False, monitored_run=fail)
    assert got["result"] == "DRY_RUN"
    assert not (tmp_path / "outputs/scheduler/last_schedule_run.json").exists()


def test_demo_is_blocked_without_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "plan", lambda _: fake_plan("demo"))
    with pytest.raises(ValueError, match="DEMO"):
        scheduler.run_safely(tmp_path, execute=True)


def test_validation_failure_does_not_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "plan", lambda _: fake_plan())
    calls = []
    def runner(_):
        calls.append(1)
        return {"result": "FAILED", "failure_class": "DATA_VALIDATION", "message": "bad data"}
    result = scheduler.run_safely(tmp_path, execute=True, monitored_run=runner,
                                  sleep_fn=lambda _: pytest.fail("unexpected retry"))
    assert result["result"] == "FAILED" and len(calls) == 1


def test_temporary_database_failure_retries_then_recovers(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "plan", lambda _: fake_plan())
    waits = []
    events = [
        {"result": "FAILED", "failure_class": "PREFLIGHT", "message": "db offline",
         "preflight": {"checks": [{"check": "postgresql_postgis", "status": "CRITICAL"}]}},
        {"result": "SUCCESS", "failure_class": None, "message": "recovered"},
    ]
    def runner(_):
        return events.pop(0)
    result = scheduler.run_safely(tmp_path, execute=True, monitored_run=runner,
                                  sleep_fn=waits.append)
    assert result["result"] == "SUCCESS"
    assert result["attempt_count"] == 2
    assert waits == [2]
    assert (tmp_path / "outputs/scheduler/last_schedule_run.json").exists()
    assert not (tmp_path / "outputs/scheduler/.ingestion.lock").exists()


def test_other_preflight_critical_does_not_retry():
    event = {"result": "FAILED", "failure_class": "PREFLIGHT",
             "preflight": {"checks": [
                 {"check": "postgresql_postgis", "status": "CRITICAL"},
                 {"check": "accepted_manifest", "status": "CRITICAL"}]}}
    assert not scheduler.retryable_db_preflight(event)


def test_exception_releases_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "plan", lambda _: fake_plan())
    with pytest.raises(ZeroDivisionError):
        scheduler.run_safely(tmp_path, execute=True, monitored_run=lambda _: 1 / 0)
    assert not (tmp_path / "outputs/scheduler/.ingestion.lock").exists()
