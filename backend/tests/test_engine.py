"""仿真引擎与指标的核心测试。

重点证明：
1. 同场景同种子事件流完全一致（确定性）；
2. 一个坐席任何时刻只接一通电话（状态机不变量）；
3. 放弃、溢出、跨班次延迟下班、整理时长都体现在事件里；
4. 指标确实可以脱离引擎、仅用事件流重算。
"""
from __future__ import annotations

from app.metrics import compute_metrics
from app.scenarios_data import (
    _cross_shift_config,
    _scarce_a_config,
    _scarce_b_config,
)
from app.service import canonical_hash, run_simulation
from app.sim.engine import (
    AVAILABLE,
    OFFLINE,
    ON_CALL,
    WRAP,
    ScenarioConfig,
    SimulationEngine,
)

# ---------- 小型手工场景，便于精确定位行为 ----------

MINI = {
    "name": "mini",
    "horizon_sec": 600,
    "call_types": [
        {
            "key": "g",
            "language": "zh",
            "skill": "general",
            "priority": 1,
            "arrival_rates": [[0, 600, 1.0]],  # 每秒 1 个 -> 高峰排队
            "talk_time": {"kind": "fixed", "mean": 100},
            "patience": {"kind": "fixed", "mean": 50},  # 50 秒必放弃
            "wrap_sec": 20,
            "sla_sec": 15,
        }
    ],
    "agents": [
        {"agent_id": "X1", "capabilities": [{"language": "zh", "skill": "general"}],
         "shift_start": 0, "shift_end": 300},
        {"agent_id": "X2", "capabilities": [{"language": "zh", "skill": "general"}],
         "shift_start": 100, "shift_end": 600},
    ],
    "overflow": {},
}


def test_determinism_same_seed():
    cfg = _cross_shift_config()
    h1 = run_simulation(cfg, 42)["event_hash"]
    h2 = run_simulation(cfg, 42)["event_hash"]
    assert h1 == h2


def test_different_seed_differs():
    cfg = _cross_shift_config()
    h1 = run_simulation(cfg, 42)["event_hash"]
    h2 = run_simulation(cfg, 123)["event_hash"]
    assert h1 != h2


def test_agent_never_double_booked():
    """回放事件，任意时刻每个坐席至多与一个 call_id 绑定。"""
    result = run_simulation(_cross_shift_config(), 42)
    busy: dict[str, str] = {}

    for ev in result["events"]:
        snap = ev["agents_after"]
        for row in snap:
            aid = row["agent_id"]
            if row["status"] in (ON_CALL, WRAP):
                # ON_CALL/WRAP 快照中的 current_call 由 ASSIGNED/CALL_END 事件可交叉验证
                pass
        if ev["type"] == "ASSIGNED":
            aid = ev["agent_id"]
            # 该事件的 before 快照里该坐席必须是 AVAILABLE（否则就是并发接第二通）
            before = next(r for r in ev["agents_before"] if r["agent_id"] == aid)
            assert before["status"] == AVAILABLE, f"{aid} 在非空闲状态接通了 {ev['call_id']}"
            assert ev["call_id"] not in busy.values()
            busy[aid] = ev["call_id"]
        elif ev["type"] == "CALL_END":
            aid = ev["agent_id"]
            assert busy.get(aid) == ev["call_id"]
        elif ev["type"] == "WRAP_END":
            aid = ev["agent_id"]
            busy.pop(aid, None)
        elif ev["type"] == "SHIFT_END" and ev["reason"] == "wrap_finished_then_logout":
            busy.pop(ev["agent_id"], None)


def test_abandon_fires_after_patience():
    result = run_simulation(MINI, 1)
    abandons = [e for e in result["events"] if e["type"] == "ABANDONED"]
    assert abandons, "高峰单坐席场景必须有人放弃"
    for e in abandons:
        assert e["reason"] == "patience_timeout"
        # 固定耐心 50 秒
        assert abs(e["waited_sec"] - 50.0) < 1e-6


def test_wrap_blocks_agent():
    """整理期间坐席状态为 WRAP，不允许被新来电选中。"""
    result = run_simulation(MINI, 1)
    wraps = [e for e in result["events"] if e["type"] == "WRAP_START"]
    assert wraps
    # 每个 WRAP_START 后，同一坐席在 WRAP_END 前不会出现 ASSIGNED
    in_wrap: set[str] = set()
    for ev in result["events"]:
        if ev["type"] == "WRAP_START":
            in_wrap.add(ev["agent_id"])
        elif ev["type"] in ("WRAP_END", "SHIFT_END"):
            in_wrap.discard(ev["agent_id"])
        elif ev["type"] == "ASSIGNED":
            assert ev["agent_id"] not in in_wrap


def test_shift_end_pending_then_deferred_logout():
    result = run_simulation(_cross_shift_config(), 42)
    pendings = [e for e in result["events"] if e["type"] == "SHIFT_END_PENDING"]
    deferred = [
        e for e in result["events"]
        if e["type"] == "SHIFT_END" and e["reason"] == "wrap_finished_then_logout"
    ]
    assert pendings, "1500 秒高峰交接应出现延迟下班"
    assert deferred, "延迟下班者最终应在整理结束后登出"
    for e in pendings:
        assert e["current_call"] is not None
    # 1500 整点交接窗口必须有早班坐席延迟下班
    assert any(e["t"] == 1500.0 for e in pendings)
    for e in deferred:
        assert e["t"] >= 900.0


def test_overflow_changes_routing_but_not_call_plan():
    a = run_simulation(_scarce_a_config(), 42)
    b = run_simulation(_scarce_b_config(), 42)
    # 关键：A/B 来电计划完全一致（同种子预生成），差异只来自路由事件
    arrivals_a = [(e["t"], e["call_id"]) for e in a["events"] if e["type"] == "ARRIVAL"]
    arrivals_b = [(e["t"], e["call_id"]) for e in b["events"] if e["type"] == "ARRIVAL"]
    assert arrivals_a == arrivals_b
    assert a["metrics"]["total_calls"] == b["metrics"]["total_calls"] == 72

    overflow_events = [e for e in b["events"] if e["type"] == "OVERFLOW"]
    assert overflow_events and all(e["reason"] == "wait_threshold_reached" for e in overflow_events)
    assert all(e["threshold_sec"] == 30 for e in overflow_events)
    # 有普通来电由 fraud 专家接通
    expert_general = [
        e for e in b["events"]
        if e["type"] == "ASSIGNED" and e["skill"] == "general" and e["agent_id"] in ("E1", "E2")
    ]
    assert expert_general
    # A 场景绝不允许专家接普通来电
    for e in a["events"]:
        if e["type"] == "ASSIGNED":
            if e["agent_id"] in ("E1", "E2"):
                assert e["skill"] == "fraud"
    # 挤占证据：B 的 fraud 服务水平不高于 A
    sl_a = a["metrics"]["by_skill"]["fraud"]["sl"]
    sl_b = b["metrics"]["by_skill"]["fraud"]["sl"]
    assert sl_b < sl_a


def test_metrics_derivable_from_events_alone():
    """把事件喂给一个全新进程式的纯函数，结果与 service 完全一致。"""
    result = run_simulation(_scarce_b_config(), 42)
    recomputed = compute_metrics(result["events"], result["horizon_sec"])
    assert recomputed == result["metrics"]
    # 哈希可复算
    assert canonical_hash(result["events"]) == result["event_hash"]


def test_outcome_partition_covers_all_calls():
    for cfg in (_cross_shift_config(), _scarce_a_config(), _scarce_b_config()):
        m = run_simulation(cfg, 42)["metrics"]
        assert (
            m["answered"] + m["abandoned"] + m["expired"] == m["total_calls"]
        )


def test_skill_service_level_structure():
    m = run_simulation(_cross_shift_config(), 42)["metrics"]
    assert set(m["by_skill"]) == {"billing", "tech"}
    for block in m["by_skill"].values():
        for key in ("sl", "asa", "abandon_rate", "wait_p50", "wait_p90", "wait_histogram"):
            assert key in block


def test_expired_only_at_horizon():
    result = run_simulation(MINI, 1)
    for e in result["events"]:
        if e["type"] == "EXPIRED":
            assert e["reason"] == "horizon_reached_still_waiting"
            assert e["t"] == 600.0
