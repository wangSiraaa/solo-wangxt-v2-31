"""FastAPI 入口：场景与运行记录的 CRUD、仿真执行、事件流回放。"""
from __future__ import annotations

import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from . import db
from .scenarios_data import DEMO_SCENARIOS
from .schemas import RunRequest, ScenarioConfig, ScenarioIn, ScenarioOut
from .service import canonical_hash, run_simulation

app = FastAPI(title="排班技能路由仿真 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    seed_demo_scenarios()


def seed_demo_scenarios() -> None:
    with db.get_session() as session:
        for sid, builder in DEMO_SCENARIOS:
            if session.get(db.ScenarioRow, sid):
                continue
            cfg = builder()
            row = db.ScenarioRow(
                id=sid,
                name=cfg["name"],
                description=cfg.get("description", ""),
                config_json=json.dumps(cfg, ensure_ascii=False) if not db._IS_PG else cfg,
                default_seed=cfg.get("default_seed", 42),
            )
            session.add(row)
        session.commit()


def _config_of(row: db.ScenarioRow) -> dict:
    raw = row.config_json
    return json.loads(raw) if isinstance(raw, str) else raw


def _metrics_of(row: db.RunRow) -> dict:
    raw = row.metrics_json
    return json.loads(raw) if isinstance(raw, str) else raw


def _events_of(row: db.RunRow) -> list[dict]:
    raw = row.events_json
    return json.loads(raw) if isinstance(raw, str) else raw


@app.get("/api/health")
def health():
    return {"status": "ok", "database": "postgresql" if db._IS_PG else "sqlite"}


@app.get("/api/scenarios", response_model=list[ScenarioOut])
def list_scenarios():
    with db.get_session() as session:
        rows = session.query(db.ScenarioRow).order_by(db.ScenarioRow.created_at).all()
        return [
            ScenarioOut(id=r.id, name=r.name, description=r.description,
                        config=_config_of(r), default_seed=r.default_seed)
            for r in rows
        ]


@app.get("/api/scenarios/{scenario_id}", response_model=ScenarioOut)
def get_scenario(scenario_id: str):
    with db.get_session() as session:
        row = session.get(db.ScenarioRow, scenario_id)
        if not row:
            raise HTTPException(404, "场景不存在")
        return ScenarioOut(id=row.id, name=row.name, description=row.description,
                           config=_config_of(row), default_seed=row.default_seed)


@app.post("/api/scenarios", response_model=ScenarioOut)
def create_scenario(body: ScenarioIn):
    # 先校验配置合法
    try:
        ScenarioConfig.model_validate(body.config)
    except ValidationError as e:
        raise HTTPException(422, f"场景配置不合法: {e.errors()}")
    sid = db.new_id()
    stored = json.dumps(body.config, ensure_ascii=False) if not db._IS_PG else body.config
    with db.get_session() as session:
        row = db.ScenarioRow(
            id=sid, name=body.name, description=body.description,
            config_json=stored, default_seed=body.default_seed,
        )
        session.add(row)
        session.commit()
    return ScenarioOut(id=sid, name=body.name, description=body.description,
                       config=body.config, default_seed=body.default_seed)


@app.post("/api/runs")
def create_run(body: RunRequest):
    if body.config is not None:
        raw_config = body.config
        try:
            ScenarioConfig.model_validate(raw_config)
        except ValidationError as e:
            raise HTTPException(422, f"场景配置不合法: {e.errors()}")
    else:
        if not body.scenario_id:
            raise HTTPException(400, "必须提供 scenario_id 或内联 config")
        with db.get_session() as session:
            row = session.get(db.ScenarioRow, body.scenario_id)
            if not row:
                raise HTTPException(404, "场景不存在")
            raw_config = _config_of(row)

    result = run_simulation(raw_config, body.seed, label=body.label)
    m, e = result["metrics"], result["events"]
    run_id = db.new_id()
    with db.get_session() as session:
        row = db.RunRow(
            id=run_id,
            scenario_id=body.scenario_id,
            seed=body.seed,
            label=body.label,
            metrics_json=json.dumps(m, ensure_ascii=False) if not db._IS_PG else m,
            events_json=json.dumps(e, ensure_ascii=False) if not db._IS_PG else e,
            event_hash=result["event_hash"],
            event_count=result["event_count"],
            planned_calls=result["planned_calls"],
            horizon_sec=result["horizon_sec"],
        )
        session.add(row)
        session.commit()
    return {"run_id": run_id, "event_hash": result["event_hash"], "event_count": result["event_count"]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, include_events: bool = True):
    with db.get_session() as session:
        row = session.get(db.RunRow, run_id)
        if not row:
            raise HTTPException(404, "运行不存在")
        payload = {
            "run_id": row.id,
            "scenario_id": row.scenario_id,
            "seed": row.seed,
            "label": row.label,
            "event_hash": row.event_hash,
            "event_count": row.event_count,
            "planned_calls": row.planned_calls,
            "horizon_sec": row.horizon_sec,
            "metrics": _metrics_of(row),
        }
        if include_events:
            payload["events"] = _events_of(row)
        return payload


@app.get("/api/runs")
def list_runs(scenario_id: str | None = None, limit: int = 50):
    with db.get_session() as session:
        q = session.query(db.RunRow).order_by(db.RunRow.created_at.desc())
        if scenario_id:
            q = q.filter(db.RunRow.scenario_id == scenario_id)
        rows = q.limit(limit).all()
        return [
            {
                "run_id": r.id,
                "scenario_id": r.scenario_id,
                "seed": r.seed,
                "label": r.label,
                "event_hash": r.event_hash,
                "event_count": r.event_count,
                "planned_calls": r.planned_calls,
            }
            for r in rows
        ]


@app.post("/api/runs/{run_id}/verify")
def verify_run(run_id: str):
    """用存储的事件重算哈希，校验事件流未被篡改。"""
    with db.get_session() as session:
        row = session.get(db.RunRow, run_id)
        if not row:
            raise HTTPException(404, "运行不存在")
        events = _events_of(row)
        digest = canonical_hash(events)
        return {"stored_hash": row.event_hash, "recomputed_hash": digest,
                "ok": digest == row.event_hash}
