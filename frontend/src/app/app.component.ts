import { Component, OnDestroy, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { interval, Subscription } from 'rxjs';
import { SimulationService } from './simulation.service';
import { AgentSnapshot, AgentTimeline, Scenario, SimEvent, SimulationResult } from './models';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './app.component.html',
  styleUrl: './app.component.css',
})
export class AppComponent implements OnInit, OnDestroy {
  private service = inject(SimulationService);
  private timer?: Subscription;

  scenarios: Scenario[] = [];
  selectedScenarioId: number | null = null;
  seed = 9901;
  result?: SimulationResult;
  loading = false;
  error = '';
  currentTime = 0;
  playing = false;
  selectedEventId: number | null = null;

  ngOnInit(): void {
    this.service.listScenarios().subscribe({
      next: (scenarios) => {
        this.scenarios = scenarios;
        this.selectedScenarioId = scenarios[0]?.id ?? null;
        if (this.selectedScenarioId !== null) {
          const selected = scenarios.find((item) => item.id === this.selectedScenarioId);
          if (selected) this.seed = selected.seed;
          this.runSimulation();
        }
      },
      error: (err) => (this.error = `无法加载场景：${err.message}`),
    });
  }

  ngOnDestroy(): void {
    this.timer?.unsubscribe();
  }

  runSimulation(): void {
    if (this.selectedScenarioId === null) return;
    this.pause();
    this.loading = true;
    this.error = '';
    this.service.run(this.selectedScenarioId, this.seed).subscribe({
      next: (result) => {
        this.result = result;
        this.currentTime = 0;
        this.selectedEventId = null;
        this.loading = false;
      },
      error: (err) => {
        this.error = `仿真失败：${err.error?.detail ?? err.message}`;
        this.loading = false;
      },
    });
  }

  onScenarioChange(): void {
    const selected = this.scenarios.find((item) => item.id === this.selectedScenarioId);
    if (selected) this.seed = selected.seed;
    this.runSimulation();
  }

  get maxTime(): number {
    return this.result ? Math.max(...this.result.events.map((event) => event.time)) : 0;
  }

  get visibleEvents(): SimEvent[] {
    return this.result?.events.filter((event) => event.time <= this.currentTime + 1e-9) ?? [];
  }

  get currentEvent(): SimEvent | undefined {
    if (!this.result) return undefined;
    const list = this.visibleEvents;
    return this.selectedEventId
      ? list.find((event) => event.id === this.selectedEventId)
      : list[list.length - 1];
  }

  get latestSnapshot(): AgentSnapshot[] {
    return this.currentEvent?.agents_snapshot ?? this.result?.events[0]?.agents_snapshot ?? [];
  }

  get queueLengthSeries(): { time: number; length: number }[] {
    if (!this.result) return [];
    return this.result.events.map((event) => ({
      time: event.time,
      length: event.queue_after.length,
    }));
  }

  get maxQueueLength(): number {
    return Math.max(1, ...this.queueLengthSeries.map((point) => point.length));
  }

  queuePath(width = 620, height = 150): string {
    const series = this.queueLengthSeries;
    if (series.length < 2) return '';
    const maxTime = this.maxTime || 1;
    return series
      .map((point, index) => {
        const x = (point.time / maxTime) * width;
        const y = height - (point.length / this.maxQueueLength) * (height - 24) - 12;
        return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(' ');
  }

  visiblePoint(point: { time: number }): boolean {
    return point.time <= this.currentTime + 1e-9;
  }

  play(): void {
    if (!this.result) return;
    this.playing = true;
    this.timer = interval(250).subscribe(() => {
      const next = this.result?.events.find((event) => event.time > this.currentTime + 1e-9);
      if (!next) {
        this.pause();
        return;
      }
      this.currentTime = next.time;
    });
  }

  pause(): void {
    this.playing = false;
    this.timer?.unsubscribe();
  }

  step(delta: number): void {
    this.pause();
    const times = this.result?.events.map((event) => event.time).sort((a, b) => a - b) ?? [];
    const index = times.findIndex((time) => Math.abs(time - this.currentTime) < 1e-9);
    const target = times[index + delta] ?? times[delta < 0 ? 0 : times.length - 1];
    if (target !== undefined) this.currentTime = target;
  }

  selectEvent(event: SimEvent): void {
    this.pause();
    this.currentTime = event.time;
    this.selectedEventId = event.id;
  }

  percent(value: number | null | undefined): string {
    if (value === null || value === undefined) return '—';
    return `${(value * 100).toFixed(1)}%`;
  }

  stateLabel(state: string | null | undefined): string {
    if (!state) return '—';
    return { offline: '离线', available: '空闲', busy: '通话', wrap: '整理' }[state] ?? state;
  }

  segmentStyle(start: number, end: number): string {
    const duration = this.result?.duration ?? 1;
    const left = (start / duration) * 100;
    const width = Math.max(0.4, ((end - start) / duration) * 100);
    return `left: ${left}%; width: ${width}%;`;
  }

  playedSegments(segments: AgentTimeline['segments']): AgentTimeline['segments'] {
    return segments
      .filter((segment) => segment.start <= this.currentTime)
      .map((segment) => ({
        ...segment,
        end: Math.min(segment.end, this.currentTime),
        duration: Math.max(0, this.currentTime - segment.start),
      }))
      .filter((segment) => segment.end > segment.start);
  }

  keyValues(record: Record<string, unknown>): { key: string; value: unknown }[] {
    return Object.entries(record).map(([key, value]) => ({ key, value }));
  }

  skillEntries(): { key: string; value: SimulationResult['metrics']['by_skill'][string] }[] {
    return Object.entries(this.result?.metrics.by_skill ?? {}).map(([key, value]) => ({ key, value }));
  }
}
