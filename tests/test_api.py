import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from api.app import app, store


@pytest.fixture
def client():
    store._entries.clear()
    return TestClient(app)


def create(client, **body):
    r = client.post("/simulations", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_health_limits_and_scenarios(client):
    assert client.get("/health").json()["status"] == "ok"
    lim = client.get("/limits").json()
    assert lim["max_robots"] >= 10 and lim["max_width"] >= 30
    names = {s["name"] for s in client.get("/scenarios").json()}
    assert {"robot_failure", "small_warehouse"} <= names


def test_create_named_scenario_and_state(client):
    c = create(client, scenario="robot_failure", strategy="aegis")
    assert c["info"]["robots"] == 3 and c["info"]["width"] == 17
    st = client.get(f"/simulations/{c['info']['run_id']}/state").json()
    assert st["map"]["height"] == 10 and len(st["robots"]) == 3 and st["tick"] == 0


@pytest.mark.parametrize("w,h,r,t", [(9, 7, 2, 4), (25, 16, 6, 18), (40, 25, 12, 30)])
def test_custom_grid_and_robot_count_are_honoured(client, w, h, r, t):
    c = create(client, custom={"width": w, "height": h, "robots": r, "tasks": t, "seed": 3})
    assert (c["info"]["width"], c["info"]["height"], c["info"]["robots"], c["info"]["tasks"]) == (w, h, r, t)
    assert c["state"]["map"]["width"] == w
    rid = c["info"]["run_id"]
    done = client.post(f"/simulations/{rid}/run").json()
    assert done["status"] in ("finished", "stalled")
    m = client.get(f"/simulations/{rid}/metrics").json()
    assert m["tasks_created"] == t and m["collisions"] == 0 and m["completion_rate"] == 100.0


def test_custom_defaults_three_tasks_per_robot(client):
    c = create(client, custom={"robots": 4})
    assert c["info"]["tasks"] == 12


@pytest.mark.parametrize("custom", [
    {"width": 3}, {"width": 500}, {"height": 1}, {"robots": 0}, {"robots": 999},
    {"width": 5, "robots": 8},            # more robots than start cells
    {"tasks": 9999},
])
def test_custom_validation_rejects_bad_sizes(client, custom):
    assert client.post("/simulations", json={"custom": custom}).status_code == 422


def test_create_needs_exactly_one_source(client):
    assert client.post("/simulations", json={}).status_code == 422
    both = {"scenario": "robot_failure", "custom": {}}
    assert client.post("/simulations", json=both).status_code == 422
    assert client.post("/simulations", json={"scenario": "nope"}).status_code == 404
    assert client.post("/simulations", json={"scenario": "../../etc/passwd"}).status_code == 404


def test_step_reset_delete_and_404s(client):
    rid = create(client, scenario="small_warehouse")["info"]["run_id"]
    assert client.post(f"/simulations/{rid}/step", json={"ticks": 5}).json()["tick"] == 5
    assert client.post(f"/simulations/{rid}/step").json()["tick"] == 6          # default body
    assert client.post(f"/simulations/{rid}/step", json={"ticks": 0}).status_code == 422
    assert client.post(f"/simulations/{rid}/reset").json()["tick"] == 0
    assert client.delete(f"/simulations/{rid}").status_code == 204
    for path in ("", "/state", "/metrics", "/events"):
        assert client.get(f"/simulations/{rid}{path}").status_code == 404
    assert client.delete(f"/simulations/{rid}").status_code == 404


def test_failure_event_triggers_recovery_via_api(client):
    rid = create(client, scenario="small_warehouse", strategy="aegis")["info"]["run_id"]
    client.post(f"/simulations/{rid}/step", json={"ticks": 5})
    r = client.post(f"/simulations/{rid}/events", json={"type": "robot_failure", "robot_id": "R2"})
    assert r.status_code == 200 and r.json()["applied"] is True
    kinds = [e["type"] for e in r.json()["log"]]
    assert "robot_failure" in kinds and "recovery" in kinds
    states = {x["robot_id"]: x["status"] for x in r.json()["state"]["robots"]}
    assert states["R2"] == "UNAVAILABLE"
    # failing it twice is a conflict, not a crash
    again = client.post(f"/simulations/{rid}/events", json={"type": "robot_failure", "robot_id": "R2"})
    assert again.status_code == 409


def test_event_validation_errors(client):
    rid = create(client, scenario="small_warehouse")["info"]["run_id"]
    post = lambda body: client.post(f"/simulations/{rid}/events", json=body)
    assert post({"type": "robot_failure", "robot_id": "R99"}).status_code == 404
    assert post({"type": "block_cell", "cell": [999, 0]}).status_code == 422
    assert post({"type": "block_cell", "cell": [2, 1]}).status_code == 409      # shelf
    assert post({"type": "explode"}).status_code == 422
    assert post({"type": "block_cell"}).status_code == 422
    bad_task = {"type": "add_task", "task": {"id": "X", "pickup": [0, 0], "delivery": [0, 0]}}
    assert post(bad_task).status_code == 422                                     # pickup == delivery
    ok = {"type": "add_task", "task": {"id": "X1", "pickup": [0, 3], "delivery": [16, 9], "priority": 3}}
    assert post(ok).status_code == 200
    assert post(ok).status_code == 409                                           # duplicate id
    assert client.get(f"/simulations/{rid}/metrics").json()["tasks_created"] == 11


def test_block_unblock_roundtrip(client):
    rid = create(client, scenario="small_warehouse")["info"]["run_id"]
    r = client.post(f"/simulations/{rid}/events", json={"type": "block_cell", "cell": [4, 3]})
    assert [4, 3] in r.json()["state"]["blocked"]
    r = client.post(f"/simulations/{rid}/events", json={"type": "unblock_cell", "cell": [4, 3]})
    assert r.json()["state"]["blocked"] == []


def test_scheduled_events_in_custom_config(client):
    custom = {"width": 17, "height": 10, "robots": 3, "tasks": 9, "seed": 1,
              "events": [{"tick": 4, "event": {"type": "robot_failure", "robot_id": "R2"}}]}
    rid = create(client, custom=custom, strategy="aegis")["info"]["run_id"]
    client.post(f"/simulations/{rid}/run")
    log = client.get(f"/simulations/{rid}/events", params={"limit": 1000}).json()
    assert any(e["type"] == "robot_failure" for e in log)
    bad = dict(custom, events=[{"tick": 4, "event": {"type": "robot_failure", "robot_id": "R9"}}])
    assert client.post("/simulations", json={"custom": bad}).status_code == 422


def test_benchmarks_compare_both_strategies(client):
    r = client.post("/benchmarks", json={"scenarios": ["robot_failure"]})
    assert r.status_code == 200 and r.json()["count"] == 2
    by = {row["strategy"]: row for row in r.json()["rows"]}
    assert by["aegis"]["completion_rate"] > by["baseline"]["completion_rate"]
    r = client.post("/benchmarks", json={"custom": {"width": 21, "height": 13, "robots": 5, "seed": 2}})
    assert r.json()["count"] == 2 and all(x["collisions"] == 0 for x in r.json()["rows"])
    assert client.post("/benchmarks", json={"scenarios": ["nope"]}).status_code == 404
    assert client.post("/benchmarks").json()["count"] >= 10                      # all named x 2


def test_live_simulation_cap_evicts_oldest(client):
    store.max_live = 3
    try:
        ids = [create(client, scenario="small_warehouse")["info"]["run_id"] for _ in range(5)]
        assert len(client.get("/simulations").json()) == 3
        assert client.get(f"/simulations/{ids[0]}").status_code == 404
        assert client.get(f"/simulations/{ids[-1]}").status_code == 200
    finally:
        store.max_live = 50


def test_openapi_schema_builds(client):
    spec = client.get("/openapi.json").json()
    assert "/simulations/{run_id}/events" in spec["paths"] and "/benchmarks" in spec["paths"]
