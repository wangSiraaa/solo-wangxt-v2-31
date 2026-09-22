from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CallSpec(BaseModel):
    id: str = Field(..., min_length=1)
    arrival_time: float = Field(..., ge=0)
    language: str
    skill: str
    priority: int = Field(default=1, ge=1)
    service_time: float | None = Field(default=None, ge=0)
    patience: float | None = Field(default=None, ge=0)


class ArrivalProfile(BaseModel):
    language: str
    skill: str
    priority: int = Field(default=1, ge=1)
    count: int = Field(..., ge=1)
    first_arrival: float = Field(..., ge=0)
    mean_interarrival: float = Field(..., gt=0)
    mean_service: float = Field(..., gt=0)
    mean_patience: float = Field(..., gt=0)


class AgentSpec(BaseModel):
    id: str = Field(..., min_length=1)
    name: str
    skills: list[str]
    languages: list[str]
    shift_start: float = Field(..., ge=0)
    shift_end: float = Field(..., ge=0)
    wrap_time: float = Field(..., ge=0)

    @field_validator("shift_end")
    @classmethod
    def shift_after_start(cls, value: float, info):
        start = info.data.get("shift_start", 0)
        if value < start:
            raise ValueError("shift_end must be greater than or equal to shift_start")
        return value


class OverflowRule(BaseModel):
    from_skill: str
    to_skill: str
    wait_threshold: float = Field(..., ge=0)


class ScenarioInput(BaseModel):
    name: str = Field(..., min_length=1)
    duration: float = Field(..., gt=0)
    language_required: bool = True
    routing: Literal["priority_fifo", "longest_waiting"] = "priority_fifo"
    calls: list[CallSpec] = Field(default_factory=list)
    arrival_profiles: list[ArrivalProfile] = Field(default_factory=list)
    agents: list[AgentSpec]
    overflow_rules: list[OverflowRule] = Field(default_factory=list)
    default_service_time: float = Field(default=180, gt=0)
    default_patience: float = Field(default=120, ge=0)
    enable_random_patience: bool = False
    enable_random_service: bool = False

    @field_validator("calls", "agents")
    @classmethod
    def unique_ids(cls, value: list):
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("ids must be unique")
        return value

    @model_validator(mode="after")
    def validate_scenario(self):
        if not self.calls and not self.arrival_profiles:
            raise ValueError("at least one call or arrival profile is required")
        for call in self.calls:
            if call.arrival_time > self.duration:
                raise ValueError(f"call {call.id} arrives after the simulation duration")
        for agent in self.agents:
            if agent.shift_start > self.duration:
                raise ValueError(f"agent {agent.id} starts after the simulation duration")
            if not agent.skills or not agent.languages:
                raise ValueError(f"agent {agent.id} requires skills and languages")
        return self


class ScenarioSave(ScenarioInput):
    seed: int = Field(default=777, ge=0)


class ScenarioResponse(ScenarioSave):
    id: int

    model_config = ConfigDict(from_attributes=True)


class RunRequest(BaseModel):
    scenario_id: int | None = None
    seed: int | None = Field(default=None, ge=0)
    scenario: ScenarioInput | None = None


class RunResponse(BaseModel):
    run_id: int | None = None
    scenario_id: int | None = None
    seed: int
    duration: float
    events: list[dict]
    metrics: dict
    waiting_distribution: list[dict]
    agent_timeline: list[dict]
