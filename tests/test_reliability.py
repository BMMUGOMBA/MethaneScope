"""Lesson 2.8: isolated reliability tests; no actual Docker, DB, or NASA access."""
from pathlib import Path
from unittest.mock import patch
import json

from methanescope import monitor, pipeline


def good_health():
    return {"status":"OK", "checks":[], "scientific_validation":"NOT_ESTABLISHED"}


def test_preflight_failure_blocks_commands(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        return {"status":"CRITICAL", "checks":[], "scientific_validation":"NOT_ESTABLISHED"}
    monkeypatch.setattr(monitor, "health_snapshot", unavailable)
    with patch.object(pipeline, "run", side_effect=AssertionError("must not execute")):
        result = monitor.run_once(tmp_path)
    assert result["result"] == "FAILED"
    assert result["failure_class"] == "PREFLIGHT"
    assert (tmp_path / "outputs/monitoring/alerts.jsonl").exists()


def test_validation_failure_never_ingests(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "health_snapshot", lambda *a, **kw: good_health())
    called=[]
    def fake_run(args):
        called.append(args[0])
        assert args[0] == "validate"
        return 1
    monkeypatch.setattr(pipeline, "run", fake_run)
    result = monitor.run_once(tmp_path)
    assert called == ["validate"]
    assert result["failure_class"] == "DATA_VALIDATION"
    assert "ingestion_exit_code" not in result


def test_ingestion_failure_records_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "health_snapshot", lambda *a, **kw: good_health())
    called=[]
    def fake_run(args):
        called.append(args[0])
        return 0 if args[0] == "validate" else 1
    monkeypatch.setattr(pipeline, "run", fake_run)
    result = monitor.run_once(tmp_path)
    assert called == ["validate", "ingest"]
    assert result["failure_class"] == "INGESTION"
    alerts = (tmp_path / "outputs/monitoring/alerts.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(alerts[-1])["failure_class"] == "INGESTION"


def test_exception_recorded_as_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "health_snapshot", lambda *a, **kw: good_health())
    def fake_run(args):
        if args[0] == "validate":
            return 0
        raise ConnectionError("simulated DB outage")
    monkeypatch.setattr(pipeline, "run", fake_run)
    result = monitor.run_once(tmp_path)
    assert result["result"] == "FAILED"
    assert result["failure_class"] == "EXCEPTION"
    assert "simulated DB outage" in result["message"]


def test_recovered_run_creates_history_without_alert(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "health_snapshot", lambda *a, **kw: good_health())
    monkeypatch.setattr(pipeline, "run", lambda args: 0)
    result = monitor.run_once(tmp_path)
    assert result["result"] == "SUCCESS"
    assert len(monitor.read_history(tmp_path / "outputs/monitoring/run_history.jsonl")) == 1
    assert not (tmp_path / "outputs/monitoring/alerts.jsonl").exists()
