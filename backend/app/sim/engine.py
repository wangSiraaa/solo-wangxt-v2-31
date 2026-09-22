"""SimPy 离散事件仿真引擎。

设计要点：
- 一切统计数字都由本引擎产出的事件流推导（见 metrics.py），前端只负责回放。
- 同场景 + 同种子 => 同事件流。所有随机量（到达间隔、耐心、通话时长）
  在仿真开始前由同一个 `random.Random(seed)` 预生成，与路由决策完全无关，
  因此 A/B 两版溢出规则在同种子下使用完全相同的来电计划。
- 坐席状态机 OFFLINE/AVAILABLE/ON_CALL/WRAP 由普通布尔状态 + 同步派发器维护，
  派发器只在 AVAILABLE 坐席间选择，结构上保证一个坐席不可能同时接两通电话。
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

import simpy

from ..schemas import AgentSpec, CallType, Capability, OverflowRule, ScenarioConfig

# 坐席状态
OFFLINE, AVAILABLE, ON_CALL, WRAP = "OFFLINE", "AVAILABLE", "ON_CALL", "WRAP"


@dataclass
class PlannedCall:
    call_id: str
    type_key: str
    arrival: float
    patience: float
    talk: float


@dataclass
class Call:
    plan: PlannedCall
    call_type: CallType
    rules: list[OverflowRule]
    active_overflow: set[int] = field(default_factory=set)  # 已生效的规则下标
    assigned: simpy.Event | None = None
    outcome: str = "WAITING"  # WAITING / ANSWERED / ABANDONED / EXPIRED
    answer_time: float | None = None
    agent_id: str | None = None
    wait_sec: float | None = None


@dataclass
class Agent:
    spec: AgentSpec
    status: str = OFFLINE
    current_call: str | None = None
    pending_logout: bool = False  # 通话/整理中到点，结束后下班

    def cap_keys(self) -> set[tuple[str, str]]:
        return {(c.language, c.skill) for c in self.spec.capabilities}


def generate_call_plan(config: ScenarioConfig, seed: int) -> list[PlannedCall]:
    """按分段泊松过程预生成全部来电及其耐心/通话时长。"""
    rng = random.Random(seed)
    arrivals: list[tuple[float, str]] = []
    for ct in config.call_types:
        for start, end, rate in ct.arrival_rates:
            start = max(0.0, start)
            end = min(float(config.horizon_sec), end)
            if end <= start or rate <= 0:
                continue
            n = _poisson(rng, rate * (end - start))
            for _ in range(n):
                t = rng.uniform(start, end)
                if t < config.horizon_sec:
                    arrivals.append((t, ct.key))
    arrivals.sort(key=lambda x: (x[0], x[1]))

    type_map = {ct.key: ct for ct in config.call_types}
    plan: list[PlannedCall] = []
    for i, (t, key) in enumerate(arrivals, start=1):
        ct = type_map[key]
        plan.append(
            PlannedCall(
                call_id=f"C{i:04d}",
                type_key=key,
                arrival=t,
                patience=max(0.0, ct.patience.sample(rng)),
                talk=max(1.0, ct.talk_time.sample(rng)),
            )
        )
    return plan


def _poisson(rng: random.Random, lam: float) -> int:
    """Knuth 泊松采样（random.Random 没有 poisson 方法时的后备）。"""
    import math

    lk = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= lk:
            return k - 1


class SimulationEngine:
    def __init__(self, config: ScenarioConfig, seed: int, label: str = ""):
        self.config = config
        self.seed = seed
        self.label = label
        self.env = simpy.Environment()
        self.plan = generate_call_plan(config, seed)
        self.agents = {spec.agent_id: Agent(spec=spec) for spec in config.agents}
        self.waiting: dict[str, Call] = {}
        self.calls: dict[str, Call] = {}
        self.events: list[dict] = []
        self._seq = 0

    # ---------------- 事件与快照 ----------------

    def _queue_snapshot(self) -> list[dict]:
        rows = []
        t = self.env.now
        for call in self._ordered_waiting():
            rows.append(
                {
                    "call_id": call.plan.call_id,
                    "type_key": call.call_type.key,
                    "language": call.call_type.language,
                    "skill": call.call_type.skill,
                    "priority": call.call_type.priority,
                    "enqueue_time": round(call.plan.arrival, 4),
                    "waited": round(t - call.plan.arrival, 4),
                    "overflow_rules_active": sorted(call.active_overflow),
                }
            )
        return rows

    def _agent_snapshot(self) -> list[dict]:
        return [
            {
                "agent_id": a.spec.agent_id,
                "name": a.spec.display_name or a.spec.agent_id,
                "status": a.status,
                "current_call": a.current_call,
                "shift_start": a.spec.shift_start,
                "shift_end": a.spec.shift_end,
                "pending_logout": a.pending_logout,
            }
            for a in self.agents.values()
        ]

    def _record(self, kind: str, before_q, before_a, after_q, after_a, reason: str = "", **kw) -> dict:
        ev = {
            "seq": self._seq,
            "t": round(self.env.now, 4),
            "type": kind,
            "reason": reason,
            **kw,
            "queue_before": before_q,
            "queue_after": after_q,
            "agents_before": before_a,
            "agents_after": after_a,
        }
        self._seq += 1
        self.events.append(ev)
        return ev

    def _ordered_waiting(self) -> list[Call]:
        return sorted(
            self.waiting.values(),
            key=lambda c: (-c.call_type.priority, c.plan.arrival, c.plan.call_id),
        )

    # ---------------- 匹配与派发 ----------------

    @staticmethod
    def _cap_covers(cap: Capability, language: str, skill: str) -> bool:
        return (cap.language in (language, "*")) and (cap.skill in (skill, "*"))

    def _eligible_capabilities(self, call: Call) -> list[Capability]:
        """基础能力 + 已到阈值的溢出能力。"""
        caps = [Capability(language=call.call_type.language, skill=call.call_type.skill, level=0)]
        for idx in call.active_overflow:
            caps.extend(call.rules[idx].add_capabilities)
        return caps

    def _agent_matches(self, agent: Agent, call: Call) -> bool:
        if agent.status != AVAILABLE:
            return False
        capset = agent.cap_keys()
        for cap in self._eligible_capabilities(call):
            if (cap.language, cap.skill) in capset:
                return True
            # 坐席侧通配能力（如 ('*','tech')）
            if any(
                cl in (cap.language, "*") and cs in (cap.skill, "*")
                for (cl, cs) in capset
            ):
                return True
        return False

    def _best_agent(self, candidates: list[Agent], call: Call) -> Agent:
        """最佳适配：优先最「专才」的坐席（能力数最少），保护通才不被挤占；
        再按该技能等级、坐席编号决胜。"""

        def level_of(a: Agent) -> int:
            best = -1
            for c in a.spec.capabilities:
                if self._cap_covers(c, call.call_type.language, call.call_type.skill):
                    best = max(best, c.level)
            return best

        return min(
            candidates,
            key=lambda a: (len(a.spec.capabilities), -level_of(a), a.spec.agent_id),
        )

    def dispatch(self, reason: str) -> None:
        """同步派发循环：把等待队列尽量塞给当前 AVAILABLE 坐席。

        只挑选 status==AVAILABLE 的坐席，且每次赋值后坐席立刻变为 ON_CALL，
        因此同一坐席在下一轮循环里绝不可能再被选中（不可并发接两通）。
        """
        progressed = True
        while progressed:
            progressed = False
            for call in self._ordered_waiting():
                candidates = [a for a in self.agents.values() if self._agent_matches(a, call)]
                if not candidates:
                    continue
                agent = self._best_agent(candidates, call)
                self._assign(call, agent, reason)
                progressed = True
                break  # 队列已变，重新按优先级排序扫描

    def _assign(self, call: Call, agent: Agent, reason: str) -> None:
        before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
        wait = self.env.now - call.plan.arrival
        call.outcome = "ANSWERED"
        call.answer_time = self.env.now
        call.agent_id = agent.spec.agent_id
        call.wait_sec = wait
        self.waiting.pop(call.plan.call_id, None)
        agent.status = ON_CALL
        agent.current_call = call.plan.call_id
        overflow_used = sorted(call.active_overflow)
        after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
        self._record(
            "ASSIGNED",
            before_q,
            before_a,
            after_q,
            after_a,
            reason=reason,
            call_id=call.plan.call_id,
            type_key=call.call_type.key,
            language=call.call_type.language,
            skill=call.call_type.skill,
            priority=call.call_type.priority,
            agent_id=agent.spec.agent_id,
            wait_sec=round(wait, 4),
            overflow_rules_active=overflow_used,
            sla_sec=call.call_type.sla_sec,
            met_sla=wait <= call.call_type.sla_sec,
        )
        call.assigned.succeed()

    # ---------------- SimPy 进程 ----------------

    def call_process(self, env: simpy.Environment, call: Call):
        # 0) 等待到计划到达时刻
        yield env.timeout(call.plan.arrival)
        # 1) 到达并入队
        before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
        self.waiting[call.plan.call_id] = call
        after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
        self._record(
            "ARRIVAL",
            before_q,
            before_a,
            after_q,
            after_a,
            reason="new_call_queued",
            call_id=call.plan.call_id,
            type_key=call.call_type.key,
            language=call.call_type.language,
            skill=call.call_type.skill,
            priority=call.call_type.priority,
            patience_sec=round(call.plan.patience, 4),
            talk_sec=round(call.plan.talk, 4),
        )
        call.assigned = env.event()
        abandon_proc = env.process(self.abandon_timer(call))
        overflow_procs = [env.process(self.overflow_timer(call, idx)) for idx in range(len(call.rules))]

        dispatch_reason = "arrival"
        self.dispatch(dispatch_reason)
        yield call.assigned  # 等待派发器接通

        # 已接通：取消所有等待计时器
        for p in [abandon_proc, *overflow_procs]:
            if not p.triggered:
                p.interrupt()

        # 2) 通话
        yield env.timeout(call.plan.talk)
        before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
        after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
        self._record(
            "CALL_END",
            before_q,
            before_a,
            after_q,
            after_a,
            reason="talk_finished",
            call_id=call.plan.call_id,
            agent_id=call.agent_id,
            talk_sec=round(call.plan.talk, 4),
        )

        # 3) 整理
        agent = self.agents[call.agent_id]
        wrap = agent.spec.wrap_override
        wrap = call.call_type.wrap_sec if wrap is None else wrap
        if wrap > 0:
            before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
            agent.status = WRAP
            after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
            self._record(
                "WRAP_START",
                before_q,
                before_a,
                after_q,
                after_a,
                reason="after_call_work",
                call_id=call.plan.call_id,
                agent_id=agent.spec.agent_id,
                wrap_sec=wrap,
            )
            yield env.timeout(wrap)
        else:
            agent.status = WRAP  # 瞬时经过，释放逻辑统一在下方处理

        before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
        agent.current_call = None
        if agent.pending_logout:
            agent.status = OFFLINE
            agent.pending_logout = False
            after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
            self._record(
                "SHIFT_END",
                before_q,
                before_a,
                after_q,
                after_a,
                reason="wrap_finished_then_logout",
                agent_id=agent.spec.agent_id,
            )
            return
        agent.status = AVAILABLE
        after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
        self._record(
            "WRAP_END",
            before_q,
            before_a,
            after_q,
            after_a,
            reason="agent_available_again" if wrap > 0 else "instant_release_no_wrap",
            agent_id=agent.spec.agent_id,
        )
        self.dispatch("wrap_release")

    def abandon_timer(self, call: Call):
        try:
            yield self.env.timeout(call.plan.patience)
        except simpy.Interrupt:
            return
        if call.plan.call_id not in self.waiting:
            return
        before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
        self.waiting.pop(call.plan.call_id, None)
        call.outcome = "ABANDONED"
        after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
        self._record(
            "ABANDONED",
            before_q,
            before_a,
            after_q,
            after_a,
            reason="patience_timeout",
            call_id=call.plan.call_id,
            type_key=call.call_type.key,
            language=call.call_type.language,
            skill=call.call_type.skill,
            priority=call.call_type.priority,
            waited_sec=round(self.env.now - call.plan.arrival, 4),
            patience_sec=round(call.plan.patience, 4),
            overflow_rules_active=sorted(call.active_overflow),
        )

    def overflow_timer(self, call: Call, rule_idx: int):
        threshold = call.rules[rule_idx].threshold_sec
        try:
            yield self.env.timeout(threshold)
        except simpy.Interrupt:
            return
        if call.plan.call_id not in self.waiting:
            return
        rule = call.rules[rule_idx]
        before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
        call.active_overflow.add(rule_idx)
        after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
        self._record(
            "OVERFLOW",
            before_q,
            before_a,
            after_q,
            after_a,
            reason="wait_threshold_reached",
            call_id=call.plan.call_id,
            type_key=call.call_type.key,
            language=call.call_type.language,
            skill=call.call_type.skill,
            priority=call.call_type.priority,
            waited_sec=round(self.env.now - call.plan.arrival, 4),
            rule_index=rule_idx,
            threshold_sec=threshold,
            added_capabilities=[c.model_dump() for c in rule.add_capabilities],
            note=rule.note,
        )
        self.dispatch(f"overflow_rule_{rule_idx}")

    def shift_process(self, env: simpy.Environment, agent: Agent):
        yield env.timeout(agent.spec.shift_start)
        before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
        agent.status = AVAILABLE
        after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
        self._record(
            "SHIFT_START",
            before_q,
            before_a,
            after_q,
            after_a,
            reason="scheduled_login",
            agent_id=agent.spec.agent_id,
        )
        self.dispatch("shift_login")

        yield env.timeout(agent.spec.shift_end - agent.spec.shift_start)
        if agent.status == AVAILABLE:
            before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
            agent.status = OFFLINE
            after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
            self._record(
                "SHIFT_END",
                before_q,
                before_a,
                after_q,
                after_a,
                reason="scheduled_logout",
                agent_id=agent.spec.agent_id,
            )
        else:
            # 通话/整理中：挂起下班，等 WRAP_END 处真正下班
            agent.pending_logout = True
            before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
            after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
            self._record(
                "SHIFT_END_PENDING",
                before_q,
                before_a,
                after_q,
                after_a,
                reason="busy_at_shift_end_logout_deferred",
                agent_id=agent.spec.agent_id,
                current_call=agent.current_call,
            )

    def horizon_process(self, env: simpy.Environment):
        yield env.timeout(self.config.horizon_sec)
        # 截止仍在排队的来电标记为 EXPIRED（既不算接通也不算放弃）
        for call in list(self.waiting.values()):
            before_q, before_a = self._queue_snapshot(), self._agent_snapshot()
            self.waiting.pop(call.plan.call_id, None)
            call.outcome = "EXPIRED"
            after_q, after_a = self._queue_snapshot(), self._agent_snapshot()
            self._record(
                "EXPIRED",
                before_q,
                before_a,
                after_q,
                after_a,
                reason="horizon_reached_still_waiting",
                call_id=call.plan.call_id,
                type_key=call.call_type.key,
                language=call.call_type.language,
                skill=call.call_type.skill,
                waited_sec=round(self.env.now - call.plan.arrival, 4),
            )

    def run(self) -> dict:
        env = self.env
        type_map = {ct.key: ct for ct in self.config.call_types}
        rules_map = {k: sorted(v, key=lambda r: r.threshold_sec) for k, v in self.config.overflow.items()}

        self._record("SIM_START", [], [], self._queue_snapshot(), self._agent_snapshot(), reason="init",
                     horizon_sec=self.config.horizon_sec, seed=self.seed, label=self.label,
                     planned_calls=len(self.plan))

        for pc in self.plan:
            env.process(self.call_process(env, self._make_call(pc, type_map, rules_map)))
        for agent in self.agents.values():
            env.process(self.shift_process(env, agent))
        env.process(self.horizon_process(env))

        env.run()  # horizon 之后排队者已过期，剩余只有有限的通话/整理，自然收敛

        self._record(
            "SIM_END",
            self._queue_snapshot(),
            self._agent_snapshot(),
            self._queue_snapshot(),
            self._agent_snapshot(),
            reason="all_calls_resolved",
            t_final=round(env.now, 4),
        )
        return {"events": self.events, "plan_size": len(self.plan)}

    def _make_call(self, pc: PlannedCall, type_map: dict, rules_map: dict) -> Call:
        call = Call(plan=pc, call_type=type_map[pc.type_key], rules=rules_map.get(pc.type_key, []))
        # 到达进程需要在 call_process 里入队；call_id 注册提前以便计时器引用
        self.calls[pc.call_id] = call
        return call
