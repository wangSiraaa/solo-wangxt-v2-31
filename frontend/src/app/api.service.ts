import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { RunDetail, RunSummary, Scenario } from './models';

@Injectable({ providedIn: 'root' })
export class ApiService {
  private http = inject(HttpClient);
  private base = '/api';

  health(): Observable<{ status: string; database: string }> {
    return this.http.get<{ status: string; database: string }>(`${this.base}/health`);
  }

  listScenarios(): Observable<Scenario[]> {
    return this.http.get<Scenario[]>(`${this.base}/scenarios`);
  }

  createRun(scenarioId: string, seed: number, label = ''): Observable<{ run_id: string; event_hash: string; event_count: number }> {
    return this.http.post<{ run_id: string; event_hash: string; event_count: number }>(
      `${this.base}/runs`, { scenario_id: scenarioId, seed, label });
  }

  getRun(runId: string): Observable<RunDetail> {
    return this.http.get<RunDetail>(`${this.base}/runs/${runId}`);
  }

  listRuns(scenarioId?: string): Observable<RunSummary[]> {
    const q = scenarioId ? `?scenario_id=${scenarioId}` : '';
    return this.http.get<RunSummary[]>(`${this.base}/runs${q}`);
  }

  verify(runId: string): Observable<{ stored_hash: string; recomputed_hash: string; ok: boolean }> {
    return this.http.post<{ stored_hash: string; recomputed_hash: string; ok: boolean }>(
      `${this.base}/runs/${runId}/verify`, {});
  }
}

/** 在浏览器端用同一批事件重算关键指标——证明图表来自事件流而非前端随机数。 */
export function recomputeFromEvents(events: SimEventLike[]): MetricsLite {
  const calls = new Map<string, any>();
  for (const ev of events) {
    if (ev.type === 'ARRIVAL') {
      calls.set(ev.call_id!, {
        outcome: 'WAITING', wait: null, metSla: null, skill: ev.skill,
        agent: null, overflow: false,
      });
    } else if (ev.type === 'ASSIGNED') {
      calls.set(ev.call_id!, {
        outcome: 'ANSWERED', wait: ev.wait_sec, metSla: ev.met_sla,
        skill: ev.skill, agent: ev.agent_id,
        overflow: (ev.overflow_rules_active?.length ?? 0) > 0,
      });
    } else if (ev.type === 'ABANDONED' || ev.type === 'EXPIRED') {
      const c = calls.get(ev.call_id!)!;
      c.outcome = ev.type;
      c.wait = ev.waited_sec;
      c.overflow = (ev.overflow_rules_active?.length ?? 0) > 0;
    }
  }
  const rows = [...calls.values()];
  const answered = rows.filter(c => c.outcome === 'ANSWERED');
  const abandoned = rows.filter(c => c.outcome === 'ABANDONED');
  const waits = answered.map(c => c.wait).sort((a, b) => a - b);
  const pct = (q: number) =>
    waits.length ? waits[Math.round(q * (waits.length - 1))] : null;
  const bySkill: Record<string, { total: number; answered: number; abandoned: number; sl: number | null }> = {};
  for (const c of rows) {
    const k = c.skill;
    bySkill[k] ??= { total: 0, answered: 0, abandoned: 0, sl: null };
    bySkill[k].total++;
    if (c.outcome === 'ANSWERED') {
      bySkill[k].answered++;
    }
    if (c.outcome === 'ABANDONED') bySkill[k].abandoned++;
  }
  for (const [k, b] of Object.entries(bySkill)) {
    const inSla = rows.filter(c => c.skill === k && c.outcome === 'ANSWERED' && c.metSla).length;
    b.sl = b.answered ? +(inSla / b.answered).toFixed(4) : null;
  }
  return {
    total: rows.length,
    answered: answered.length,
    abandoned: abandoned.length,
    abandonRate: rows.length ? +(abandoned.length / rows.length).toFixed(4) : null,
    withinSla: answered.filter(c => c.metSla).length,
    sl: answered.length ? +(answered.filter(c => c.metSla).length / answered.length).toFixed(4) : null,
    p50: pct(0.5), p90: pct(0.9),
    bySkill,
  };
}

export interface MetricsLite {
  total: number;
  answered: number;
  abandoned: number;
  abandonRate: number | null;
  withinSla: number;
  sl: number | null;
  p50: number | null;
  p90: number | null;
  bySkill: Record<string, { total: number; answered: number; abandoned: number; sl: number | null }>;
}

type SimEventLike = {
  type: string;
  call_id?: string;
  skill?: string;
  wait_sec?: number;
  waited_sec?: number;
  met_sla?: boolean;
  agent_id?: string;
  overflow_rules_active?: number[];
};
