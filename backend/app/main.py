from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models
from .database import Base, SessionLocal, engine, get_db
from .scenarios import SCENARIO_LIBRARY
from .schemas import RunRequest, RunResponse, ScenarioInput, ScenarioResponse, ScenarioSave
from .simulation import run_simulation

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_library()
    yield


app = FastAPI(
    title="客服排班技能路由仿真 API",
    description="用 SimPy 离散事件生成可审计事件流，并从事件投影统计指标。",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200", "http://127.0.0.1:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def seed_library() -> None:
    with SessionLocal() as db:
        existing = {name: db.scalar(select(models.Scenario).where(models.Scenario.name == name))
                    for name in SCENARIO_LIBRARY}
        changed = False
        for name, payload in SCENARIO_LIBRARY.items():
            if existing[name] is None:
                db.add(models.Scenario(name=name, seed=9901, payload=payload))
                changed = True
        if changed:
            db.commit()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/scenarios", response_model=list[ScenarioResponse])
def list_scenarios(db: Session = Depends(get_db)):
    rows = db.scalars(select(models.Scenario).order_by(models.Scenario.id)).all()
    return [{"id": row.id, "seed": row.seed, **row.payload} for row in rows]


@app.get("/api/scenarios/{scenario_id}", response_model=ScenarioResponse)
def get_scenario(scenario_id: int, db: Session = Depends(get_db)):
    row = db.get(models.Scenario, scenario_id)
    if row is None:
        raise HTTPException(status_code=404, detail="scenario not found")
    return {"id": row.id, "seed": row.seed, **row.payload}


@app.post("/api/scenarios", response_model=ScenarioResponse, status_code=201)
def create_scenario(item: ScenarioSave, db: Session = Depends(get_db)):
    payload = item.model_dump(exclude={"seed"})
    if db.scalar(select(models.Scenario).where(models.Scenario.name == item.name)):
        raise HTTPException(status_code=409, detail="scenario name already exists")
    row = models.Scenario(name=item.name, seed=item.seed, payload=payload)
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "seed": row.seed, **row.payload}


@app.post("/api/simulations", response_model=RunResponse)
def run(body: RunRequest, db: Session = Depends(get_db), persist: bool = True):
    scenario_row = None
    if body.scenario_id is not None:
        scenario_row = db.get(models.Scenario, body.scenario_id)
        if scenario_row is None:
            raise HTTPException(status_code=404, detail="scenario not found")
        payload = scenario_row.payload
        seed = body.seed if body.seed is not None else scenario_row.seed
    elif body.scenario is not None:
        payload = body.scenario.model_dump()
        seed = body.seed if body.seed is not None else 777
    else:
        raise HTTPException(status_code=400, detail="scenario_id or scenario is required")

    scenario = ScenarioInput.model_validate(payload)
    result = run_simulation(scenario.model_dump(), seed)

    run_row = None
    if persist:
        run_row = models.SimulationRun(
            scenario_id=scenario_row.id if scenario_row else None,
            seed=seed,
            result=result,
        )
        db.add(run_row)
        db.commit()
        db.refresh(run_row)
    return {
        "run_id": run_row.id if run_row else None,
        "scenario_id": scenario_row.id if scenario_row else None,
        **result,
    }


@app.get("/api/simulations/{run_id}", response_model=RunResponse)
def get_simulation(run_id: int, db: Session = Depends(get_db)):
    row = db.get(models.SimulationRun, run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="simulation run not found")
    return {
        "run_id": row.id,
        "scenario_id": row.scenario_id,
        **row.result,
    }
