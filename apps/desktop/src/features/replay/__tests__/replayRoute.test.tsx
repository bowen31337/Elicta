import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import ReplayRoute from '../route';

/**
 * The replay screen, connected.
 *
 * The placeholder rendered `embarrassmentCount={0}`, and zero is the *passing*
 * value for M2 — so a screen with nothing to show reported a clean release
 * gate for a build nobody had measured. That is the thing these guard.
 */
function stubService(table: Record<string, unknown>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      const body = table[path];
      if (body === undefined) return { ok: false, status: 404, json: async () => null } as Response;
      return { ok: true, status: 200, json: async () => body } as Response;
    }),
  );
}

const RUNS = {
  runs: [
    {
      run_id: 'run-1',
      recording_id: 'northwind-02',
      language: 'en',
      status: 'completed',
      progress: 1,
      suggestion_count: 12,
    },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe('the replay screen', () => {
  it('shows the run the service knows about, not an em dash', async () => {
    stubService({
      '/api/replay/runs': RUNS,
      '/api/replay/runs/run-1/metrics': {
        run_id: 'run-1',
        languages: [
          {
            language: 'en',
            surfaced_count: 10,
            useful_count: 8,
            precision_at_surfaced: 0.8,
            embarrassing_count: 0,
            clears_m2_gate: true,
          },
        ],
      },
    });
    render(<ReplayRoute />);

    expect(
      await screen.findByRole('heading', { name: /northwind-02/ }),
    ).toBeInTheDocument();
    expect(screen.getByText('80%')).toBeInTheDocument();
  });

  it('reports a failing M2 as the count the service measured', async () => {
    stubService({
      '/api/replay/runs': RUNS,
      '/api/replay/runs/run-1/metrics': {
        run_id: 'run-1',
        languages: [
          {
            language: 'en',
            surfaced_count: 10,
            useful_count: 8,
            precision_at_surfaced: 0.8,
            embarrassing_count: 2,
            clears_m2_gate: false,
          },
        ],
      },
    });
    render(<ReplayRoute />);

    expect(await screen.findByText('2')).toBeInTheDocument();
  });

  it('scores the run in the language it was conducted in, never a blend', async () => {
    stubService({
      '/api/replay/runs': {
        runs: [{ ...RUNS.runs[0], language: 'pt' }],
      },
      '/api/replay/runs/run-1/metrics': {
        run_id: 'run-1',
        languages: [
          {
            language: 'en',
            surfaced_count: 10,
            useful_count: 10,
            precision_at_surfaced: 1,
            embarrassing_count: 0,
            clears_m2_gate: true,
          },
          {
            language: 'pt',
            surfaced_count: 4,
            useful_count: 1,
            precision_at_surfaced: 0.25,
            embarrassing_count: 1,
            clears_m2_gate: false,
          },
        ],
      },
    });
    render(<ReplayRoute />);

    // The English figures are excellent and belong to a different gate.
    expect(await screen.findByText('25%')).toBeInTheDocument();
    expect(screen.queryByText('100%')).not.toBeInTheDocument();
  });

  it('says no run has been started rather than showing a passing M2', async () => {
    stubService({ '/api/replay/runs': { runs: [] } });
    render(<ReplayRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Nothing selected yet' }),
    ).toBeInTheDocument();
    expect(screen.queryByText('M2 needs zero')).not.toBeInTheDocument();
  });

  it('shows nothing rather than an unmeasured gate when the service is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<ReplayRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Cannot reach the service' }),
    ).toBeInTheDocument();
    expect(screen.queryByText('M2 needs zero')).not.toBeInTheDocument();
  });
});

describe('how much evidence the gates rest on', () => {
  /**
   * A live run photographed "Useful when surfaced 100%" in green against
   * "M1 needs 70%" — measured over exactly one rated suggestion, with nothing
   * on screen to say so. These two numbers block a release, and a reader
   * cannot judge a rate without knowing what it was taken over. The CI gate
   * has always printed the fraction; the screen printed the percentage alone.
   */
  it('says how many ratings the precision figure was taken over', async () => {
    stubService({
      '/api/replay/runs': RUNS,
      '/api/replay/runs/run-1/metrics': {
        run_id: 'run-1',
        languages: [
          {
            language: 'en',
            surfaced_count: 1,
            useful_count: 1,
            embarrassing_count: 0,
            precision_at_surfaced: 1,
          },
        ],
      },
    });
    render(<ReplayRoute />);

    expect(await screen.findByText('100%')).toBeInTheDocument();
    expect(screen.getByText(/1 of 1 rated/i)).toBeInTheDocument();
  });

  it('says nothing has been rated rather than showing a rate over nothing', async () => {
    stubService({
      '/api/replay/runs': RUNS,
      '/api/replay/runs/run-1/metrics': {
        run_id: 'run-1',
        languages: [
          {
            language: 'en',
            surfaced_count: 0,
            useful_count: 0,
            embarrassing_count: 0,
            precision_at_surfaced: 0,
          },
        ],
      },
    });
    render(<ReplayRoute />);

    // Both gates say it, because both are unmeasured.
    expect(await screen.findAllByText(/nothing rated yet/i)).toHaveLength(2);
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
  });
});
