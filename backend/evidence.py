from __future__ import annotations

from app.scenarios import CROSS_SHIFT_SCENARIO, SCARCE_SKILL_SCENARIO
from app.simulation import run_simulation


def print_evidence(title: str, scenario: dict):
    result = run_simulation(scenario, 9901)
    print(f"\n{title}")
    print("=" * len(title))
    for event in result["events"]:
        if event["type"] in {"ARRIVAL", "DISPATCH", "ABANDONED", "OVERFLOW_ELIGIBLE", "WRAP_COMPLETED"}:
            print(f"{event['time']:>6.0f}s {event['type']:<18} {event['message']}")
    print("\n指标（由上述事件重放得到）")
    print(result["metrics"])
    print("等待分布", result["waiting_distribution"])
    print("坐席占用", result["agent_timeline"])


if __name__ == "__main__":
    print_evidence("跨班次 + 通话后整理", CROSS_SHIFT_SCENARIO)
    print_evidence("稀缺技能挤占 + 优先级 + 溢出", SCARCE_SKILL_SCENARIO)
