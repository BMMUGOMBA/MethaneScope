"""Lesson 2.6 unit tests: do not require Docker or modify NASA data."""
import json
from pathlib import Path

from methanescope import monitor


def test_health_status_ok_when_all_pass():
    assert monitor.classify_health_checks([{"status": "OK"}]) == "OK"


def test_health_warning_and_critical_precedence():
    assert monitor.classify_health_checks([{"status": "OK"}, {"status": "WARN"}]) == "WARN"
    assert monitor.classify_health_checks([{"status": "WARN"}, {"status": "CRITICAL"}]) == "CRITICAL"


def test_report_history_handles_bad_json(tmp_path):
    history = tmp_path / "runs.jsonl"
    history.write_text('{"result":"SUCCESS"}\nnot json\n{"result":"FAILED"}\n', encoding="utf-8")
    assert [x["result"] for x in monitor.read_history(history)] == ["SUCCESS", "FAILED"]


def test_health_marks_missing_data_as_critical(tmp_path, monkeypatch):
    (tmp_path / "outputs" / "emit_batch").mkdir(parents=True)
    # No need for a DB during this unit test.
    snapshot = monitor.health_snapshot(tmp_path, check_db=False)
    assert snapshot["status"] == "CRITICAL"
    assert all(row["check"] != "postgresql_postgis" for row in snapshot["checks"])


def test_run_once_preflight_blocked_no_data_is_safe(tmp_path):
    (tmp_path / "outputs").mkdir()
    result = monitor.run_once(tmp_path)
    assert result["result"] == "FAILED"
    assert result["failure_class"] == "PREFLIGHT"
    assert (tmp_path / "outputs" / "monitoring" / "alerts.jsonl").exists()


def test_atomic_output(tmp_path):
    target = tmp_path / "last_health.json"
    monitor.write_json_atomic(target, {"status": "OK"})
    assert json.loads(target.read_text())["status"] == "OK"
    assert not (tmp_path / "last_health.json.tmp").exists()
