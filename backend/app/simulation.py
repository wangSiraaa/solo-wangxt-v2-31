from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any

import simpy


WAIT_BUCKETS = [0, 10, 20, 30, 60, 90, 120, 180, 300, float("inf")]
SLA_SECONDS = 20


@dataclass
class Call:
    id: str
    arrival_time: float
    language: str
    skill: str
    priority: int
    service_time: float
    patience: float
    state: str = "scheduled"
    agent_id: str | None = None
    answer_time: float | None = None
    assigned_event: Any = None
    escalations: list[str] = field(default_factory=list)


@dataclass
class Agent:
    id: str
    name: str
    skills: set[str]
    languages: set[str]
    shift_start: float
    shift_end: float
    wrap_time: float
    state: str = "offline"
    pending_offline: bool = False


class SimulationEngine:
    """Deterministic SimPy discrete-event simulation.

    All statistics returned by the API are projected from ``self.events`` after
    the run; the event log is therefore the audit trail between routing causes
    and dashboard numbers.
    """

    def __init__(self, scenario: dict[str, Any], seed: int):
        self.scenario = scenario
        self.seed = seed
        self.env = simpy.Environment()
        self.rng = random.Random(seed)
        self.events: list[dict[str, Any]] = []
        self.queue: list[Call] = []
        self.agents = {
            spec["id"]: Agent(
                id=spec["id"],
                name=spec["name"],
                skills=set(spec["skills"]),
                languages=set(spec["languages"]),
                shift_start=float(spec["shift_start"]),
                shift_end=float(spec["shift_end"]),
                wrap_time=float(spec["wrap_time"]),
            )
            for spec in scenario["agents"]
        }
        self.calls = self._build_calls()
        self.overflow = self._build_overflow()
        self.end_time = float(scenario["duration"])

    def _build_calls(self) -> list[Call]:
        calls: list[Call] = []
        for spec in self.scenario["calls"]:
            service = spec.get("service_time")
            patience = spec.get("patience")
            calls.append(
                Call(
                    id=spec["id"],
                    arrival_time=float(spec["arrival_time"]),
                    language=spec["language"],
                    skill=spec["skill"],
                    priority=int(spec["priority"]),
                    service_time=float(
                        service
                        if service is not None
                        else self.scenario["default_service_time"]
                    ),
                    patience=float(
                        patience
                        if patience is not None
                        else self.scenario["default_patience"]
                    ),
                )
            )

        seq = 1
        for profile in self.scenario.get("arrival_profiles", []):
            t = float(profile["first_arrival"])
            for _ in range(int(profile["count"])):
                if t > self.scenario["duration"]:
                    break
                service = (
                    self.rng.expovariate(1 / float(profile["mean_service"]))
                    if self.scenario.get("enable_random_service")
                    else float(profile["mean_service"])
                )
                patience = (
                    self.rng.expovariate(1 / float(profile["mean_patience"]))
                    if self.scenario.get("enable_random_patience")
                    else float(profile["mean_patience"])
                )
                calls.append(
                    Call(
                        id=f"generated-{seq}",
                        arrival_time=round(t, 6),
                        language=profile["language"],
                        skill=profile["skill"],
                        priority=int(profile["priority"]),
                        service_time=round(max(service, 0), 6),
                        patience=round(max(patience, 0), 6),
                    )
                )
                gap = self.rng.expovariate(1 / float(profile["mean_interarrival"]))
                t += gap
                seq += 1
        return sorted(calls, key=lambda c: (c.arrival_time, c.id))

    def _build_overflow(self) -> dict[str, list[tuple[float, str]]]:
        result: dict[str, list[tuple[float, str]]] = {}
        for rule in self.scenario.get("overflow_rules", []):
            result.setdefault(rule["from_skill"], []).append(
                (float(rule["wait_threshold"]), rule["to_skill"])
            )
        for values in result.values():
            values.sort(key=lambda item: (item[0], item[1]))
        return result

    def run(self) -> dict[str, Any]:
        for agent in self.agents.values():
            self.env.process(self.agent_lifecycle(agent))
        for call in self.calls:
            if call.arrival_time <= self.scenario["duration"]:
                self.env.process(self.call_lifecycle(call))
        self.env.run()
        return {
            "seed": self.seed,
            "duration": max(self.end_time, self.env.now),
            "events": self.events,
            "metrics": compute_metrics(self.events),
            "waiting_distribution": waiting_distribution(self.events),
            "agent_timeline": agent_timeline(self.events),
        }

    def agent_lifecycle(self, agent: Agent):
        yield self.env.timeout(agent.shift_start)
        agent.state = "available"
        self.emit(
            "SHIFT_START",
            message=f"{agent.name} 上班并进入可用状态",
            reason={
                "code": "SHIFT_START",
                "detail": "到达坐席排班的上班时间，可以接听排队来电。",
                "factors": {"shift_start": agent.shift_start},
            },
            agent=agent,
            agent_before={"state": "offline", "pending_offline": False},
        )
        self.dispatch()

        yield self.env.timeout(agent.shift_end - agent.shift_start)
        before = self.snapshot_agent(agent)
        agent.pending_offline = True
        if agent.state == "available":
            agent.state = "offline"
        self.emit(
            "SHIFT_END",
            message=(
                f"{agent.name} 下班；当前通话允许完成并进入整理，之后离线"
                if agent.state != "offline"
                else f"{agent.name} 下班并离线"
            ),
            reason={
                "code": "SHIFT_END",
                "detail": "到达下班时间后不会再分配新电话；忙碌坐席只完成当前通话和整理。",
                "factors": {"shift_end": agent.shift_end, "state": agent.state},
            },
            agent=agent,
            agent_before=before,
        )

    def call_lifecycle(self, call: Call):
        yield self.env.timeout(call.arrival_time)
        call.state = "waiting"
        call.assigned_event = self.env.event()
        before_queue = self.snapshot_queue(include=())
        self.queue.append(call)
        self.emit(
            "ARRIVAL",
            message=(
                f"来电 {call.id} 进入队列：{call.language}/{call.skill}，"
                f"优先级 {call.priority}"
            ),
            reason={
                "code": "ARRIVAL",
                "detail": "新来电按语言、技能和优先级参与路由；优先级只决定排队顺序，不强占通话。",
                "factors": {
                    "language": call.language,
                    "skill": call.skill,
                    "priority": call.priority,
                    "patience": call.patience,
                },
            },
            call=call,
            queue_before=before_queue,
        )
        self.dispatch()

        for threshold, target_skill in self.overflow.get(call.skill, []):
            if threshold > call.patience or call.assigned_event.triggered:
                continue
            threshold_age = self.env.now - call.arrival_time
            remaining = threshold - threshold_age
            timeout = self.env.timeout(remaining)
            results = yield call.assigned_event | timeout
            if call.assigned_event in results and call.assigned_event.triggered:
                call.state = "active"
                yield from self.serve_call(call)
                return
            if call.state != "waiting":
                return
            if target_skill not in call.escalations:
                before = self.snapshot_queue()
                call.escalations.append(target_skill)
                self.emit(
                    "OVERFLOW_ELIGIBLE",
                    message=(
                        f"来电 {call.id} 等待 {threshold:.0f}s 后允许溢出到 {target_skill}"
                    ),
                    reason={
                        "code": "OVERFLOW_THRESHOLD_REACHED",
                        "detail": "溢出等待阈值已到，路由技能集合扩大；队列成员本身不变。",
                        "factors": {
                            "threshold": threshold,
                            "from_skill": call.skill,
                            "to_skill": target_skill,
                        },
                    },
                    call=call,
                    queue_before=before,
                    data={"threshold": threshold, "to_skill": target_skill},
                )
                self.dispatch()
            if call.assigned_event.triggered:
                call.state = "active"
                yield from self.serve_call(call)
                return

        if call.assigned_event.triggered:
            call.state = "active"
            yield from self.serve_call(call)
            return

        remaining = call.patience - (self.env.now - call.arrival_time)
        if remaining > 0:
            results = yield call.assigned_event | self.env.timeout(remaining)
            if call.assigned_event in results and call.assigned_event.triggered:
                call.state = "active"
                yield from self.serve_call(call)
                return
        if call.state == "waiting":
            self.abandon(call)

    def serve_call(self, call: Call):
        agent = self.agents[call.agent_id]
        call.answer_time = self.env.now
        yield self.env.timeout(call.service_time)

        before_agent = self.snapshot_agent(agent)
        call.state = "completed"
        agent.state = "wrap"
        self.emit(
            "CALL_COMPLETED",
            message=f"来电 {call.id} 通话结束，{agent.name} 进入 {agent.wrap_time:.0f}s 整理",
            reason={
                "code": "SERVICE_FINISHED",
                "detail": "通话时长结束；整理期间坐席仍被占用，不能接第二通电话。",
                "factors": {"service_time": call.service_time, "wrap_time": agent.wrap_time},
            },
            call=call,
            agent=agent,
            agent_before=before_agent,
            data={"talk_time": self.env.now - call.answer_time},
        )

        if agent.wrap_time:
            yield self.env.timeout(agent.wrap_time)
        before_agent = self.snapshot_agent(agent)
        agent.state = "offline" if agent.pending_offline else "available"
        self.emit(
            "WRAP_COMPLETED",
            message=(
                f"{agent.name} 整理完成并离线"
                if agent.state == "offline"
                else f"{agent.name} 整理完成，重新可用"
            ),
            reason={
                "code": "WRAP_FINISHED",
                "detail": "整理结束后坐席才重新进入可分配池；若已到下班时间则离线。",
                "factors": {"pending_offline": agent.pending_offline},
            },
            call=call,
            agent=agent,
            agent_before=before_agent,
        )
        if agent.state == "available":
            self.dispatch()

    def abandon(self, call: Call):
        before = self.snapshot_queue()
        call.state = "abandoned"
        if call in self.queue:
            self.queue.remove(call)
        wait = self.env.now - call.arrival_time
        self.emit(
            "ABANDONED",
            message=f"来电 {call.id} 等待 {wait:.0f}s 后放弃",
            reason={
                "code": "PATIENCE_EXPIRED",
                "detail": "等待时间达到客户耐心上限，且在此之前没有满足语言与技能的可用坐席。",
                "factors": {"wait_time": wait, "patience": call.patience},
            },
            call=call,
            queue_before=before,
            data={"wait_time": wait, "patience": call.patience},
        )

    def dispatch(self):
        if not self.queue:
            return
        occupied_agents: set[str] = set()
        def call_order(item: Call):
            wait = self.env.now - item.arrival_time
            if self.scenario["routing"] == "longest_waiting":
                return (-wait, item.priority, item.id)
            return (item.priority, item.arrival_time, item.id)

        ordered_calls = sorted(list(self.queue), key=call_order)
        for call in ordered_calls:
            if call.state != "waiting":
                continue
            allowed_skills = set([call.skill, *call.escalations])
            eligible = [
                agent
                for agent in self.agents.values()
                if agent.state == "available"
                and not agent.pending_offline
                and agent.id not in occupied_agents
                and not allowed_skills.isdisjoint(agent.skills)
                and (
                    not self.scenario.get("language_required", True)
                    or call.language in agent.languages
                )
            ]
            if not eligible:
                continue

            def score(agent: Agent):
                primary = 0 if call.skill in agent.skills else 1
                return (
                    primary,
                    len(agent.skills),
                    len(agent.languages),
                    agent.shift_start,
                    agent.id,
                )

            agent = min(eligible, key=score)
            before_queue = self.snapshot_queue()
            before_agent = self.snapshot_agent(agent)
            wait = self.env.now - call.arrival_time
            matching_skill = call.skill if call.skill in agent.skills else call.escalations[-1]
            agent.state = "busy"
            call.state = "active"
            call.agent_id = agent.id
            call.answer_time = self.env.now
            occupied_agents.add(agent.id)
            if call in self.queue:
                self.queue.remove(call)
            overflow_used = matching_skill != call.skill
            self.emit(
                "DISPATCH",
                message=(
                    f"来电 {call.id} 等待 {wait:.0f}s 后分配给 {agent.name}"
                    + (f"，使用溢出技能 {matching_skill}" if overflow_used else "")
                ),
                reason={
                    "code": "ELIGIBLE_AGENT_AVAILABLE",
                    "detail": "存在满足语言和技能集合的可用坐席；优先原技能，再选择技能更少的坐席以保留稀缺通才。",
                    "factors": {
                        "wait_time": wait,
                        "priority": call.priority,
                        "allowed_skills": sorted(allowed_skills),
                        "selected_skill": matching_skill,
                        "overflow_used": overflow_used,
                        "eligible_agent_ids": [a.id for a in eligible],
                    },
                },
                call=call,
                agent=agent,
                queue_before=before_queue,
                agent_before=before_agent,
                data={
                    "wait_time": wait,
                    "service_time": call.service_time,
                    "matching_skill": matching_skill,
                    "overflow_used": overflow_used,
                    "eligible_agent_ids": [a.id for a in eligible],
                },
            )
            call.assigned_event.succeed()

    def snapshot_queue(self, include: Any | None = None) -> list[dict[str, Any]]:
        calls = list(self.queue)
        if include is not None:
            calls = [c for c in calls if c in include]
        return [
            {
                "call_id": c.id,
                "language": c.language,
                "skill": c.skill,
                "priority": c.priority,
                "waiting_for": self.env.now - c.arrival_time,
                "escalations": list(c.escalations),
            }
            for c in sorted(calls, key=lambda item: (item.priority, item.arrival_time, item.id))
        ]

    def snapshot_agent(self, agent: Agent) -> dict[str, Any]:
        return {
            "agent_id": agent.id,
            "name": agent.name,
            "state": agent.state,
            "pending_offline": agent.pending_offline,
            "skills": sorted(agent.skills),
            "languages": sorted(agent.languages),
            "shift_start": agent.shift_start,
            "shift_end": agent.shift_end,
        }

    def emit(
        self,
        event_type: str,
        message: str,
        reason: dict[str, Any],
        call: Call | None = None,
        agent: Agent | None = None,
        queue_before: list[dict[str, Any]] | None = None,
        agent_before: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ):
        queue_after = self.snapshot_queue()
        event = {
            "id": len(self.events) + 1,
            "time": round(self.env.now, 6),
            "type": event_type,
            "message": message,
            "reason": reason,
            "call_id": call.id if call else None,
            "agent_id": agent.id if agent else None,
            "call": self.snapshot_call(call) if call else None,
            "queue_before": queue_before if queue_before is not None else queue_after,
            "queue_after": queue_after,
            "agent_before": agent_before,
            "agent_after": self.snapshot_agent(agent) if agent else None,
            "agents_snapshot": [self.snapshot_agent(a) for a in self.agents.values()],
            "data": data or {},
        }
        self.events.append(event)

    def snapshot_call(self, call: Call) -> dict[str, Any]:
        return {
            "call_id": call.id,
            "arrival_time": call.arrival_time,
            "language": call.language,
            "skill": call.skill,
            "priority": call.priority,
            "state": call.state,
            "agent_id": call.agent_id,
            "service_time": call.service_time,
            "patience": call.patience,
            "wait_time": max(0, self.env.now - call.arrival_time)
            if call.state in {"waiting", "active", "completed", "abandoned"}
            else 0,
            "escalations": list(call.escalations),
        }


def run_simulation(scenario: dict[str, Any], seed: int) -> dict[str, Any]:
    return SimulationEngine(scenario, seed).run()


def _empty_stat(offered: int = 0) -> dict[str, Any]:
    return {
        "offered": offered,
        "answered": 0,
        "abandoned": 0,
        "answered_within_20s": 0,
        "service_level_20": None,
        "abandonment_rate": None,
        "average_wait": None,
        "max_wait": 0,
    }


def compute_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    skills: dict[str, dict[str, Any]] = {}
    skill_waits: dict[str, list[float]] = {}
    overall = _empty_stat()
    overall_waits: list[float] = []

    def ensure(skill: str) -> dict[str, Any]:
        return skills.setdefault(skill, _empty_stat())

    for event in events:
        call = event.get("call") or {}
        skill = call.get("skill")
        if event["type"] == "ARRIVAL":
            overall["offered"] += 1
            ensure(skill)["offered"] += 1
        elif event["type"] in {"DISPATCH", "ABANDONED"}:
            wait = float(event["data"]["wait_time"])
            overall_waits.append(wait)
            skill_waits.setdefault(skill, []).append(wait)
            stat = ensure(skill)
            stat["max_wait"] = max(stat["max_wait"], wait)
            overall["max_wait"] = max(overall["max_wait"], wait)
            if event["type"] == "DISPATCH":
                overall["answered"] += 1
                stat["answered"] += 1
                if wait <= SLA_SECONDS + 1e-9:
                    overall["answered_within_20s"] += 1
                    stat["answered_within_20s"] += 1
            else:
                overall["abandoned"] += 1
                stat["abandoned"] += 1

    def finish(stat: dict[str, Any], waits: list[float]) -> dict[str, Any]:
        offered = stat["offered"]
        stat["routed"] = stat["answered"] + stat["abandoned"]
        stat["service_level_20"] = (
            round(stat["answered_within_20s"] / offered, 4) if offered else None
        )
        stat["abandonment_rate"] = (
            round(stat["abandoned"] / offered, 4) if offered else None
        )
        stat["average_wait"] = round(sum(waits) / len(waits), 3) if waits else None
        stat["max_wait"] = round(stat["max_wait"], 3)
        return stat

    for skill, stat in skills.items():
        finish(stat, skill_waits.get(skill, []))
    return {"overall": finish(overall, overall_waits), "by_skill": skills}


def waiting_distribution(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for lower, upper in zip(WAIT_BUCKETS, WAIT_BUCKETS[1:]):
        rows.append(
            {
                "lower": None if lower == float("inf") else lower,
                "upper": None if upper == float("inf") else upper,
                "answered": 0,
                "abandoned": 0,
                "total": 0,
            }
        )
    for event in events:
        if event["type"] not in {"DISPATCH", "ABANDONED"}:
            continue
        wait = float(event["data"]["wait_time"])
        index = next(i for i, upper in enumerate(WAIT_BUCKETS[1:]) if wait <= upper + 1e-9)
        key = "answered" if event["type"] == "DISPATCH" else "abandoned"
        rows[index][key] += 1
        rows[index]["total"] += 1
    return rows


def agent_timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timelines: dict[str, dict[str, Any]] = {}

    def ensure(event: dict, agent: dict):
        item = timelines.setdefault(
            agent["agent_id"],
            {
                "agent_id": agent["agent_id"],
                "name": agent["name"],
                "segments": [],
                "talk_seconds": 0,
                "wrap_seconds": 0,
                "logged_in_seconds": 0,
                "occupied_seconds": 0,
                "occupancy_pct": None,
            },
        )
        return item

    for event in events:
        agent = event.get("agent_after")
        if not agent:
            continue
        item = ensure(event, agent)
        start = item.get("segment_start")
        state = item.get("segment_state")
        if start is not None and state:
            duration = event["time"] - start
            segment = {"start": start, "end": event["time"], "state": state, "duration": duration}
            item["segments"].append(segment)
            if state == "busy":
                item["talk_seconds"] += duration
            elif state == "wrap":
                item["wrap_seconds"] += duration
        if agent["state"] == "offline" and item.get("segment_state") in {"available", "busy", "wrap"}:
            item["segment_start"] = None
            item["segment_state"] = None
        else:
            item["segment_start"] = event["time"]
            item["segment_state"] = agent["state"]

    login_start: dict[str, float] = {}
    logout_end: dict[str, float] = {}
    for event in events:
        agent = event.get("agent_after")
        if not agent:
            continue
        agent_id = agent["agent_id"]
        if event["type"] == "SHIFT_START":
            login_start[agent_id] = event["time"]
        logout_end[agent_id] = max(logout_end.get(agent_id, event["time"]), event["time"])

    for item in timelines.values():
        item["segments"] = [segment for segment in item["segments"] if segment["duration"] > 0]
        item["logged_in_seconds"] = (
            logout_end.get(item["agent_id"], 0) - login_start.get(item["agent_id"], 0)
        )
        handled = item["talk_seconds"] + item["wrap_seconds"]
        item["occupancy_pct"] = (
            round(handled / item["logged_in_seconds"], 4)
            if item["logged_in_seconds"] > 0
            else None
        )
        item.pop("occupied_seconds", None)
        item.pop("segment_start", None)
        item.pop("segment_state", None)
    return [timelines[key] for key in sorted(timelines)]
