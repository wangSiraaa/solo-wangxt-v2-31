from __future__ import annotations

from app.scenarios import CROSS_SHIFT_SCENARIO, SCARCE_SKILL_SCENARIO
from app.simulation import compute_metrics, run_simulation


def dispatch_events(result):
    return [event for event in result["events"] if event["type"] == "DISPATCH"]


def test_same_scenario_and_seed_are_event_level_deterministic():
    first = run_simulation(CROSS_SHIFT_SCENARIO, 9901)
    second = run_simulation(CROSS_SHIFT_SCENARIO, 9901)
    other_seed = run_simulation(CROSS_SHIFT_SCENARIO, 42)

    assert first["events"] == second["events"]
    assert first["metrics"] == second["metrics"]
    # The deterministic fixture has no stochastic durations, but seed is retained
    # and the public result remains stable.
    assert first["seed"] == 9901
    assert other_seed["events"] == first["events"]


def test_agent_cannot_hold_two_calls_and_wrap_blocks_dispatch():
    result = run_simulation(CROSS_SHIFT_SCENARIO, 9901)
    busy: dict[str, tuple[float, float]] = {}

    for event in result["events"]:
        if event["type"] == "DISPATCH":
            agent_id = event["agent_id"]
            start = event["time"]
            end = start + event["data"]["service_time"]
            assert agent_id not in busy or start >= busy[agent_id][1]
            busy[agent_id] = (start, end)

    wait_reasons = [
        event
        for event in result["events"]
        if event["type"] == "DISPATCH" and event["data"]["wait_time"] > 0
    ]
    assert wait_reasons[0]["call_id"] == "early-2"
    assert wait_reasons[0]["data"]["wait_time"] == 90
    # Talk ends at 90s; the 20s post-call wrap makes this agent unavailable
    # until shift end at 100s.
    assert wait_reasons[0]["reason"]["code"] == "ELIGIBLE_AGENT_AVAILABLE"

    completed = [event for event in result["events"] if event["type"] == "CALL_COMPLETED"]
    assert len(completed) == 4
    assert all(event["agent_after"]["state"] == "wrap" for event in completed)

    by_agent = {item["agent_id"]: item for item in result["agent_timeline"]}
    assert by_agent["morning-billing"]["occupancy_pct"] == 0.9091
    assert by_agent["evening-billing"]["occupancy_pct"] == 1


def test_cross_shift_events_explain_queue_metrics():
    result = run_simulation(CROSS_SHIFT_SCENARIO, 9901)
    events = result["events"]
    queue_lengths = [(event["time"], event["type"], len(event["queue_after"])) for event in events]
    assert (10, "ARRIVAL", 1) in queue_lengths
    assert (20, "ARRIVAL", 1) in queue_lengths
    assert (90, "ARRIVAL", 2) in queue_lengths
    assert (110, "SHIFT_START", 2) in queue_lengths

    metrics = result["metrics"]
    assert metrics["overall"] == {
        "offered": 4,
        "answered": 4,
        "abandoned": 0,
        "answered_within_20s": 1,
        "service_level_20": 0.25,
        "abandonment_rate": 0,
        "average_wait": 82.5,
        "max_wait": 140,
        "routed": 4,
    }
    assert result["waiting_distribution"][4]["total"] == 1  # 60-90 seconds
    assert result["waiting_distribution"][5]["total"] == 1  # 90-120 seconds
    assert result["waiting_distribution"][6]["total"] == 1  # 120-180 seconds


def test_scarce_skill_priority_and_overflow_are_auditable():
    result = run_simulation(SCARCE_SKILL_SCENARIO, 9901)
    by_call = {}
    for event in result["events"]:
        if event["type"] == "DISPATCH":
            by_call[event["call_id"]] = event
    abandoned = [event for event in result["events"] if event["type"] == "ABANDONED"]

    # The scarce generalist is used for the tech-only call first. Later, the
    # higher-priority overflowing support call wins over the earlier billing call.
    assert by_call["tech-1"]["agent_id"] == "generalist"
    assert "bill-hi" not in by_call
    assert [event["call_id"] for event in abandoned] == ["bill-wait", "bill-hi"]
    assert all(event["reason"]["code"] == "PATIENCE_EXPIRED" for event in abandoned)

    overflow = [event for event in result["events"] if event["type"] == "OVERFLOW_ELIGIBLE"]
    assert [event["data"]["to_skill"] for event in overflow] == ["billing", "tech"]
    assert by_call["support-overflow"]["data"]["wait_time"] == 70
    assert by_call["support-overflow"]["data"]["matching_skill"] == "tech"
    assert by_call["support-overflow"]["data"]["overflow_used"] is True
    support_completed = next(
        event
        for event in result["events"]
        if event["type"] == "CALL_COMPLETED" and event["call_id"] == "support-overflow"
    )
    assert support_completed["time"] == 140
    assert support_completed["agent_after"]["state"] == "wrap"

    metrics = result["metrics"]["by_skill"]
    assert metrics["billing"]["abandonment_rate"] == 1
    assert metrics["billing"]["service_level_20"] == 0
    assert metrics["support"]["service_level_20"] == 0
    assert metrics["tech"]["service_level_20"] == 1


def test_metrics_are_recomputed_only_from_event_log():
    result = run_simulation(SCARCE_SKILL_SCENARIO, 9901)
    assert compute_metrics(result["events"]) == result["metrics"]
    first_dispatch = next(event for event in result["events"] if event["type"] == "DISPATCH")
    assert first_dispatch["queue_before"]
    assert "agents_snapshot" in first_dispatch
