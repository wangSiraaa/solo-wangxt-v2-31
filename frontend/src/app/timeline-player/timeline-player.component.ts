import { CommonModule } from '@angular/common';
import {
  Component, EventEmitter, Input, OnDestroy, Output, effect, signal,
} from '@angular/core';
import { EVENT_COLORS, explainEvent } from '../explain';
import { SimEvent } from '../models';

@Component({
  selector: 'app-timeline-player',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './timeline-player.component.html',
  styleUrl: './timeline-player.component.css',
})
export class TimelinePlayerComponent implements OnDestroy {
  @Input() set events(value: SimEvent[]) {
    this._events = value;
    this.cursor.set(0);
  }
  get events(): SimEvent[] { return this._events; }
  private _events: SimEvent[] = [];

  @Output() cursorChange = new EventEmitter<number>();

  cursor = signal(0);
  playing = signal(false);
  speed = signal(8); // 每秒播放的事件数

  private timer: ReturnType<typeof setInterval> | null = null;
  readonly colors = EVENT_COLORS;
  readonly explain = explainEvent;

  constructor() {
    effect(() => this.cursorChange.emit(this.cursor()));
  }

  get current(): SimEvent | undefined {
    return this._events[this.cursor()];
  }

  play(): void {
    if (this.playing()) return;
    if (this.cursor() >= this._events.length - 1) this.cursor.set(0);
    this.playing.set(true);
    this.timer = setInterval(() => {
      const next = this.cursor() + 1;
      if (next >= this._events.length) {
        this.pause();
        return;
      }
      this.cursor.set(next);
    }, 1000 / this.speed());
  }

  pause(): void {
    this.playing.set(false);
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
  }

  step(delta: number): void {
    this.pause();
    this.cursor.set(Math.min(this._events.length - 1, Math.max(0, this.cursor() + delta)));
  }

  seek(evt: SimEvent): void {
    this.pause();
    this.cursor.set(evt.seq);
  }

  setSpeed(v: number): void {
    this.speed.set(v);
    if (this.playing()) { this.pause(); this.play(); }
  }

  fmt(t: number | undefined): string {
    if (t == null) return '-';
    const s = Math.floor(t);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}.${String(Math.round((t - s) * 10)).padStart(1, '0')}`;
  }

  eventKindFilter = signal<string>('');

  visibleEvents(): SimEvent[] {
    const f = this.eventKindFilter();
    return f ? this._events.filter(e => e.type === f) : this._events;
  }

  kindOptions(): string[] {
    return [...new Set(this._events.map(e => e.type))];
  }

  ngOnDestroy(): void { this.pause(); }
}
