import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Scenario, SimulationResult } from './models';

@Injectable({ providedIn: 'root' })
export class SimulationService {
  private http = inject(HttpClient);

  listScenarios(): Observable<Scenario[]> {
    return this.http.get<Scenario[]>('/api/scenarios');
  }

  run(scenarioId: number, seed?: number): Observable<SimulationResult> {
    return this.http.post<SimulationResult>('/api/simulations', {
      scenario_id: scenarioId,
      seed,
    });
  }

  adHoc(scenario: unknown, seed: number): Observable<SimulationResult> {
    return this.http.post<SimulationResult>('/api/simulations', { scenario, seed });
  }
}
