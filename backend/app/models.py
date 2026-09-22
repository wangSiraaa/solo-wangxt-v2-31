from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from .database import Base


class Scenario(Base):
    __tablename__ = "scenarios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False, unique=True)
    seed = Column(Integer, nullable=False, default=777)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    runs = relationship("SimulationRun", back_populates="scenario", cascade="all, delete-orphan")


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id = Column(Integer, primary_key=True, index=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=True, index=True)
    seed = Column(Integer, nullable=False)
    result = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    scenario = relationship("Scenario", back_populates="runs")
