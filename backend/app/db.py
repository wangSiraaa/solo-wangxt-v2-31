"""数据库：PostgreSQL 优先（DATABASE_URL 指向 postgresql://），
未配置时回退到本地 SQLite，便于离线开发与测试。
事件流以 JSON / JSONB 整列保存。"""
from __future__ import annotations

import os
import uuid

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./sim.db")

_IS_PG = DATABASE_URL.startswith("postgresql")
_JSON = JSONB if _IS_PG else Text  # SQLite 上用 Text 存 JSON 字符串


class Base(DeclarativeBase):
    pass


class ScenarioRow(Base):
    __tablename__ = "scenarios"

    id = Column(String(36), primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    config_json = Column(_JSON, nullable=False)
    default_seed = Column(Integer, default=42)
    created_at = Column(DateTime, server_default=func.now())


class RunRow(Base):
    __tablename__ = "runs"

    id = Column(String(36), primary_key=True)
    scenario_id = Column(String(36), nullable=True, index=True)
    seed = Column(Integer, nullable=False)
    label = Column(String(200), default="")
    metrics_json = Column(_JSON, nullable=False)
    events_json = Column(_JSON, nullable=False)
    event_hash = Column(String(64), nullable=False)
    event_count = Column(Integer, nullable=False)
    planned_calls = Column(Integer, nullable=False)
    horizon_sec = Column(Float, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


engine = create_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if not _IS_PG else {},
    pool_pre_ping=_IS_PG,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return SessionLocal()


def new_id() -> str:
    return str(uuid.uuid4())
