"""内置演示场景（固定 ID 与种子，保证可复跑、可 A/B）。

场景一 cross_shift：晚高峰与班次交接重叠，展示通话中到点下班（延迟登出）、
                 跨班次等待、放弃与技能级服务水平。
场景二 scarce_A / scarce_B：完全相同的来电计划与种子，仅溢出策略不同——
                 A 不溢出（保护稀缺反欺诈专家），B 普通来电等 30 秒后溢出给
                 专家坐席，对比稀缺技能被挤占后的服务水平差异。
"""
from __future__ import annotations

SCENARIO_CROSS_SHIFT = "11111111-1111-4111-8111-111111111111"
SCENARIO_SCARCE_A = "22222222-2222-4222-a222-222222222222"
SCENARIO_SCARCE_B = "22222222-2222-4222-b222-222222222222"

SEED = 42


def _cross_shift_config() -> dict:
    return {
        "name": "跨班次交接（晚高峰 15:00 交接班）",
        "description": (
            "中文账单/技术两条线，早班 0–1500 秒、晚班 1500–2700、夜班 2400–3600。"
            "账单来电在 900–1800 秒高峰；1500 秒整两名早班坐席到点，"
            "其中仍在通话/整理者延迟下班。观察交接窗口的排队、放弃与 SLA。"
        ),
        "horizon_sec": 3600,
        "default_seed": SEED,
        "call_types": [
            {
                "key": "billing_zh",
                "language": "zh",
                "skill": "billing",
                "priority": 1,
                "arrival_rates": [
                    [0, 900, 0.012],
                    [900, 1800, 0.045],
                    [1800, 3600, 0.016],
                ],
                "talk_time": {"kind": "exponential", "mean": 130},
                "patience": {"kind": "triangular", "low": 45, "mode": 120, "high": 300},
                "wrap_sec": 30,
                "sla_sec": 20,
            },
            {
                "key": "tech_zh",
                "language": "zh",
                "skill": "tech",
                "priority": 1,
                "arrival_rates": [[0, 3600, 0.012]],
                "talk_time": {"kind": "exponential", "mean": 220},
                "patience": {"kind": "triangular", "low": 60, "mode": 180, "high": 420},
                "wrap_sec": 45,
                "sla_sec": 30,
            },
            {
                "key": "billing_en",
                "language": "en",
                "skill": "billing",
                "priority": 2,
                "arrival_rates": [[0, 900, 0.008]],
                "talk_time": {"kind": "exponential", "mean": 140},
                "patience": {"kind": "triangular", "low": 60, "mode": 150, "high": 300},
                "wrap_sec": 30,
                "sla_sec": 20,
            },
        ],
        "agents": [
            # 早班账单（0–1500，正好在高峰中到点）
            {"agent_id": "A01", "display_name": "早班-林晓", "capabilities": [
                {"language": "zh", "skill": "billing", "level": 1}],
                "shift_start": 0, "shift_end": 1500},
            {"agent_id": "A02", "display_name": "早班-赵磊", "capabilities": [
                {"language": "zh", "skill": "billing", "level": 1}],
                "shift_start": 0, "shift_end": 1500},
            # 晚班账单 1500 整点上班
            {"agent_id": "A03", "display_name": "晚班-陈静", "capabilities": [
                {"language": "zh", "skill": "billing", "level": 1}],
                "shift_start": 1500, "shift_end": 2700},
            {"agent_id": "A04", "display_name": "晚班-黄涛", "capabilities": [
                {"language": "zh", "skill": "billing", "level": 1}],
                "shift_start": 1500, "shift_end": 2700},
            # 夜班
            {"agent_id": "A05", "display_name": "夜班-周敏", "capabilities": [
                {"language": "zh", "skill": "billing", "level": 1}],
                "shift_start": 2400, "shift_end": 3600},
            # 技术线：早班 0–1500，晚班 1500–3600（整点交接）
            {"agent_id": "T01", "display_name": "技术早班-吴昊", "capabilities": [
                {"language": "zh", "skill": "tech", "level": 1}],
                "shift_start": 0, "shift_end": 1500},
            {"agent_id": "T02", "display_name": "技术晚班-郑楠", "capabilities": [
                {"language": "zh", "skill": "tech", "level": 1}],
                "shift_start": 1500, "shift_end": 3600},
            # 多技能支援岗（600–2700）
            {"agent_id": "S01", "display_name": "全能支援-冯远", "capabilities": [
                {"language": "zh", "skill": "billing", "level": 0},
                {"language": "zh", "skill": "tech", "level": 2}],
                "shift_start": 600, "shift_end": 2700},
            # 英文账单仅早班
            {"agent_id": "E01", "display_name": "English-Amy", "capabilities": [
                {"language": "en", "skill": "billing", "level": 1}],
                "shift_start": 0, "shift_end": 900},
        ],
        "overflow": {},
    }


def _scarce_base() -> dict:
    return {
        "horizon_sec": 1800,
        "default_seed": SEED,
        "call_types": [
            {
                "key": "general_zh",
                "language": "zh",
                "skill": "general",
                "priority": 1,
                "arrival_rates": [[0, 1800, 0.032]],
                "talk_time": {"kind": "exponential", "mean": 160},
                "patience": {"kind": "triangular", "low": 40, "mode": 90, "high": 240},
                "wrap_sec": 20,
                "sla_sec": 20,
            },
            {
                "key": "fraud_vip",
                "language": "zh",
                "skill": "fraud",
                "priority": 3,
                "arrival_rates": [[0, 1800, 0.012]],
                "talk_time": {"kind": "exponential", "mean": 280},
                "patience": {"kind": "triangular", "low": 60, "mode": 150, "high": 360},
                "wrap_sec": 60,
                "sla_sec": 30,
            },
        ],
        "agents": [
            {"agent_id": "G1", "display_name": "普通组-韩梅", "capabilities": [
                {"language": "zh", "skill": "general", "level": 1}],
                "shift_start": 0, "shift_end": 1800},
            {"agent_id": "G2", "display_name": "普通组-孙强", "capabilities": [
                {"language": "zh", "skill": "general", "level": 1}],
                "shift_start": 0, "shift_end": 1800},
            {"agent_id": "G3", "display_name": "普通组-马超", "capabilities": [
                {"language": "zh", "skill": "general", "level": 1}],
                "shift_start": 0, "shift_end": 1800},
            {"agent_id": "E1", "display_name": "反欺诈专家-苏晴", "capabilities": [
                {"language": "zh", "skill": "fraud", "level": 2}],
                "shift_start": 0, "shift_end": 1800},
            {"agent_id": "E2", "display_name": "反欺诈专家-林峰", "capabilities": [
                {"language": "zh", "skill": "fraud", "level": 2}],
                "shift_start": 0, "shift_end": 1800},
        ],
    }


def _scarce_a_config() -> dict:
    base = _scarce_base()
    base.update(
        name="稀缺技能 A：专家只接反欺诈（无溢出）",
        description=(
            "3 名普通坐席 + 2 名反欺诈专家。普通来电高峰排队，但严格不溢出，"
            "专家始终保持空闲容量给高优先级欺诈来电。作为对照基线。"
        ),
        overflow={},
    )
    return base


def _scarce_b_config() -> dict:
    base = _scarce_base()
    base.update(
        name="稀缺技能 B：普通来电等待 30 秒溢出给专家",
        description=(
            "与 A 完全相同的来电计划与种子(42)，仅增加溢出规则：普通来电等待超过 "
            "30 秒后允许反欺诈专家接听。观察专家被普通长通话占用后，欺诈 VIP 的"
            "服务水平如何下滑。"
        ),
        overflow={
            "general_zh": [
                {
                    "threshold_sec": 30,
                    "note": "30 秒未接通则溢出到反欺诈专家",
                    "add_capabilities": [{"language": "zh", "skill": "fraud", "level": 0}],
                }
            ]
        },
    )
    return base


DEMO_SCENARIOS = [
    (SCENARIO_CROSS_SHIFT, _cross_shift_config),
    (SCENARIO_SCARCE_A, _scarce_a_config),
    (SCENARIO_SCARCE_B, _scarce_b_config),
]
