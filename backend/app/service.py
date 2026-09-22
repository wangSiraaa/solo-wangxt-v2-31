"""仿真编排：配置解析 -> 引擎 -> 指标 -> 校验摘要。"""
from __future__ import annotations

import hashlib
import json

from .metrics import compute_metrics
from .schemas import ScenarioConfig
from .sim.engine import SimulationEngine


def canonical_hash(events: list[dict]) -> str:
    """事件流的规范化哈希。前端可用同一批事件重算，证明确实拿到的是后端事件。"""
    payload = json.dumps(events, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_simulation(raw_config: dict, seed: int, label: str = "") -> dict:
    config = ScenarioConfig.model_validate(raw_config)
    engine = SimulationEngine(config, seed, label=label)
    result = engine.run()
    events = result["events"]
    metrics = compute_metrics(events, config.horizon_sec)
    return {
        "events": events,
        "metrics": metrics,
        "planned_calls": result["plan_size"],
        "event_count": len(events),
        "event_hash": canonical_hash(events),
        "horizon_sec": config.horizon_sec,
        "seed": seed,
        "label": label,
    }
