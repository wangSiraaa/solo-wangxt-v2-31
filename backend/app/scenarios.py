from __future__ import annotations

CROSS_SHIFT_SCENARIO = {
    "name": "cross_shift_wrap",
    "duration": 300,
    "language_required": True,
    "routing": "priority_fifo",
    "default_service_time": 100,
    "default_patience": 100,
    "calls": [
        {
            "id": "early-1",
            "arrival_time": 10,
            "language": "zh",
            "skill": "billing",
            "priority": 1,
            "service_time": 80,
            "patience": 100,
        },
        {
            "id": "early-2",
            "arrival_time": 20,
            "language": "zh",
            "skill": "billing",
            "priority": 1,
            "service_time": 60,
            "patience": 100,
        },
        {
            "id": "late-1",
            "arrival_time": 90,
            "language": "zh",
            "skill": "billing",
            "priority": 1,
            "service_time": 50,
            "patience": 180,
        },
        {
            "id": "late-2",
            "arrival_time": 120,
            "language": "zh",
            "skill": "billing",
            "priority": 1,
            "service_time": 40,
            "patience": 180,
        },
    ],
    "agents": [
        {
            "id": "morning-billing",
            "name": "早班计费专员",
            "skills": ["billing"],
            "languages": ["zh"],
            "shift_start": 0,
            "shift_end": 100,
            "wrap_time": 20,
        },
        {
            "id": "evening-billing",
            "name": "晚班计费专员",
            "skills": ["billing"],
            "languages": ["zh"],
            "shift_start": 110,
            "shift_end": 300,
            "wrap_time": 20,
        },
    ],
    "overflow_rules": [],
}


SCARCE_SKILL_SCENARIO = {
    "name": "scarce_skill_priority_and_overflow",
    "duration": 300,
    "language_required": True,
    "routing": "priority_fifo",
    "default_service_time": 100,
    "default_patience": 100,
    "calls": [
        {
            "id": "tech-1",
            "arrival_time": 0,
            "language": "zh",
            "skill": "tech",
            "priority": 2,
            "service_time": 90,
            "patience": 100,
        },
        {
            "id": "bill-hi",
            "arrival_time": 10,
            "language": "zh",
            "skill": "billing",
            "priority": 2,
            "service_time": 80,
            "patience": 100,
        },
        {
            "id": "bill-wait",
            "arrival_time": 20,
            "language": "zh",
            "skill": "billing",
            "priority": 2,
            "service_time": 60,
            "patience": 40,
        },
        {
            "id": "support-overflow",
            "arrival_time": 30,
            "language": "zh",
            "skill": "support",
            "priority": 1,
            "service_time": 40,
            "patience": 200,
        },
    ],
    "agents": [
        {
            "id": "generalist",
            "name": "唯一通才（稀缺技能）",
            "skills": ["tech", "billing"],
            "languages": ["zh"],
            "shift_start": 0,
            "shift_end": 300,
            "wrap_time": 10,
        },
        {
            "id": "billing-specialist",
            "name": "计费专员（230 上班）",
            "skills": ["billing"],
            "languages": ["zh"],
            "shift_start": 230,
            "shift_end": 300,
            "wrap_time": 10,
        },
    ],
    "overflow_rules": [
        {"from_skill": "support", "to_skill": "billing", "wait_threshold": 40},
        {"from_skill": "support", "to_skill": "tech", "wait_threshold": 69},
    ],
}


SCENARIO_LIBRARY = {
    CROSS_SHIFT_SCENARIO["name"]: CROSS_SHIFT_SCENARIO,
    SCARCE_SKILL_SCENARIO["name"]: SCARCE_SKILL_SCENARIO,
}
