export interface Scenario {
  id: number;
  name: string;
  seed: number;
  duration: number;
  calls: unknown[];
  agents: unknown[];
  overflow_rules: unknown[];
}

export interface SimEvent {
  id: number;
  time: number;
  type: string;
  message: string;
  call_id: string | null;
  agent_id: string | null;
  reason: { code: string; detail: string; factors: Record<string, unknown> };
  call: Record<string, unknown> | null;
  queue_before: QueueItem[];
  queue_after: QueueItem[];
  agent_before: AgentSnapshot | null;
  agent_after: AgentSnapshot | null;
  agents_snapshot: AgentSnapshot[];
  data: Record<string, unknown>;
}

export interface QueueItem {
  call_id: string;
  language: string;
  skill: string;
  priority: number;
  waiting_for: number;
  escalations: string[];
}

export interface AgentSnapshot {
  agent_id: string;
  name: string;
  state: 'offline' | 'available' | 'busy' | 'wrap';
  pending_offline: boolean;
  skills: string[];
  languages: string[];
  shift_start: number;
  shift_end: number;
}

export interface SimulationResult {
  run_id: number | null;
  scenario_id: number | null;
  seed: number;
  duration: number;
  events: SimEvent[];
  metrics: {
    overall: SkillStat;
    by_skill: Record<string, SkillStat>;
  };
  waiting_distribution: WaitBucket[];
  agent_timeline: AgentTimeline[];
}

export interface SkillStat {
  offered: number;
  answered: number;
  abandoned: number;
  answered_within_20s: number;
  service_level_20: number | null;
  abandonment_rate: number | null;
  average_wait: number | null;
  max_wait: number;
}

export interface WaitBucket {
  lower: number | null;
  upper: number | null;
  answered: number;
  abandoned: number;
  total: number;
}

export interface AgentTimeline {
  agent_id: string;
  name: string;
  segments: { start: number; end: number; state: string; duration: number }[];
  talk_seconds: number;
  wrap_seconds: number;
  logged_in_seconds: number;
  occupancy_pct: number | null;
}
