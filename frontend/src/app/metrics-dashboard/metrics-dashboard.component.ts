import { Component, Input, computed, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Metrics } from '../models';

@Component({
  selector: 'app-metrics-dashboard',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './metrics-dashboard.component.html',
  styleUrl: './metrics-dashboard.component.css',
})
export class MetricsDashboardComponent {
  private _metrics = signal<Metrics | null>(null);
  @Input() set metrics(m: Metrics | null) { this._metrics.set(m); }
  metricsSig = this._metrics;

  /** 可选：浏览器端用事件重算的结果，用于逐格对照后端数字。 */
  private _clientSide = signal<any>(null);
  @Input() set clientSide(v: any) { this._clientSide.set(v); }
  clientSideSig = this._clientSide;

  hist = computed(() => {
    const m = this._metrics();
    if (!m) return [] as { label: string; count: number; pct: number }[];
    const h = m.wait_distribution_all_answered.histogram;
    const entries = Object.entries(h);
    const max = Math.max(1, ...entries.map(([, v]) => v));
    return entries.map(([label, count]) => ({
      label: label.replace('Infinity', '∞'),
      count,
      pct: Math.round((count / max) * 100),
    }));
  });

  queueCurve = computed(() => {
    const m = this._metrics();
    if (!m || !m.queue_timeline.length) return { points: '', area: '' };
    const tl = m.queue_timeline;
    const w = 1000;
    const maxQ = Math.max(1, ...tl.map(p => p.waiting));
    const maxT = Math.max(1, m.horizon_sec, tl[tl.length - 1].t);
    const step = w / Math.max(1, tl.length - 1);
    const xy = tl.map((p, i) => `${(i * step).toFixed(1)},${(120 - (p.waiting / maxQ) * 112).toFixed(1)}`);
    const points = xy.join(' ');
    const area = `0,120 ${points} ${w},120`;
    return { points, area, w, maxT, maxQ };
  });

  pct(v: number | null): string {
    return v == null ? '—' : (v * 100).toFixed(1) + '%';
  }
  num(v: number | null, d = 1): string {
    return v == null ? '—' : v.toFixed(d);
  }
  skillRows = computed(() => Object.entries(this._metrics()?.by_skill ?? {}).map(([skill, b]) => ({ skill, b })));
  typeRows = computed(() => Object.entries(this._metrics()?.by_type ?? {}).map(([typeKey, b]) => ({ typeKey, b })));
  agentRows = computed(() => Object.entries(this._metrics()?.agents ?? {}).map(([agentId, a]) => ({ agentId, a })));
  skillKeys = computed(() => Object.keys(this._metrics()?.by_skill ?? {}));
  readonly Object = Object;
  readonly Math = Math;

  slColor(v: number | null): string {
    if (v == null) return 'var(--muted)';
    return v >= 0.8 ? 'var(--green)' : v >= 0.5 ? 'var(--yellow)' : 'var(--red)';
  }
}
