import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { DebriefChatScreen } from '../route';
import { readableText, useDebriefChat } from '../useDebriefChat';

/**
 * The conversational half of debrief mode.
 *
 * These assert the things that would make the screen misleading rather than
 * merely ugly: a question that vanishes when sent, an answer that cannot be
 * told from the question, or a failure that looks like an empty answer.
 */

const BASE = {
  meetingTitle: 'Northwind Logistics — Discovery 2',
  turns: [],
  busy: false,
  error: null,
  started: true,
};

describe('asking a question', () => {
  it('sends what was typed and clears the box', async () => {
    const onAsk = vi.fn();
    render(<DebriefChatScreen {...BASE} onAsk={onAsk} />);

    const box = screen.getByLabelText(/Ask anything about what was said/);
    await userEvent.type(box, 'What did they say about March?');
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }));

    expect(onAsk).toHaveBeenCalledWith('What did they say about March?');
    expect(box).toHaveValue('');
  });

  it('will not send an empty or whitespace-only question', async () => {
    const onAsk = vi.fn();
    render(<DebriefChatScreen {...BASE} onAsk={onAsk} />);

    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled();
    await userEvent.type(screen.getByLabelText(/Ask anything/), '   ');
    expect(screen.getByRole('button', { name: 'Ask' })).toBeDisabled();
    expect(onAsk).not.toHaveBeenCalled();
  });

  it('says it is working rather than looking unresponsive', () => {
    // This half of the product is allowed to be slow; it is not allowed to be
    // silent about being slow.
    render(<DebriefChatScreen {...BASE} busy />);
    expect(screen.getByRole('button', { name: 'Thinking…' })).toBeDisabled();
  });
});

describe('the thread', () => {
  const turns = [
    { role: 'user' as const, text: 'What did they say about March?' },
    { role: 'assistant' as const, text: 'Priya said the pilot has to be live before March 31.' },
  ];

  it('attributes every turn to a named speaker', () => {
    render(<DebriefChatScreen {...BASE} turns={turns} />);

    expect(screen.getByText('You')).toBeInTheDocument();
    expect(screen.getByText('Elicta')).toBeInTheDocument();
    expect(screen.getByText(/pilot has to be live before March 31/)).toBeInTheDocument();
  });

  it('hides the openers once the thread has started', () => {
    render(<DebriefChatScreen {...BASE} turns={turns} />);
    expect(
      screen.queryByRole('button', { name: /Draft the follow-up paragraph/ }),
    ).not.toBeInTheDocument();
  });

  it('offers openers on an empty thread', async () => {
    const onAsk = vi.fn();
    render(<DebriefChatScreen {...BASE} onAsk={onAsk} />);

    await userEvent.click(screen.getByRole('button', { name: /Draft the follow-up paragraph/ }));
    expect(onAsk).toHaveBeenCalledWith('Draft the follow-up paragraph about integrations.');
  });
});

describe('before the conversation is open', () => {
  it('explains that answers are cited before asking for trust', () => {
    render(<DebriefChatScreen {...BASE} started={false} />);

    expect(screen.getByText(/cites the utterance it rests on/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start' })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Ask anything/)).not.toBeInTheDocument();
  });
});

describe('when the service is unreachable', () => {
  it('says so as an alert rather than showing an empty answer', () => {
    render(<DebriefChatScreen {...BASE} error="The debrief service answered 503." />);

    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('The debrief service answered 503.');
    expect(alert).toHaveTextContent('Nothing was lost');
  });
});

/**
 * The service is careful about this: an unconfigured engine answers 503
 * naming the setting that would fix it, and a rate-limited provider answers
 * 429 saying to wait rather than to go hunting for a broken deployment. A
 * client that renders the status number instead discards the whole of it.
 */
describe('when the service refuses', () => {
  function Probe() {
    const chat = useDebriefChat('meeting-1');
    return (
      <div>
        <span data-testid="error">{chat.error ?? ''}</span>
        <button type="button" onClick={() => void chat.start()}>
          open
        </button>
      </div>
    );
  }

  afterEach(() => vi.unstubAllGlobals());

  it('shows what the service said, not what number it said it with', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 429,
        json: async () => ({
          detail:
            'the debrief conversation (FR-7.3): the model provider is rate limiting this ' +
            'deployment. The same request should succeed shortly — this is a limit, not a fault.',
        }),
      })),
    );
    render(<Probe />);

    await userEvent.click(screen.getByRole('button', { name: 'open' }));

    await waitFor(() =>
      expect(screen.getByTestId('error')).toHaveTextContent('rate limiting this deployment'),
    );
  });

  it('falls back to the status when the refusal carries no explanation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 502,
        json: async () => {
          throw new SyntaxError('Unexpected token < in JSON');
        },
      })),
    );
    render(<Probe />);

    await userEvent.click(screen.getByRole('button', { name: 'open' }));

    await waitFor(() =>
      expect(screen.getByTestId('error')).toHaveTextContent('The debrief service answered 502.'),
    );
  });
});

describe('reading a message off the wire', () => {
  it('keeps only the text blocks and joins them', () => {
    // The wire carries a list of content blocks, not a string; a screen that
    // rendered the raw list would show JSON to the operator.
    expect(
      readableText([
        { type: 'text', text: 'Priya said ' },
        { type: 'thinking' },
        { type: 'text', text: 'the pilot ships in March.' },
      ]),
    ).toBe('Priya said the pilot ships in March.');
  });

  it('is empty when a message carries no text at all', () => {
    expect(readableText([{ type: 'thinking' }])).toBe('');
  });
});
