import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from api.app import app, db, store


@pytest.fixture
def client():
    store._entries.clear()
    db.clear()
    return TestClient(app)


def create(client, **body):
    r = client.post("/simulations", json=body)
    assert r.status_code == 201, r.text
    return r.json()["info"]["run_id"]


def test_health_reports_persistence(client):
    p = client.get("/health").json()["persistence"]
    assert p["enabled"] is True
    create(client, scenario="small_warehouse")
    assert client.get("/health").json()["persistence"]["saved_runs"] == 1


def test_runs_are_saved_and_listed(client):
    rid = create(client, scenario="robot_failure")
    client.post(f"/simulations/{rid}/step", json={"ticks": 5})
    rows = client.get("/history").json()
    assert [r["run_id"] for r in rows] == [rid]
    assert rows[0]["live"] is True and rows[0]["tick"] == 5 and rows[0]["actions"] == 1
    d = client.get(f"/history/{rid}").json()
    assert d["metrics"]["tasks_created"] == 10 and d["scenario"] == "robot_failure"
    assert client.get("/history", params={"strategy": "baseline"}).json() == []
    assert client.get("/history/nope").status_code == 404


def test_evicted_run_can_be_resumed_exactly(client):
    rid = create(client, scenario="robot_failure", strategy="aegis")
    client.post(f"/simulations/{rid}/step", json={"ticks": 6})
    client.post(f"/simulations/{rid}/events", json={"type": "robot_failure", "robot_id": "R2"})
    client.post(f"/simulations/{rid}/step", json={"ticks": 4})
    before = client.get(f"/simulations/{rid}/state").json()

    store._entries.clear()                                   # as if the server restarted
    assert client.get(f"/simulations/{rid}").status_code == 404
    assert client.get("/history").json()[0]["live"] is False

    r = client.post(f"/history/{rid}/resume")
    assert r.status_code == 201 and r.json()["info"]["run_id"] == rid
    after = client.get(f"/simulations/{rid}/state").json()
    assert (after["tick"], after["robots"], after["tasks"]) == (before["tick"], before["robots"], before["tasks"])
    assert client.post(f"/simulations/{rid}/run").status_code == 200  # and it keeps working


def test_events_journal_and_reset(client):
    rid = create(client, scenario="robot_failure")
    client.post(f"/simulations/{rid}/step", json={"ticks": 3})
    client.post(f"/simulations/{rid}/events", json={"type": "robot_failure", "robot_id": "R1"})
    client.post(f"/simulations/{rid}/run")
    ops = [j["op"] for j in client.get(f"/history/{rid}/journal").json()]
    assert ops == ["step", "event", "run"]
    ev = client.get(f"/history/{rid}/events").json()
    assert any(e["type"] == "robot_failure" for e in ev)
    client.post(f"/simulations/{rid}/reset")
    assert client.get(f"/history/{rid}/journal").json() == []
    assert client.get(f"/history/{rid}").json()["tick"] == 0


def test_compare_shows_aegis_vs_baseline_from_history(client):
    assert client.get("/history/compare", params={"scenario": "robot_failure"}).status_code == 404
    for strat in ("baseline", "aegis"):
        rid = create(client, scenario="robot_failure", strategy=strat)
        client.post(f"/simulations/{rid}/run")
    c = client.get("/history/compare", params={"scenario": "robot_failure"}).json()
    assert c["aegis"]["completion_rate"] > c["baseline"]["completion_rate"]
    assert c["delta"]["completion_rate"] > 0 and c["delta"]["unserved_tasks"] < 0


def test_delete_history(client):
    rid = create(client, scenario="small_warehouse")
    assert client.delete(f"/history/{rid}").status_code == 204
    assert client.get(f"/simulations/{rid}").status_code == 404
    assert client.get(f"/history/{rid}").status_code == 404
    assert client.post(f"/history/{rid}/resume").status_code == 404


def test_benchmarks_are_remembered(client):
    client.post("/benchmarks", json={"scenarios": ["robot_failure"]})
    rows = client.get("/benchmarks/history").json()
    assert len(rows) == 2 and {r["strategy"] for r in rows} == {"baseline", "aegis"}
    assert rows[0]["batch_id"] == 1 and rows[0]["created_at"]
