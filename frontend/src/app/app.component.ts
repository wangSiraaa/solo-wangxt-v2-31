import { CommonModule } from '@angular/common';
import { Component, OnInit, signal } from '@angular/core';
import { HttpClientModule } from '@angular/common/http';
import { ApiService, recomputeFromEvents } from './api.service';
import { RunDetail, Scenario } from './models';
import { TimelinePlayerComponent } from './timeline-player/timeline-player.component';
import { MetricsDashboardComponent } from './metrics-dashboard/metrics-dashboard.component';

interface CompareCell {
  name: string;
  total: number;
  answered: number;
  abandoned: number;
  abandonRate: number | null;
  sl: number | null;
  slFraud: number | null;
  slGeneral: number | null;
  overflowShareGeneral: number | null;
  occ: number | null;
  eventHash: string;
}

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, HttpClientModule, TimelinePlayerComponent, MetricsDashboardComponent],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit {
  scenarios = signal<Scenario[]>([]);
  selectedId = signal<string>('');
  seed = signal<number>(42);
  loading = signal(false);
  running = signal(false);
  run = signal<RunDetail | null>(null);
  cursor = signal(0);
  dbKind = signal('');
  verifyOk = signal<boolean | null>(null);
  verifyHash = signal('');
  tab = signal<'replay' | 'metrics'>('replay');
  comparing = signal(false);
  compare = signal<{ a?: CompareCell; b?: CompareCell } | null>(null);

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.api.health().subscribe(h => this.dbKind.set(h.database));
    this.loading.set(true);
    this.api.listScenarios().subscribe(list => {
      this.scenarios.set(list);
      this.selectedId.set(list[0]?.id ?? '');
      this.loading.set(false);
      if (list[0]) this.startRun(list[0].id, list[0].default_seed);
    });
  }

  selectedScenario(): Scenario | undefined {
    return this.scenarios().find(s => s.id === this.selectedId());
  }

  startRun(id = this.selectedId(), seed = this.seed()): void {
    this.running.set(true);
    this.verifyOk.set(null);
    this.api.createRun(id, seed, '').subscribe({
      next: created => {
        this.api.getRun(created.run_id).subscribe(detail => {
          this.run.set(detail);
          this.verifyHash.set(detail.event_hash);
          this.running.set(false);
          this.api.verify(detail.run_id).subscribe(v => this.verifyOk.set(v.ok));
        });
      },
      error: () => this.running.set(false),
    });
  }

  clientSideMetrics() {
    const r = this.run();
    return r ? recomputeFromEvents(r.events as any[]) : null;
  }

  /** 运行稀缺技能 A/B 两个场景，用同种子对比挤占效应。 */
  runComparison(): void {
    this.comparing.set(true);
    const all = this.scenarios();
    const a = all.find(s => s.name.includes('稀缺技能 A'));
    const b = all.find(s => s.name.includes('稀缺技能 B'));
    if (!a || !b) return;
    let cellA: CompareCell | undefined;
    let cellB: CompareCell | undefined;
    const build = (s: Scenario, runId: string, cb: (c: CompareCell) => void) => {
      this.api.getRun(runId).subscribe(d => {
        cb({
          name: s.name,
          total: d.metrics.total_calls,
          answered: d.metrics.answered,
          abandoned: d.metrics.abandoned,
          abandonRate: d.metrics.abandon_rate,
          sl: d.metrics.overall.sl,
          slFraud: d.metrics.by_skill['fraud']?.sl ?? null,
          slGeneral: d.metrics.by_skill['general']?.sl ?? null,
          overflowShareGeneral: d.metrics.by_skill['general']?.overflow_share ?? null,
          occ: d.metrics.pooled_occupancy,
          eventHash: d.event_hash,
        });
      });
    };
    this.api.createRun(a.id, 42).subscribe(ra =>
      build(a, ra.run_id, c => { cellA = c; if (cellA && cellB) this.compare.set({ a: cellA, b: cellB }); }));
    this.api.createRun(b.id, 42).subscribe(rb =>
      build(b, rb.run_id, c => { cellB = c; if (cellA && cellB) this.compare.set({ a: cellA, b: cellB }); }));
  }

  fmtPct(v: number | null): string { return v == null ? '—' : (v * 100).toFixed(1) + '%'; }

  shortHash(h: string): string { return h ? h.slice(0, 12) + '…' : ''; }
}
