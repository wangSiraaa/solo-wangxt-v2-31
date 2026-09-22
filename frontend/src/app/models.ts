/** 后端事件 / 指标的 TypeScript 镜像（backend/app/sim/engine.py 与 metrics.py）。 */

export interface QueueRow {
  call_id: string;
  type_key: string;
  language: string;
  skill: string;
  priority: number;
  enqueue_time: number;
  waited: number;
  overflow_rules_active: number[];
}

export interface AgentRow {
  agent_id: string;
  name: string;
  status: 'OFFLINE' | 'AVAILABLE' | 'ON_CALL' | 'WRAP';
  current_call: string | null;
  shift_start: number;
  shift_end: number;
  pending_logout: boolean;
}

export type SimEventType =
  | 'SIM_START' | 'ARRIVAL' | 'ASSIGNED' | 'CALL_END'
  | 'WRAP_START' | 'WRAP_END'
  | 'ABANDONED' | 'OVERFLOW' | 'EXPIRED'
  | 'SHIFT_START' | 'SHIFT_END' | 'SHIFT_END_PENDING'
  | 'SIM_END';

export interface SimEvent {
  seq: number;
  t: number;
  type: SimEventType;
  reason: string;
  call_id?: string;
  type_key?: string;
  language?: string;
  skill?: string;
  priority?: number;
  agent_id?: string;
  wait_sec?: number;
  waited_sec?: number;
  patience_sec?: number;
  talk_sec?: number;
  wrap_sec?: number;
  sla_sec?: number;
  met_sla?: boolean;
  threshold_sec?: number;
  rule_index?: number;
  added_capabilities?: { language: string; skill: string; level: number }[];
  note?: string;
  current_call?: string | null;
  overflow_rules_active?: number[];
  horizon_sec?: number;
  seed?: number;
  label?: string;
  planned_calls?: number;
  t_final?: number;
  queue_before: QueueRow[];
  queue_after: QueueRow[];
  agents_before: AgentRow[];
  agents_after: AgentRow[];
}

export interface SkillBlock {
  total: number;
  answered: number;
  abandoned: number;
  expired: number;
  abandon_rate: number | null;
  answer_rate: number | null;
  sl: number | null;
  asa: number | null;
  within_sla: number;
  sla_sec: number | null;
  overflow_share: number | null;
  wait_p50: number | null;
  wait_p80: number | null;
  wait_p90: number | null;
  wait_p95: number | null;
  wait_p99: number | null;
  wait_max: number | null;
  wait_histogram: Record<string, number>;
}

export interface AgentInterval {
  start: number;
  end: number;
  status: string;
}

export interface AgentTimeline {
  staffed_sec: number;
  busy_sec: number;
  occupancy: number | null;
  intervals: AgentInterval[];
}

export interface Metrics {
  horizon_sec: number;
  total_calls: number;
  answered: number;
  abandoned: number;
  expired: number;
  abandon_rate: number | null;
  answer_rate: number | null;
  pooled_occupancy: number | null;
  avg_queue_length: number;
  overall: SkillBlock;
  by_skill: Record<string, SkillBlock>;
  by_language: Record<string, SkillBlock>;
  by_type: Record<string, SkillBlock>;
  wait_distribution_all_answered: {
    p50: number | null; p80: number | null; p90: number | null;
    p95: number | null; p99: number | null; max: number | null;
    histogram: Record<string, number>;
  };
  agents: Record<string, AgentTimeline>;
  queue_timeline: { t: number; seq: number; type: string; waiting: number }[];
}

export interface Scenario {
  id: string;
  name: string;
  description: string;
  config: any;
  default_seed: number;
}

export interface RunDetail {
  run_id: string;
  scenario_id: string | null;
  seed: number;
  label: string;
  event_hash: string;
  event_count: number;
  planned_calls: number;
  horizon_sec: number;
  metrics: Metrics;
  events: SimEvent[];
}

export interface RunSummary {
  run_id: string;
  scenario_id: string | null;
  seed: number;
  label: string;
  event_hash: string;
  event_count: number;
  planned_calls: number;
}
