import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { SettingsPanel } from '../SettingsPanel';
import type { SecretKey, ServiceSettings, UseSettingsResult } from '../useSettings';

const CONFIGURED: ServiceSettings = {
  inference: {
    model: 'claude-opus-5',
    base_url: null,
    auth_mode: 'api_key',
    provider: 'anthropic',
    region: null,
    project_id: null,
    resource: null,
  },
  vendors: { asr_base_url: null, capture_base_url: null },
  connectors: {
  live_model: 'nova-3',
  local_asr_base_url: null,
    record_vendors: ['deepgram', 'assemblyai'],
    keyterm_prompting: true,
    disable_vendor_retention: true,
    region: null,
  },
  consent: { model: 'engagement_level' },
  secrets: [
    { key: 'anthropic_api_key', configured: true, hint: 'abcd' },
    { key: 'anthropic_oauth_token', configured: false, hint: null },
  ],
  speech: { credentials: [], policy: 'single', active_id: null },
  durable: true,
};

function controller(overrides: Partial<UseSettingsResult> = {}): UseSettingsResult {
  return {
    settings: CONFIGURED,
    loading: false,
    saving: false,
    error: null,
    save: vi.fn().mockResolvedValue(true),
    test: vi.fn().mockResolvedValue('Verified (…abcd).'),
    addSpeechKey: vi.fn().mockResolvedValue(null),
    setSpeechKeyEnabled: vi.fn().mockResolvedValue(null),
    removeSpeechKey: vi.fn().mockResolvedValue(null),
    testSpeechKey: vi.fn().mockResolvedValue('Verified (…8285).'),
    setSpeechPolicy: vi.fn().mockResolvedValue(null),
    ...overrides,
  };
}

/**
 * The screen shows one service at a time, so a test about the transcriber has
 * to open the transcriber's tab the way an operator would. Matched on a prefix
 * because a tab whose service is not set up carries "— needs attention" in its
 * accessible name.
 */
async function openTab(label: string) {
  await userEvent.click(screen.getByRole('tab', { name: new RegExp(`^${label}\\b`) }));
}

/** Two providers, so the list has to tell them apart. */
const WITH_SPEECH_KEYS: ServiceSettings = {
  ...CONFIGURED,
  speech: {
    policy: 'single',
    active_id: 'a',
    credentials: [
      { id: 'a', vendor: 'deepgram', label: 'Northwind', enabled: true },
      { id: 'b', vendor: 'assemblyai', label: 'spare', enabled: true },
    ],
  },
};

describe('SettingsPanel', () => {
  it('never prefills a secret input, because the service never returns one', () => {
    render(<SettingsPanel controller={controller()} />);

    const field = screen.getByLabelText('Anthropic API key') as HTMLInputElement;

    expect(field.value).toBe('');
    expect(field.type).toBe('password');
  });

  it('shows which key is stored without showing the key', () => {
    render(<SettingsPanel controller={controller()} />);

    const field = screen.getByLabelText('Anthropic API key');

    expect(field).toHaveAttribute('placeholder', 'Configured — ends abcd');
  });

  it('distinguishes a configured credential from an unset one', async () => {
    render(<SettingsPanel controller={controller()} />);

    expect(screen.getByText('A key is stored. Leave this blank to keep it.')).toBeInTheDocument();

    await openTab('Speech');

    expect(screen.getByText(/No key yet/)).toBeInTheDocument();
  });

  it('does not send a secret the operator did not type', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].secrets).toBeUndefined();
  });

  it('sends only the secret that was actually edited', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await userEvent.type(screen.getByLabelText('Anthropic API key'), 'sk-ant-new-key');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    const sent = save.mock.calls[0][0].secrets as { key: SecretKey; value: string }[];
    expect(sent).toEqual([{ key: 'anthropic_api_key', value: 'sk-ant-new-key' }]);
  });

  it('clears a credential only through the explicit clear action', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].secrets).toEqual([
      { key: 'anthropic_api_key', value: '' },
    ]);
  });

  it('offers no clear action for a credential that is not set', () => {
    render(<SettingsPanel controller={controller()} />);

    // One Clear button, for the one configured secret.
    expect(screen.getAllByRole('button', { name: 'Clear' })).toHaveLength(1);
  });

  it('cannot test a credential that has not been configured', async () => {
    render(<SettingsPanel controller={controller()} />);

    // Claude's key is stored in this fixture; the transcriber's is not, and
    // now lives a tab away rather than four fields down.
    expect(screen.getByRole('button', { name: 'Test' })).toBeEnabled();

    await openTab('Speech');

    // Not a disabled button: with an empty pool there is no key for one to
    // belong to. A Test button with nothing to test is a control that can
    // only ever disappoint.
    expect(screen.queryByRole('button', { name: 'Test' })).not.toBeInTheDocument();
  });

  it('reports the outcome of a credential test next to the field', async () => {
    const test = vi.fn().mockResolvedValue('AuthenticationError: invalid x-api-key');
    render(<SettingsPanel controller={controller({ test })} />);

    await userEvent.click(screen.getAllByRole('button', { name: 'Test' })[0]);

    expect(
      await screen.findByText('AuthenticationError: invalid x-api-key'),
    ).toBeInTheDocument();
  });

  it('warns when settings will not survive a restart', () => {
    render(
      <SettingsPanel
        controller={controller({ settings: { ...CONFIGURED, durable: false } })}
      />,
    );

    expect(
      screen.getByText(/will be lost when the service\s+restarts/),
    ).toBeInTheDocument();
  });

  it('stays quiet about durability when settings are durable', () => {
    render(<SettingsPanel controller={controller()} />);

    expect(screen.queryByText(/will be lost/)).not.toBeInTheDocument();
  });

  it('surfaces an unreachable service instead of appearing to have saved', () => {
    render(
      <SettingsPanel
        controller={controller({
          settings: null,
          error: 'The service is unreachable. Check that it is running.',
        })}
      />,
    );

    expect(screen.getByRole('alert')).toHaveTextContent('The service is unreachable');
  });

  it('lets the operator choose between a key and a token', () => {
    render(<SettingsPanel controller={controller()} />);

    expect(screen.getByRole('radio', { name: 'API key' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'OAuth token' })).not.toBeChecked();
  });

  it('marks which credential is actually in use', () => {
    render(<SettingsPanel controller={controller()} />);

    // The API-key field is labelled as in use; the token field is not.
    expect(screen.getByText('in use')).toBeInTheDocument();
  });

  it('follows the stored mode when the operator uses a token', () => {
    render(
      <SettingsPanel
        controller={controller({
          settings: {
            ...CONFIGURED,
            inference: { ...CONFIGURED.inference, auth_mode: 'oauth_token' },
          },
        })}
      />,
    );

    expect(screen.getByRole('radio', { name: 'OAuth token' })).toBeChecked();
  });

  it('saves the chosen auth mode alongside the model', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await userEvent.click(screen.getByRole('radio', { name: 'OAuth token' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].inference.auth_mode).toBe('oauth_token');
  });

  it('shows the credential for the chosen mode, and only that one', async () => {
    // Both fields at once was the confusion: a screen that says "use one or
    // the other" and then offers both, side by side, with a Test button each.
    render(<SettingsPanel controller={controller()} />);

    expect(screen.getByLabelText('Anthropic API key')).toBeInTheDocument();
    expect(screen.queryByLabelText('Anthropic OAuth token')).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole('radio', { name: 'OAuth token' }));

    expect(screen.getByLabelText('Anthropic OAuth token')).toBeInTheDocument();
    expect(screen.queryByLabelText('Anthropic API key')).not.toBeInTheDocument();
  });

  it('still admits to a stored credential it is no longer using', async () => {
    // Hiding the unselected field must not hide a secret the service holds:
    // a key nobody can see is a key nobody can revoke.
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await userEvent.click(screen.getByRole('radio', { name: 'OAuth token' }));

    expect(
      screen.getByText(/Anthropic API key is also stored \(ends abcd\), and is not in use/),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].secrets).toEqual([
      { key: 'anthropic_api_key', value: '' },
    ]);
  });

  it('asks for no Anthropic credential at all when the host supplies it', async () => {
    render(<SettingsPanel controller={controller()} />);

    await userEvent.selectOptions(screen.getByLabelText('Route Claude calls through'), 'bedrock');

    expect(screen.queryByLabelText('Anthropic API key')).not.toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: 'API key' })).not.toBeInTheDocument();
    // The stored key is still accounted for rather than silently orphaned.
    expect(screen.getByText(/Anthropic API key is also stored/)).toBeInTheDocument();
  });

  it('chooses how the pool serves, rather than which vendor does', async () => {
    // There is no live-vendor setting any more, and its absence is the point:
    // adding a credential *is* choosing a provider, so a separate dropdown
    // could only ever disagree with the pool. It did — a key labelled for one
    // vendor was probed against another.
    const setSpeechPolicy = vi.fn().mockResolvedValue(null);
    render(
      <SettingsPanel controller={controller({ settings: WITH_SPEECH_KEYS, setSpeechPolicy })} />,
    );

    await openTab('Speech');
    expect(screen.queryByLabelText('Live transcription')).not.toBeInTheDocument();

    await userEvent.selectOptions(
      screen.getByLabelText('When there is more than one'),
      'rotate',
    );

    await waitFor(() => expect(setSpeechPolicy).toHaveBeenCalledWith('rotate'));
  });

  it('shows the two recording engines that cross-check each other', async () => {
    render(<SettingsPanel controller={controller()} />);

    await openTab('Speech');

    expect(screen.getByText('Deepgram + AssemblyAI')).toBeInTheDocument();
  });

  it('defaults to sending vocabulary and opting out of vendor retention', async () => {
    render(<SettingsPanel controller={controller()} />);

    await openTab('Speech');

    expect(
      screen.getByLabelText('Send engagement vocabulary to the transcriber'),
    ).toBeChecked();
    expect(
      screen.getByLabelText('Tell vendors not to retain client audio'),
    ).toBeChecked();
  });

  it('saves a retention opt-out that the operator turns off', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await openTab('Speech');
    await userEvent.click(
      screen.getByLabelText('Tell vendors not to retain client audio'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].connectors.disable_vendor_retention).toBe(false);
  });

  it('saves a pinned region', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await openTab('Speech');
    await userEvent.type(screen.getByLabelText('Speech region'), 'eu');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].connectors.region).toBe('eu');
  });

  it('offers only Anthropic-compatible providers', () => {
    render(<SettingsPanel controller={controller()} />);

    const options = Array.from(
      (screen.getByLabelText('Route Claude calls through') as HTMLSelectElement).options,
    ).map((option) => option.value);

    expect(options).toEqual([
      'anthropic',
      'bedrock',
      'vertex',
      'foundry',
      'anthropic_compatible',
    ]);
    expect(options).not.toContain('openai');
  });

  it('asks for an endpoint only when a compatible gateway is chosen', async () => {
    render(<SettingsPanel controller={controller()} />);

    expect(screen.queryByLabelText('Endpoint')).not.toBeInTheDocument();

    await userEvent.selectOptions(
      screen.getByLabelText('Route Claude calls through'),
      'anthropic_compatible',
    );

    expect(screen.getByLabelText('Endpoint')).toBeInTheDocument();
  });

  it('asks Vertex for a project and a region, and nothing else for it', async () => {
    render(<SettingsPanel controller={controller()} />);

    await userEvent.selectOptions(
      screen.getByLabelText('Route Claude calls through'),
      'vertex',
    );

    expect(screen.getByLabelText('Google Cloud project')).toBeInTheDocument();
    expect(screen.getByLabelText('AI provider region')).toBeInTheDocument();
    expect(screen.queryByLabelText('Endpoint')).not.toBeInTheDocument();
  });

  it("says plainly when a provider uses the host's own credentials", async () => {
    render(<SettingsPanel controller={controller()} />);

    await userEvent.selectOptions(
      screen.getByLabelText('Route Claude calls through'),
      'bedrock',
    );

    expect(screen.getByText(/no key needed here/)).toBeInTheDocument();
  });

  it('saves the chosen provider and its settings together', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await userEvent.selectOptions(
      screen.getByLabelText('Route Claude calls through'),
      'anthropic_compatible',
    );
    await userEvent.type(screen.getByLabelText('Endpoint'), 'https://llm.internal');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].inference.provider).toBe('anthropic_compatible');
    expect(save.mock.calls[0][0].inference.base_url).toBe('https://llm.internal');
  });

  it('lets the operator bring a speech service we do not ship support for', async () => {
    render(
      <SettingsPanel
        controller={controller({
          settings: {
            ...CONFIGURED,
            speech: {
              policy: 'single',
              active_id: null,
              credentials: [
                { id: 'x', vendor: 'custom', label: 'in-house', enabled: true },
              ],
            },
          },
        })}
      />,
    );

    await openTab('Speech');

    // The endpoint field follows the pool: holding a key for a service we do
    // not ship support for is what makes "where do we reach it?" a question.
    expect(screen.getByLabelText('Custom speech service endpoint')).toBeInTheDocument();
  });
});

/**
 * Grouping by service.
 *
 * The screen used to list four credentials together under one "Authenticate
 * with" switch that governed two of them. These assert the fix: a credential
 * appears with the service it authenticates, named after that service, and
 * each section says whether it is ready without the operator opening a single
 * password field.
 */
describe('reading the screen at a glance', () => {
  it('says whether each service is set up', async () => {
    render(<SettingsPanel controller={controller()} />);

    expect(
      within(screen.getByRole('region', { name: 'Claude' })).getByText('Ready'),
    ).toBeInTheDocument();

    await openTab('Speech');

    expect(
      within(screen.getByRole('region', { name: 'Speech to text' })).getByText('Needs a key'),
    ).toBeInTheDocument();
  });

  it('puts each credential in the section for the thing it authenticates', async () => {
    render(<SettingsPanel controller={controller()} />);

    const claude = screen.getByRole('region', { name: 'Claude' });
    expect(within(claude).getByLabelText('Anthropic API key')).toBeInTheDocument();
    expect(within(claude).queryByLabelText(/AssemblyAI/)).not.toBeInTheDocument();

    await openTab('Speech');

    const speech = screen.getByRole('region', { name: 'Speech to text' });
    expect(within(speech).getByLabelText('Add a speech key')).toBeInTheDocument();
    expect(screen.queryByLabelText('Anthropic API key')).not.toBeInTheDocument();
  });

  it('names each key by the provider that issued it', async () => {
    // "Speech-to-text vendor key" named a category. An operator has a tab open
    // on a provider's console, and that is the name they are looking for.
    render(<SettingsPanel controller={controller({ settings: WITH_SPEECH_KEYS })} />);

    await openTab('Speech');

    const rows = screen.getAllByRole('listitem');
    expect(within(rows[0]).getByText('Deepgram')).toBeInTheDocument();
    expect(within(rows[1]).getByText('AssemblyAI')).toBeInTheDocument();
    expect(within(rows[0]).getByText('Northwind')).toBeInTheDocument();
  });

  it('tests the key that was asked about, and no other', async () => {
    // The single field this replaced was probed against whichever vendor the
    // service had *saved*, so changing the dropdown above it produced
    // "Deepgram rejected the credential (401)" underneath a field labelled
    // "AssemblyAI key" -- an answer to a question nobody asked. A pooled key
    // carries its own provider, so the only thing left to get wrong is which
    // row the verdict lands in.
    const testSpeechKey = vi.fn().mockResolvedValue('AssemblyAI rejected the key (401)');
    render(
      <SettingsPanel controller={controller({ settings: WITH_SPEECH_KEYS, testSpeechKey })} />,
    );

    await openTab('Speech');
    const rows = screen.getAllByRole('listitem');
    await userEvent.click(within(rows[1]).getByRole('button', { name: 'Test' }));

    expect(testSpeechKey).toHaveBeenCalledWith('b');
    expect(within(rows[1]).getByText('AssemblyAI rejected the key (401)')).toBeInTheDocument();
    expect(
      within(rows[0]).queryByText('AssemblyAI rejected the key (401)'),
    ).not.toBeInTheDocument();
  });

  it('keeps saying what a key is doing after it has been tested', async () => {
    // The verdict used to replace the status line rather than join it, so a
    // tested key stopped saying what it was for — and kept showing a stale
    // verdict after being taken out of service, which is the state that
    // matters most to see.
    const testSpeechKey = vi.fn().mockResolvedValue('Deepgram rejected the key (401)');
    const setSpeechKeyEnabled = vi.fn().mockResolvedValue(null);
    render(
      <SettingsPanel
        controller={controller({
          settings: WITH_SPEECH_KEYS,
          testSpeechKey,
          setSpeechKeyEnabled,
        })}
      />,
    );

    await openTab('Speech');
    const row = screen.getAllByRole('listitem')[0];
    await userEvent.click(within(row).getByRole('button', { name: 'Test' }));

    expect(await within(row).findByText(/rejected the key/)).toBeInTheDocument();
    expect(within(row).getByText(/Serving the nudges/)).toBeInTheDocument();

    await userEvent.click(within(row).getByRole('button', { name: 'Take out of service' }));

    // The verdict was about a key that was in service. It is not an answer
    // about this row any more.
    await waitFor(() =>
      expect(within(row).queryByText(/rejected the key/)).not.toBeInTheDocument(),
    );
  });

  it('has no unsaved speech key for a test to answer about', async () => {
    // Two guards used to live here, both about the same gap: a test asks the
    // service about the key it has *stored*, and the single field could be
    // renamed to another vendor or refilled with another key without the
    // service being told. A pooled key is stored the moment it is added and
    // carries its own provider, so neither half of that gap is reachable —
    // and the "Save first" warnings that papered over it are gone with it.
    render(<SettingsPanel controller={controller({ settings: WITH_SPEECH_KEYS })} />);

    await openTab('Speech');

    expect(screen.queryByText(/Save first/)).not.toBeInTheDocument();
    for (const button of screen.getAllByRole('button', { name: 'Test' })) {
      expect(button).toBeEnabled();
    }
  });

  it('calls meeting capture optional, because it is', async () => {
    render(
      <SettingsPanel
        controller={controller({
          settings: {
            ...CONFIGURED,
            secrets: [
              ...CONFIGURED.secrets,
              { key: 'capture_vendor_api_key', configured: false, hint: null },
            ],
          },
        })}
      />,
    );

    await openTab('Recording');

    const capture = screen.getByRole('region', { name: 'Meeting capture' });
    expect(within(capture).getByText('Optional')).toBeInTheDocument();
  });

  it('says there are unsaved changes rather than leaving the operator to remember', async () => {
    render(<SettingsPanel controller={controller()} />);

    expect(screen.queryByText('Unsaved changes')).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText('Model'), 'x');

    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
  });
});

/**
 * The tab bar.
 *
 * Splitting the screen into five is only an improvement if nothing is lost by
 * hiding four of them. Two things could be: a service that needs setting up
 * can no longer announce itself from its own badge, and an edit made on one
 * tab could go missing when the operator moves to another. These assert that
 * neither does.
 */
describe('the tab bar', () => {
  it('shows one service at a time', () => {
    render(<SettingsPanel controller={controller()} />);

    expect(screen.getAllByRole('tabpanel')).toHaveLength(1);
    expect(screen.getByRole('region', { name: 'Claude' })).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Speech to text' })).not.toBeInTheDocument();
  });

  it('says from the bar which service still needs setting up', () => {
    // The fixture has Claude's key and not the transcriber's. Read from the
    // tab, this is the whole answer to "what is left to do?" without opening
    // anything.
    render(<SettingsPanel controller={controller()} />);

    expect(screen.getByRole('tab', { name: /^Speech/ })).toHaveAccessibleName(
      'Speech — needs attention',
    );
    expect(screen.getByRole('tab', { name: /^Claude/ })).toHaveAccessibleName('Claude');
  });

  it('stops flagging a tab once its credential is stored', () => {
    render(
      <SettingsPanel
        controller={controller({
          settings: {
            ...CONFIGURED,
            speech: {
              policy: 'single',
              active_id: null,
              credentials: [
                { id: 'a', vendor: 'deepgram', label: 'Northwind', enabled: true },
              ],
            },
          },
        })}
      />,
    );

    expect(screen.getByRole('tab', { name: /^Speech/ })).toHaveAccessibleName('Speech');
  });

  it('keeps an edit made on a tab the operator has since left', async () => {
    // Every draft lives in the panel rather than in the inputs, which is what
    // makes unmounting the hidden tabs safe. One Save writes both edits.
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await userEvent.type(screen.getByLabelText('Model'), '-x');
    await openTab('Speech');
    await userEvent.type(screen.getByLabelText('Speech region'), 'eu');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].inference.model).toBe('claude-opus-5-x');
    expect(save.mock.calls[0][0].connectors.region).toBe('eu');
  });

  it('still says there are unsaved changes from a tab that has none', async () => {
    render(<SettingsPanel controller={controller()} />);

    await userEvent.type(screen.getByLabelText('Model'), 'x');
    await openTab('Storage');

    expect(screen.getByText('Unsaved changes')).toBeInTheDocument();
  });

  it('moves between tabs with the arrow keys', async () => {
    render(<SettingsPanel controller={controller()} />);

    screen.getByRole('tab', { name: /^Claude/ }).focus();
    await userEvent.keyboard('{ArrowRight}');

    expect(screen.getByRole('tab', { name: /^Speech/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(screen.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'speech-tab');
  });

  it('wraps round rather than stopping at the ends', async () => {
    render(<SettingsPanel controller={controller()} />);

    screen.getByRole('tab', { name: /^Claude/ }).focus();
    await userEvent.keyboard('{ArrowLeft}');

    expect(screen.getByRole('tab', { name: /^Storage/ })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('is one stop on the Tab key rather than five', () => {
    // A roving tabindex. Without it, reaching the first field would mean
    // tabbing past every tab on the bar.
    render(<SettingsPanel controller={controller()} />);

    const reachable = screen
      .getAllByRole('tab')
      .filter((tab) => tab.getAttribute('tabindex') === '0');

    expect(reachable).toHaveLength(1);
    expect(reachable[0]).toHaveAttribute('aria-selected', 'true');
  });
});

describe('the Microsoft 365 document connector', () => {
  /**
   * Reading a linked SharePoint or OneDrive document needs an app registration.
   * Without somewhere to enter it, the only way to configure it is an
   * environment variable — and journey 1 tells the operator to do it in
   * Settings, which would be a screen that does not exist.
   */
  const WITH_DOCUMENTS: ServiceSettings = {
    ...CONFIGURED,
    documents: { tenant_id: null, client_id: null },
    secrets: [
      ...CONFIGURED.secrets,
      { key: 'microsoft_graph_client_secret', configured: false, hint: null },
    ],
  } as ServiceSettings;

  function documentsController(overrides: Partial<UseSettingsResult> = {}) {
    return controller({ settings: WITH_DOCUMENTS, ...overrides });
  }

  it('offers the tenant and the app registration', async () => {
    render(<SettingsPanel controller={documentsController()} />);

    await openTab('Documents');

    expect(screen.getByLabelText(/directory \(tenant\) id/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/application \(client\) id/i)).toBeInTheDocument();
  });

  it('keeps the client secret write-only, like every other secret here', async () => {
    render(<SettingsPanel controller={documentsController()} />);

    await openTab('Documents');

    const field = screen.getByLabelText(/client secret/i) as HTMLInputElement;

    expect(field.value).toBe('');
    expect(field.type).toBe('password');
  });

  it('saves what was typed into the connector', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={documentsController({ save })} />);

    await openTab('Documents');
    await userEvent.type(screen.getByLabelText(/directory \(tenant\) id/i), 'tenant-1');
    await userEvent.type(screen.getByLabelText(/application \(client\) id/i), 'client-1');
    await userEvent.type(screen.getByLabelText(/client secret/i), 'shhh');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    const draft = save.mock.calls[0][0];
    expect(draft.documents).toEqual({ tenant_id: 'tenant-1', client_id: 'client-1' });
    expect(draft.secrets).toContainEqual({
      key: 'microsoft_graph_client_secret',
      value: 'shhh',
    });
  });

  it('says plainly that uploading needs none of this', async () => {
    render(<SettingsPanel controller={documentsController()} />);

    await openTab('Documents');

    expect(screen.getByText(/dropp?ing a file|uploaded|upload/i)).toBeInTheDocument();
  });
});

describe('where the data is kept', () => {
  /**
   * SQLite by default; anything else is opted into here. The URL carries a
   * password, so it is a secret like the others and what comes back has the
   * password removed.
   */
  const WITH_STORAGE: ServiceSettings = {
    ...CONFIGURED,
    storage: {
      database: 'sqlite:////home/ubuntu/.elicta/state.db',
      applies_on_restart: true,
    },
    secrets: [
      ...CONFIGURED.secrets,
      { key: 'state_database_url', configured: false, hint: null },
    ],
  } as ServiceSettings;

  function storageController(overrides: Partial<UseSettingsResult> = {}) {
    return controller({ settings: WITH_STORAGE, ...overrides });
  }

  it('says which database the data is in', async () => {
    render(<SettingsPanel controller={storageController()} />);

    await openTab('Storage');

    expect(screen.getByText(/sqlite:\/\/\/\/home\/ubuntu\/\.elicta\/state\.db/)).toBeInTheDocument();
  });

  it('keeps the connection URL write-only, because it carries a password', async () => {
    render(<SettingsPanel controller={storageController()} />);

    await openTab('Storage');

    const field = screen.getByLabelText(/database connection url/i) as HTMLInputElement;

    expect(field.value).toBe('');
    expect(field.type).toBe('password');
  });

  it('says a restart is needed rather than implying the move is immediate', async () => {
    render(<SettingsPanel controller={storageController()} />);

    await openTab('Storage');

    expect(screen.getByText(/restart/i)).toBeInTheDocument();
  });

  it('saves the url as a secret', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={storageController({ save })} />);

    await openTab('Storage');
    await userEvent.type(
      screen.getByLabelText(/database connection url/i),
      'postgresql://elicta:pw@db.internal/elicta',
    );
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].secrets).toContainEqual({
      key: 'state_database_url',
      value: 'postgresql://elicta:pw@db.internal/elicta',
    });
  });
});

describe('the storage badge', () => {
  /**
   * A badge is read before the words under it, so it must not assert something
   * it does not know. With no storage reported, "External database" told every
   * reader — and every documentation screenshot — that a default install keeps
   * its data on a server somewhere. It does not.
   */
  function withStorage(database: string | undefined): UseSettingsResult {
    const settings = {
      ...CONFIGURED,
      ...(database === undefined ? {} : { storage: { database, applies_on_restart: true } }),
      secrets: [
        ...CONFIGURED.secrets,
        { key: 'state_database_url', configured: false, hint: null },
      ],
    } as ServiceSettings;
    return controller({ settings });
  }

  it('says the data is on this machine when it is a local file', async () => {
    render(<SettingsPanel controller={withStorage('sqlite:////home/x/.elicta/state.db')} />);

    await openTab('Storage');

    expect(screen.getByText('On this machine')).toBeInTheDocument();
  });

  it('says external only when it really is external', async () => {
    render(<SettingsPanel controller={withStorage('postgresql://elicta@db/elicta')} />);

    await openTab('Storage');

    expect(screen.getByText('External database')).toBeInTheDocument();
  });

  it('falls back to a file on this machine, which is the default', async () => {
    // Not "unknown": a deployment that has not been pointed anywhere keeps its
    // data in a local file, so that is what an unreported storage means. The
    // badge saying "External database" told every reader the opposite.
    render(<SettingsPanel controller={withStorage(undefined)} />);

    await openTab('Storage');

    expect(screen.getByText('On this machine')).toBeInTheDocument();
    expect(screen.queryByText('External database')).not.toBeInTheDocument();
  });

  it('names the default in words rather than inventing a path for it', async () => {
    render(<SettingsPanel controller={withStorage(undefined)} />);

    await openTab('Storage');

    expect(screen.getByText(/a file on this machine/i)).toBeInTheDocument();
  });
});

describe('the consent model', () => {
  /**
   * This was a constant in the service whose own docstring called it "the
   * fail-open one": every engagement took engagement-level consent, no
   * meeting ever stopped to ask, and the only way to change it was to edit
   * Python. The default is unchanged — what this screen adds is that the
   * person accountable for the choice can see it and reverse it.
   */
  it('shows which consent model is in force', async () => {
    render(<SettingsPanel controller={controller()} />);

    await openTab('Recording');

    const chosen = screen.getByRole('radio', { name: /standing for the engagement/i });
    expect(chosen).toBeChecked();
  });

  it('says plainly that nobody is prompted under the standing model', async () => {
    render(<SettingsPanel controller={controller()} />);

    await openTab('Recording');

    // A screen that offered this as two unexplained words would be asking an
    // operator to pick a legal posture from a label.
    expect(screen.getByText(/no consent record is written/i)).toBeInTheDocument();
  });

  it('saves a switch to asking before every meeting', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await openTab('Recording');
    await userEvent.click(screen.getByRole('radio', { name: /ask before every meeting/i }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].consent.model).toBe('per_meeting');
  });

  it('follows the stored model when the service already asks per meeting', async () => {
    render(
      <SettingsPanel
        controller={controller({
          settings: { ...CONFIGURED, consent: { model: 'per_meeting' } },
        })}
      />,
    );

    await openTab('Recording');

    expect(screen.getByRole('radio', { name: /ask before every meeting/i })).toBeChecked();
  });
});

describe('choosing what listens during the meeting', () => {
  /**
   * The model was a keyword-argument default in a Python signature fixed at
   * `nova-3` — a choice that existed and that no operator could reach. What
   * these cover is the two things a dropdown can quietly get wrong: offering
   * a setting whose consequence is hidden, and revealing a dependent control
   * only in a state no fixture ever renders.
   */
  const withModel = (live_model: string, local_asr_base_url: string | null = null) =>
    controller({
      settings: {
        ...CONFIGURED,
        connectors: { ...CONFIGURED.connectors, live_model, local_asr_base_url },
      },
    } as Partial<UseSettingsResult>);

  it('groups the models by how they are driven, not just by where they run', async () => {
    // The grouping is the explanation. Streamed versus windowed is the choice
    // that decides how long an operator waits — the model itself was measured
    // at about four per cent of the delay — and it is invisible from the
    // model names alone.
    render(<SettingsPanel controller={withModel('nova-3')} />);
    await openTab('Speech');

    const select = screen.getByLabelText('Live transcription model');

    expect(
      within(select).getByRole('group', { name: 'Streamed, ends on turns' }),
    ).toBeInTheDocument();
    expect(
      within(select).getByRole('group', { name: /one fixed window at a time/i }),
    ).toBeInTheDocument();
    expect(within(select).getByRole('group', { name: 'On this machine' })).toBeInTheDocument();
  });

  it('warns that a windowed model waits for its slice to fill', async () => {
    render(<SettingsPanel controller={withModel('nova-3')} />);
    await openTab('Speech');

    expect(screen.getByText(/arrives as two halves/i)).toBeInTheDocument();
  });

  it('says a streamed model ends sentences where the speaker does', async () => {
    render(<SettingsPanel controller={withModel('flux-general-en')} />);
    await openTab('Speech');

    expect(screen.getByText(/sentences arrive whole/i)).toBeInTheDocument();
    expect(screen.queryByText(/arrives as two halves/i)).toBeNull();
  });

  it('says the vocabulary is not sent on a model that cannot take it', async () => {
    // `keyterm` is Nova-3 only. The service already drops the parameter
    // rather than sending it to be ignored, and an operator with the
    // vocabulary switch still on has every reason to believe it applies —
    // a silently-inert setting is worse than one that is off.
    render(<SettingsPanel controller={withModel('nova-2')} />);
    await openTab('Speech');

    expect(screen.getByText(/vocabulary is not sent on this model/i)).toBeInTheDocument();
  });

  it('says nothing of the sort on the model that does take it', async () => {
    render(<SettingsPanel controller={withModel('nova-3')} />);
    await openTab('Speech');

    expect(screen.queryByText(/vocabulary is not sent/i)).not.toBeInTheDocument();
  });

  it('asks for a server address only where one is needed', async () => {
    render(<SettingsPanel controller={withModel('nova-3')} />);
    await openTab('Speech');

    expect(screen.queryByLabelText('Local transcription server')).not.toBeInTheDocument();
  });

  it('asks for a server address as soon as a local model is chosen', async () => {
    // Elicta does not run the model. A local option with nowhere to send the
    // audio is a setting that reports itself configured and transcribes
    // nothing — which the panel would show as a working lane.
    render(<SettingsPanel controller={withModel('whisper-small')} />);
    await openTab('Speech');

    expect(screen.getByLabelText('Local transcription server')).toBeInTheDocument();
    expect(screen.getByText(/no audio leaves this machine/i)).toBeInTheDocument();
  });

  it('takes the choice and reveals what that choice now needs', async () => {
    // Picking a local model without being asked for a server is a setting
    // that reports itself configured and transcribes nothing — so the
    // address field appearing *is* the behaviour, not decoration around it.
    render(<SettingsPanel controller={withModel('nova-3')} />);
    await openTab('Speech');
    expect(screen.queryByLabelText('Local transcription server')).not.toBeInTheDocument();

    await userEvent.selectOptions(
      screen.getByLabelText('Live transcription model'),
      'parakeet-tdt-0.6b-v2',
    );

    expect(screen.getByLabelText('Live transcription model')).toHaveValue(
      'parakeet-tdt-0.6b-v2',
    );
    expect(screen.getByLabelText('Local transcription server')).toBeInTheDocument();
  });
});
