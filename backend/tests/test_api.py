from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.database import Base
from app.models import Scenario, SimulationRun


def test_api_persists_scenario_and_reproduces_same_event_log():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[main.get_db] = override_db
    main.engine = engine
    main.SessionLocal = TestingSession
    main.seed_library()
    try:
        with TestClient(main.app) as client:
            scenarios = client.get("/api/scenarios").json()
            scenario = next(item for item in scenarios if item["name"] == "scarce_skill_priority_and_overflow")

            first = client.post("/api/simulations", json={"scenario_id": scenario["id"]}).json()
            second = client.post("/api/simulations", json={"scenario_id": scenario["id"], "seed": 42}).json()
            same_seed = client.post(
                "/api/simulations",
                json={"scenario_id": scenario["id"], "seed": first["seed"]},
            ).json()

            assert first["seed"] == 9901
            assert first["events"] == same_seed["events"]
            assert second["run_id"] != first["run_id"]

            with TestingSession() as db:
                assert db.get(Scenario, scenario["id"]).seed == 9901
                assert db.get(SimulationRun, first["run_id"]).result["events"] == first["events"]
    finally:
        main.app.dependency_overrides.clear()
