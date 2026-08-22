import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import RecordingRoute from '../route';

/**
 * The recording review screen, connected.
 *
 * Two things here are worse than showing nothing: attributing a divergence to
 * the wrong speaker, and saying the audio was destroyed when the attempt
 * failed. Both are asserted.
 */
const BASE: Record<string, unknown> = {
  '/api/engagements': {
    items: [
      {
        engagement_id: 'eng-1',
        client_organisation: 'Ridgeway Health',
        sector: 'healthcare',
        commercial_context: 'Referrals rebuild',
        purpose: null,
        scope_boundary: null,
        target_requirements_template: null,
      },
    ],
    total: 1,
  },
  '/api/engagements/eng-1/meetings': {
    engagement_id: 'eng-1',
    meetings: [
      {
        meeting_id: 'meeting-1',
        engagement_id: 'eng-1',
        state: 'planned',
        capture_mode: 'record',
        scheduled_at: null,
        session_purpose: 'Discovery 1',
        sections_filled: null,
        sections_total: null,
      },
    ],
  },
};

const ALIGNMENT = {
  session_id: 'meeting-1',
  reference_engine: 'engine-a',
  other_engine: 'engine-b',
  spans: [
    {
      start_seconds: 0,
      end_seconds: 10,
      reference_engine: 'engine-a',
      reference_text: 'we need it fast',
      other_engine: 'engine-b',
      other_text: 'we need it fast',
      agreement_score: 1,
      is_divergent: false,
    },
    {
      start_seconds: 61,
      end_seconds: 65,
      reference_engine: 'engine-a',
      reference_text: 'the TMS handoff',
      other_engine: 'engine-b',
      other_text: 'the DMS handoff',
      agreement_score: 0.5,
      is_divergent: true,
    },
  ],
};

const TRANSCRIPTS = [
  {
    engine: 'engine-a',
    status: 'complete',
    segments: [
      { start_seconds: 60, end_seconds: 70, text: 'the TMS handoff', speaker: 'Priya' },
    ],
  },
  { engine: 'engine-b', status: 'failed', segments: [] },
];

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

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe('the recording review screen', () => {
  it('shows only the spans the engines actually disagreed on', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/record/divergences': ALIGNMENT,
      '/api/sessions/meeting-1/record-path-transcript': TRANSCRIPTS,
    });
    render(<RecordingRoute />);

    expect(await screen.findByText('“the TMS handoff”')).toBeInTheDocument();
    expect(screen.getByText('“the DMS handoff”')).toBeInTheDocument();
    expect(screen.queryByText('“we need it fast”')).not.toBeInTheDocument();
    expect(screen.getByText('1:01–1:05')).toBeInTheDocument();
  });

  it('reports the agreement rate the alignment actually measured', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/record/divergences': ALIGNMENT,
      '/api/sessions/meeting-1/record-path-transcript': TRANSCRIPTS,
    });
    render(<RecordingRoute />);

    expect(await screen.findByText('50%')).toBeInTheDocument();
  });

  it('names both engines and does not hide the one that failed', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/record/divergences': ALIGNMENT,
      '/api/sessions/meeting-1/record-path-transcript': TRANSCRIPTS,
    });
    render(<RecordingRoute />);

    expect(await screen.findByText('complete')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
  });

  it('attributes a divergence to the speaker the transcript recorded', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/record/divergences': ALIGNMENT,
      '/api/sessions/meeting-1/record-path-transcript': TRANSCRIPTS,
    });
    render(<RecordingRoute />);

    expect(await screen.findByText('Priya')).toBeInTheDocument();
  });

  it('says a speaker is unattributed rather than guessing one', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/record/divergences': ALIGNMENT,
      '/api/sessions/meeting-1/record-path-transcript': [
        { engine: 'engine-a', status: 'complete', segments: [] },
      ],
    });
    render(<RecordingRoute />);

    expect(await screen.findByText('Unattributed')).toBeInTheDocument();
  });

  it('does not claim the audio was destroyed when the attempt failed', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/record/divergences': ALIGNMENT,
      '/api/sessions/meeting-1/record-path-transcript': TRANSCRIPTS,
      '/api/sessions/meeting-1/audio-destruction': {
        status: 'failed',
        completed_at: '2026-08-20T10:00:00Z',
      },
    });
    render(<RecordingRoute />);

    await screen.findByText('“the TMS handoff”');
    expect(screen.queryByText('Destroyed')).not.toBeInTheDocument();
  });

  it('reports the destruction when it did complete', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/record/divergences': ALIGNMENT,
      '/api/sessions/meeting-1/record-path-transcript': TRANSCRIPTS,
      '/api/sessions/meeting-1/audio-destruction': {
        status: 'complete',
        completed_at: '2026-08-20T10:00:00Z',
      },
    });
    render(<RecordingRoute />);

    expect(await screen.findByText('Destroyed')).toBeInTheDocument();
  });

  it('renders an empty review for a meeting that was never transcribed', async () => {
    stubService(BASE);
    render(<RecordingRoute />);

    // A 404 on every source is content, not failure: this meeting has not
    // happened yet.
    expect(await screen.findByText('Where they disagreed')).toBeInTheDocument();
  });

  it('says nothing was compared rather than reporting nought per cent', async () => {
    /**
     * A live run photographed "Engines agreed 0%" beside "Needs a look 0" —
     * two engines that both finished, no disagreements between them, and a
     * headline saying they agreed about nothing. Both numbers were on screen
     * at once and they contradict each other.
     *
     * 100% would be the more flattering lie and 0% is the more alarming one;
     * neither is a measurement. Nothing was aligned, so there is nothing to
     * take a share of, and the honest answer is that it cannot be told yet —
     * which is what this journey already promises about the same measurement
     * made against real recordings.
     */
    stubService(BASE);
    render(<RecordingRoute />);

    await screen.findByText('Where they disagreed');
    expect(screen.queryByText('0%')).not.toBeInTheDocument();
    expect(screen.getByText(/not compared/i)).toBeInTheDocument();
  });

  it('tells an empty disagreement list apart from an uncompared one', async () => {
    // Same ambiguity as the headline number, one section down: a bare heading
    // with nothing under it reads as "they agreed on everything", which is the
    // conclusion an operator would act on and the one nothing here supports.
    stubService(BASE);
    render(<RecordingRoute />);

    await screen.findByText('Where they disagreed');
    expect(screen.getByText(/nothing has been compared/i)).toBeInTheDocument();
  });

  it('says so plainly when the engines were compared and agreed throughout', async () => {
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/record/divergences': {
        ...ALIGNMENT,
        spans: ALIGNMENT.spans.filter((span) => !span.is_divergent),
      },
      '/api/sessions/meeting-1/record-path-transcript': TRANSCRIPTS,
    });
    render(<RecordingRoute />);

    expect(await screen.findByText(/agreed everywhere they were compared/i)).toBeInTheDocument();
  });

  it('reports full agreement when the engines were compared and did not differ', async () => {
    // The case 0% was standing in for. Two engines that ran and matched is a
    // real result, and a different one from never having run.
    stubService({
      ...BASE,
      '/api/meetings/meeting-1/record/divergences': {
        ...ALIGNMENT,
        spans: ALIGNMENT.spans.filter((span) => !span.is_divergent),
      },
      '/api/sessions/meeting-1/record-path-transcript': TRANSCRIPTS,
    });
    render(<RecordingRoute />);

    expect(await screen.findByText('100%')).toBeInTheDocument();
  });

  it('takes the screen away when the service cannot be reached', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new TypeError('Failed to fetch');
      }),
    );
    render(<RecordingRoute />);

    expect(
      await screen.findByRole('heading', { name: 'Cannot reach the service' }),
    ).toBeInTheDocument();
  });
});
