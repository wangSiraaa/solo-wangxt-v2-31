"""场景配置与 API 出入参的 Pydantic 模型。

时间单位全部为「秒」，仿真钟从 0 开始；horizon 之后不再产生新来电，
但已接通的通话/整理会继续跑完（见 engine.py）。
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

DistKind = Literal["fixed", "exponential", "uniform", "triangular"]


class Distribution(BaseModel):
    """随机分布规格。fixed: 定值；exponential: mean；uniform: low/high；triangular: low/mode/high。"""

    kind: DistKind
    mean: Optional[float] = None
    low: Optional[float] = None
    mode: Optional[float] = None
    high: Optional[float] = None

    def sample(self, rng) -> float:
        if self.kind == "fixed":
            return float(self.mean)
        if self.kind == "exponential":
            return rng.expovariate(1.0 / self.mean)
        if self.kind == "uniform":
            return rng.uniform(self.low, self.high)
        return rng.triangular(self.low, self.mode, self.high)


class Capability(BaseModel):
    """坐席能力：(语言, 技能) 二元组。language='*' 表示任意语言。"""

    language: str
    skill: str
    level: int = 0  # 最佳适配排序用：等级越高越优先被该类来电选中


class OverflowRule(BaseModel):
    """溢出规则：某类来电等待超过 threshold_sec 后，允许接入额外能力集合。

    language='*' / skill='*' 表示该维度通配。规则按顺序逐条生效。
    """

    threshold_sec: float = Field(ge=0)
    add_capabilities: list[Capability] = Field(default_factory=list)
    note: str = ""


class CallType(BaseModel):
    """来电类型：语言 + 技能 + 优先级（数字越大越优先）。"""

    key: str
    language: str
    skill: str
    priority: int = 0
    # 分段到达率：[(开始秒, 结束秒, 每秒呼叫数)]，区间外无到达
    arrival_rates: list[tuple[float, float, float]]
    talk_time: Distribution
    patience: Distribution = Field(description="放弃等待前的最大排队时长分布")
    wrap_sec: float = Field(default=30.0, ge=0)
    sla_sec: float = Field(default=20.0, ge=0)

    @field_validator("arrival_rates")
    @classmethod
    def _rates_nonempty(cls, v):
        if not v:
            raise ValueError("arrival_rates 至少需要一个 (start, end, rate) 区间")
        for start, end, rate in v:
            if end <= start or rate < 0:
                raise ValueError("到达率区间必须 end>start 且 rate>=0")
        return v


class AgentSpec(BaseModel):
    agent_id: str
    display_name: str = ""
    capabilities: list[Capability]
    shift_start: float = Field(ge=0)
    shift_end: float = Field(ge=0)
    # 坐席个人整理时长覆盖；None 时使用来电类型的 wrap_sec
    wrap_override: Optional[float] = None

    @field_validator("shift_end")
    @classmethod
    def _end_after_start(cls, v, info):
        start = info.data.get("shift_start")
        if start is not None and v <= start:
            raise ValueError("下班时间必须晚于上班时间")
        return v


class ScenarioConfig(BaseModel):
    name: str
    description: str = ""
    horizon_sec: float = Field(gt=0)
    call_types: list[CallType]
    agents: list[AgentSpec]
    overflow: dict[str, list[OverflowRule]] = Field(default_factory=dict)
    default_seed: int = 42

    def call_type(self, key: str) -> CallType:
        return next(ct for ct in self.call_types if ct.key == key)


# ---------- API 模型 ----------


class ScenarioIn(BaseModel):
    name: str
    description: str = ""
    config: dict
    default_seed: int = 42


class ScenarioOut(BaseModel):
    id: str
    name: str
    description: str
    config: dict
    default_seed: int


class RunRequest(BaseModel):
    scenario_id: Optional[str] = None
    seed: int = 42
    # scenario_id 为空时可直接提交临时配置运行（不落库场景表，结果仍落库）
    config: Optional[dict] = None
    label: str = ""


class RunSummary(BaseModel):
    run_id: str
    scenario_id: Optional[str]
    seed: int
    label: str
    deterministic: bool
    total_calls: int
    answered: int
    abandoned: int
    expired: int
    abandon_rate: float
    service_level_overall: float
    wait_percentiles: dict
    metrics: dict
