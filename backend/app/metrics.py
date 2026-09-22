"""从事件流推导全部统计指标。

约束（对应需求）：本模块不执行任何随机数生成、也不引用仿真对象，
入参只有 engine 产出的事件列表。任何一张报表数字都必须能在此文件里
找到对应的事件类型作为数据来源；前端拿到同一批事件可做同样的复算与核对。
"""
from __future__ import annotations

from collections import defaultdict

from .sim.engine import OFFLINE, ON_CALL, WRAP

WAIT_BUCKETS = [0, 10, 20, 30, 45, 60, 90, 120, 180, 300, 600, float("inf")]


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    """最近秩百分位（确定性，无插值依赖）。"""
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, int(round(q * (len(sorted_vals) - 1)))))
    return round(sorted_vals[idx], 3)


def _histogram(values: list[float]) -> dict:
    counts = {f"{WAIT_BUCKETS[i]}-{WAIT_BUCKETS[i+1]}": 0 for i in range(len(WAIT_BUCKETS) - 1)}
    for v in values:
        for i in range(len(WAIT_BUCKETS) - 1):
            if WAIT_BUCKETS[i] <= v < WAIT_BUCKETS[i + 1]:
                counts[f"{WAIT_BUCKETS[i]}-{WAIT_BUCKETS[i+1]}"] += 1
                break
    return counts


def _extract_calls(events: list[dict]) -> dict[str, dict]:
    """用 ARRIVAL 建立来电档案，再用 ASSIGNED/ABANDONED/EXPIRED 补全结局。"""
    calls: dict[str, dict] = {}
    for ev in events:
        kind = ev["type"]
        cid = ev.get("call_id")
        if kind == "ARRIVAL":
            calls[cid] = {
                "call_id": cid,
                "type_key": ev["type_key"],
                "language": ev["language"],
                "skill": ev["skill"],
                "priority": ev["priority"],
                "arrival": ev["t"],
                "outcome": "WAITING",
                "wait_sec": None,
                "agent_id": None,
                "met_sla": None,
                "overflow_used": False,
                "sla_sec": None,
            }
        elif kind == "ASSIGNED":
            c = calls[cid]
            c.update(
                outcome="ANSWERED",
                wait_sec=ev["wait_sec"],
                agent_id=ev["agent_id"],
                met_sla=ev["met_sla"],
                overflow_used=bool(ev.get("overflow_rules_active")),
                sla_sec=ev["sla_sec"],
            )
        elif kind in ("ABANDONED", "EXPIRED"):
            c = calls[cid]
            c.update(outcome=kind, wait_sec=ev["waited_sec"],
                     overflow_used=bool(ev.get("overflow_rules_active")))
    return calls


def _service_level(calls: list[dict]) -> dict:
    answered = [c for c in calls if c["outcome"] == "ANSWERED"]
    if not answered:
        return {"answered": 0, "within_sla": 0, "sla_sec": None, "sl": None, "asa": None,
                "overflow_share": None}
    within = [c for c in answered if c["met_sla"]]
    sl = len(within) / len(answered)
    asa = sum(c["wait_sec"] for c in answered) / len(answered)
    overflow_share = sum(1 for c in answered if c["overflow_used"]) / len(answered)
    return {
        "answered": len(answered),
        "within_sla": len(within),
        "sla_sec": answered[0]["sla_sec"],
        "sl": round(sl, 4),
        "asa": round(asa, 3),
        "overflow_share": round(overflow_share, 4),
    }


def _queue_timeline(events: list[dict]) -> list[dict]:
    """以每次事件后的队列长度形成阶梯序列。"""
    timeline = []
    for ev in events:
        timeline.append({"t": ev["t"], "seq": ev["seq"], "type": ev["type"],
                         "waiting": len(ev.get("queue_after") or [])})
    return timeline


def _agent_timelines(events: list[dict], horizon: float) -> dict:
    """按事件重建坐席状态区间，计算排班在岗时长与占线（通话+整理）时长。"""
    spans = defaultdict(list)  # agent -> list of (start,end,status)
    open_span: dict[str, tuple[float, str]] = {}

    def status_of(agent_id: str, snap: list[dict]):
        for row in snap or []:
            if row["agent_id"] == agent_id:
                return row["status"]
        return None

    for ev in events:
        agents = {row["agent_id"]: row["status"] for row in ev.get("agents_after") or []}
        t = ev["t"]
        for aid, st in agents.items():
            prev = open_span.get(aid)
            if prev is None:
                open_span[aid] = (t, st)
            elif prev[1] != st:
                spans[aid].append((prev[0], t, prev[1]))
                open_span[aid] = (t, st)
    # 收尾：所有坐席最终都应为 OFFLINE（SHIFT_END / wrap 后下班）
    t_end = events[-1]["t"] if events else horizon
    for aid, (s, st) in list(open_span.items()):
        spans[aid].append((s, t_end, st))

    out = {}
    for aid, intervals in spans.items():
        staffed = busy = 0.0
        for s, e, st in intervals:
            dur = max(0.0, e - s)
            if st != OFFLINE:
                staffed += dur
            if st in (ON_CALL, WRAP):
                busy += dur
        out[aid] = {
            "staffed_sec": round(staffed, 3),
            "busy_sec": round(busy, 3),
            "occupancy": round(busy / staffed, 4) if staffed > 0 else None,
            "intervals": [
                {"start": round(s, 3), "end": round(e, 3), "status": st} for s, e, st in intervals
            ],
        }
    return out


def compute_metrics(events: list[dict], horizon: float) -> dict:
    calls = list(_extract_calls(events).values())
    total = len(calls)
    answered = [c for c in calls if c["outcome"] == "ANSWERED"]
    abandoned = [c for c in calls if c["outcome"] == "ABANDONED"]
    expired = [c for c in calls if c["outcome"] == "EXPIRED"]
    waits = sorted(c["wait_sec"] for c in answered if c["wait_sec"] is not None)
    all_waits = sorted(c["wait_sec"] for c in calls if c["wait_sec"] is not None)

    by_skill = defaultdict(list)
    by_language = defaultdict(list)
    by_type = defaultdict(list)
    for c in calls:
        by_skill[c["skill"]].append(c)
        by_language[c["language"]].append(c)
        by_type[c["type_key"]].append(c)

    def block(rows: list[dict]) -> dict:
        ans = [c for c in rows if c["outcome"] == "ANSWERED"]
        abd = [c for c in rows if c["outcome"] == "ABANDONED"]
        exp = [c for c in rows if c["outcome"] == "EXPIRED"]
        w = sorted(c["wait_sec"] for c in ans)
        base = {
            "total": len(rows),
            "answered": len(ans),
            "abandoned": len(abd),
            "expired": len(exp),
            "abandon_rate": round(len(abd) / len(rows), 4) if rows else None,
            "answer_rate": round(len(ans) / len(rows), 4) if rows else None,
        }
        base.update(_service_level(rows))
        base.update(
            {
                "wait_p50": _percentile(w, 0.5),
                "wait_p80": _percentile(w, 0.8),
                "wait_p90": _percentile(w, 0.9),
                "wait_p95": _percentile(w, 0.95),
                "wait_p99": _percentile(w, 0.99),
                "wait_max": round(w[-1], 3) if w else None,
                "wait_histogram": _histogram(w),
            }
        )
        return base

    qtl = _queue_timeline(events)
    agent_tl = _agent_timelines(events, horizon)
    staffed_sum = sum(v["staffed_sec"] for v in agent_tl.values())
    busy_sum = sum(v["busy_sec"] for v in agent_tl.values())

    metrics = {
        "horizon_sec": horizon,
        "total_calls": total,
        "answered": len(answered),
        "abandoned": len(abandoned),
        "expired": len(expired),
        "abandon_rate": round(len(abandoned) / total, 4) if total else None,
        "answer_rate": round(len(answered) / total, 4) if total else None,
        "overall": block(calls),
        "by_skill": {k: block(v) for k, v in sorted(by_skill.items())},
        "by_language": {k: block(v) for k, v in sorted(by_language.items())},
        "by_type": {k: block(v) for k, v in sorted(by_type.items())},
        "wait_distribution_all_answered": {
            "p50": _percentile(waits, 0.5),
            "p80": _percentile(waits, 0.8),
            "p90": _percentile(waits, 0.9),
            "p95": _percentile(waits, 0.95),
            "p99": _percentile(waits, 0.99),
            "max": round(waits[-1], 3) if waits else None,
            "histogram": _histogram(waits),
        },
        "wait_distribution_all_terminal": {
            "p50": _percentile(all_waits, 0.5),
            "p90": _percentile(all_waits, 0.9),
            "max": round(all_waits[-1], 3) if all_waits else None,
            "histogram": _histogram(all_waits),
        },
        "agents": agent_tl,
        "pooled_occupancy": round(busy_sum / staffed_sum, 4) if staffed_sum else None,
        "queue_timeline": qtl,
        "avg_queue_length": round(
            sum(p["waiting"] for p in qtl) / len(qtl), 4
        ) if qtl else 0.0,
    }
    return metrics
