import pytest

from fastapi.testclient import TestClient

from marketmind_ai.web.app import create_app


DEMO = {"ticker": "NVDA", "analysis_date": "2026-06-12", "llm_provider": "offline",
        "quick_model": "heuristic-fast", "deep_model": "heuristic-deep", "analysts": ["market"]}


def test_queued_job_is_visible_after_restart_without_credentials(tmp_path, monkeypatch):
    class HeldWorker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", HeldWorker)
    first = TestClient(create_app(str(tmp_path)))
    response = first.post("/api/runs", json={**DEMO, "api_key": "must-not-be-persisted",
        "research_objective": "company_overview", "research_horizon": "1_to_4_weeks"})
    assert response.status_code == 200
    run_id = response.json()["run_id"]
    assert first.get(f"/api/runs/{run_id}").json()["status"] == "queued"
    restarted = TestClient(create_app(str(tmp_path)))
    result = restarted.get(f"/api/runs/{run_id}/result")
    assert result.status_code == 200
    assert result.json()["status"] == "error"
    assert result.json()["job_status"] == "interrupted"
    assert result.json()["research_objective"] == "company_overview"
    assert result.json()["research_horizon"] == "1_to_4_weeks"
    assert restarted.get("/api/jobs?status=interrupted").json()[0]["run_id"] == run_id
    sse = restarted.get(f"/api/runs/{run_id}/stream").text
    assert "event: complete" in sse and "interrupted" in sse
    assert b"must-not-be-persisted" not in (tmp_path / "jobs.sqlite3").read_bytes()


def test_running_job_preserves_snapshot_reference_after_restart(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from marketmind_ai.graph.marketmind_graph import MarketMindGraph

    workers = []

    class HeldWorker:
        def __init__(self, target, args, **kwargs):
            workers.append((target, args))

        def start(self):
            pass

    class LostProcess(BaseException):
        pass

    snapshot_id = "a" * 32

    def interrupted_stream(self, request, *, run_id):
        yield SimpleNamespace(to_dict=lambda: {
            "run_id": run_id, "status": "running", "ticker": "NVDA", "data_mode": "demo",
            "current_agent": "Market Analyst", "data_snapshot": {"snapshot_id": snapshot_id},
        })
        raise LostProcess()

    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", HeldWorker)
    monkeypatch.setattr(MarketMindGraph, "stream", interrupted_stream)
    first = TestClient(create_app(str(tmp_path)))
    run_id = first.post("/api/runs", json=DEMO).json()["run_id"]
    target, args = workers[0]
    with pytest.raises(LostProcess):
        target(*args)
    restarted = TestClient(create_app(str(tmp_path)))
    result = restarted.get(f"/api/runs/{run_id}/result").json()
    assert result["job_status"] == "interrupted"
    assert result["data_snapshot"]["snapshot_id"] == snapshot_id
    assert result["current_agent"] == "Market Analyst"


def test_third_job_is_rejected_and_slot_is_released_on_start_failure(tmp_path, monkeypatch):
    class HeldWorker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    class BrokenWorker(HeldWorker):
        def start(self):
            raise RuntimeError("private credential in exception")

    client = TestClient(create_app(str(tmp_path)))
    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", BrokenWorker)
    response = client.post("/api/runs", json=DEMO)
    assert response.status_code == 503
    assert "private credential" not in response.text
    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", HeldWorker)
    assert client.post("/api/runs", json=DEMO).status_code == 200
    assert client.post("/api/runs", json=DEMO).status_code == 200
    third = client.post("/api/runs", json=DEMO)
    assert third.status_code == 503
    assert third.headers.get("Retry-After")


def test_completed_archive_wins_if_worker_died_before_clearing_job(tmp_path, monkeypatch):
    from marketmind_ai.graph.marketmind_graph import MarketMindGraph

    class HeldWorker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", HeldWorker)
    first = TestClient(create_app(str(tmp_path)))
    run_id = first.post("/api/runs", json=DEMO).json()["run_id"]
    graph = MarketMindGraph(storage_root=tmp_path)
    completed = {"run_id": run_id, "status": "completed", "final_signal": "No Recommendation"}
    graph.archive.save_web_snapshot(run_id, completed)
    restarted = TestClient(create_app(str(tmp_path)))
    assert restarted.get(f"/api/runs/{run_id}/result").json() == completed
    assert restarted.get("/api/jobs").json() == []


def test_failed_archive_write_leaves_previous_report_readable(tmp_path):
    from marketmind_ai.graph.marketmind_graph import MarketMindGraph

    graph = MarketMindGraph(storage_root=tmp_path)
    previous = {"run_id": "run-a", "status": "completed"}
    graph.archive.save_web_snapshot("run-a", previous)
    with pytest.raises(TypeError):
        graph.archive.save_web_snapshot("run-a", {"unserializable": object()})
    assert graph.archive.load("run-a") == previous


def test_recovery_finds_frozen_manifest_created_before_job_update(tmp_path, monkeypatch):
    from marketmind_ai.dataflows.source_records import ResearchDataSnapshot
    from marketmind_ai.dataflows.source_store import SourceStore

    class HeldWorker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", HeldWorker)
    first = TestClient(create_app(str(tmp_path)))
    run_id = first.post("/api/runs", json=DEMO).json()["run_id"]
    snapshot = ResearchDataSnapshot(origin_run_id=run_id, original_input="NVDA", symbol="NVDA", data_mode="demo",
        cutoff={"requested_date": DEMO["analysis_date"]}, resolution={"resolved_symbol": "NVDA"}, availability={})
    SourceStore(tmp_path / "sources").save(snapshot)
    restarted = TestClient(create_app(str(tmp_path)))
    recovered = restarted.get("/api/jobs").json()[0]
    assert recovered["data_snapshot"]["snapshot_id"] == snapshot.snapshot_id


def test_old_revision_error_does_not_hide_a_new_interrupted_attempt(tmp_path, monkeypatch):
    from marketmind_ai.graph.marketmind_graph import MarketMindGraph

    class HeldWorker:
        def __init__(self, **kwargs):
            pass

        def start(self):
            pass

    monkeypatch.setattr("marketmind_ai.web.app.AnalysisThread", HeldWorker)
    first = TestClient(create_app(str(tmp_path)))
    run_id = first.post("/api/runs", json=DEMO).json()["run_id"]
    graph = MarketMindGraph(storage_root=tmp_path)
    graph.archive.save_web_snapshot(run_id, {"run_id": run_id, "status": "error", "finished_at": "2020-06-12T21:00:00Z"})
    restarted = TestClient(create_app(str(tmp_path)))
    assert restarted.get(f"/api/runs/{run_id}/result").json()["job_status"] == "interrupted"
    assert restarted.get("/api/jobs").json()[0]["run_id"] == run_id


def test_redaction_preserves_recovery_identifiers(tmp_path):
    from marketmind_ai.web.jobs import JobStore

    store = JobStore(tmp_path)
    snapshot_id = "a" * 32
    store.save({"run_id": "abc123", "status": "queued", "original_input": "token-a",
                "data_snapshot": {"snapshot_id": snapshot_id}}, "a")
    job, = JobStore(tmp_path).interrupted()
    assert job["run_id"] == "abc123"
    assert job["data_snapshot"]["snapshot_id"] == snapshot_id
    assert job["original_input"] == "token-[redacted]"
