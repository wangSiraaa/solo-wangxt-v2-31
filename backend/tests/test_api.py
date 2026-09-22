"""API 端到端测试：建场景 -> 运行 -> 取事件 -> 校验哈希。使用临时 SQLite。"""
from __future__ import annotations

import importlib
import os
import tempfile

import pytest


@pytest.fixture()
def client(monkeypatch):
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    import app.db as db
    importlib.reload(db)
    import app.main as main
    importlib.reload(main)
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        # startup 事件已执行 init_db() 与 seed_demo_scenarios()
        yield c
    os.close(db_fd)
    os.unlink(db_path)


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_demo_scenarios_seeded(client):
    r = client.get("/api/scenarios")
    names = [s["name"] for s in r.json()]
    assert any("跨班次" in n for n in names)
    assert any("稀缺技能 A" in n for n in names)
    assert any("稀缺技能 B" in n for n in names)


def test_run_and_fetch_events_and_verify(client):
    sid = client.get("/api/scenarios").json()[0]["id"]
    r1 = client.post("/api/runs", json={"scenario_id": sid, "seed": 42})
    assert r1.status_code == 200
    run_id = r1.json()["run_id"]

    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["seed"] == 42
    assert len(detail["events"]) == detail["event_count"]
    assert detail["metrics"]["total_calls"] > 0
    assert detail["events"][0]["type"] == "SIM_START"

    # 校验接口：存储事件重算哈希一致
    v = client.post(f"/api/runs/{run_id}/verify").json()
    assert v["ok"] is True

    # 重复运行同种子 -> 同哈希
    r2 = client.post("/api/runs", json={"scenario_id": sid, "seed": 42}).json()
    assert r2["event_hash"] == r1.json()["event_hash"]


def test_scarce_ab_pair_same_plan_different_outcomes(client):
    scenarios = {s["name"]: s["id"] for s in client.get("/api/scenarios").json()}
    id_a = next(v for k, v in scenarios.items() if "稀缺技能 A" in k)
    id_b = next(v for k, v in scenarios.items() if "稀缺技能 B" in k)

    ra = client.post("/api/runs", json={"scenario_id": id_a, "seed": 42}).json()
    rb = client.post("/api/runs", json={"scenario_id": id_b, "seed": 42}).json()

    da = client.get(f"/api/runs/{ra['run_id']}").json()
    db_ = client.get(f"/api/runs/{rb['run_id']}").json()
    # 来电计划一致
    arr = lambda d: [(e["t"], e["call_id"]) for e in d["events"] if e["type"] == "ARRIVAL"]
    assert arr(da) == arr(db_)
    # B 出现溢出事件，A 没有
    assert not any(e["type"] == "OVERFLOW" for e in da["events"])
    assert any(e["type"] == "OVERFLOW" for e in db_["events"])
