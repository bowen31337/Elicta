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
    live_vendor: 'assemblyai',
    record_vendors: ['deepgram', 'assemblyai'],
    keyterm_prompting: true,
    disable_vendor_retention: true,
    region: null,
  },
  consent: { model: 'engagement_level' },
  secrets: [
    { key: 'anthropic_api_key', configured: true, hint: 'abcd' },
    { key: 'anthropic_oauth_token', configured: false, hint: null },
    { key: 'asr_vendor_api_key', configured: false, hint: null },
  ],
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

    expect(screen.getByText('No key is stored yet.')).toBeInTheDocument();
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

    expect(screen.getByRole('button', { name: 'Test' })).toBeDisabled();
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

  it('lets the operator choose the live transcription vendor', async () => {
    const save = vi.fn().mockResolvedValue(true);
    render(<SettingsPanel controller={controller({ save })} />);

    await openTab('Speech');
    await userEvent.selectOptions(
      screen.getByLabelText('Live transcription'),
      'deepgram',
    );
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0][0].connectors.live_vendor).toBe('deepgram');
  });

  it('explains the live vendor choice in the operator\'s terms', async () => {
    render(<SettingsPanel controller={controller()} />);

    await openTab('Speech');

    expect(
      screen.getByText(/Ends a turn when the sentence sounds finished/),
    ).toBeInTheDocument();
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
    render(<SettingsPanel controller={controller()} />);

    await openTab('Speech');
    await userEvent.selectOptions(screen.getByLabelText('Live transcription'), 'custom');

    expect(
      screen.getByLabelText('Custom speech service endpoint'),
    ).toBeInTheDocument();
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
    expect(within(speech).getByLabelText('AssemblyAI key')).toBeInTheDocument();
    expect(screen.queryByLabelText('Anthropic API key')).not.toBeInTheDocument();
  });

  it('names the speech key after the vendor that issues it', async () => {
    // "Speech-to-text vendor key" named a category. An operator has a tab open
    // on a vendor's console, and that is the name they are looking for.
    render(<SettingsPanel controller={controller()} />);

    await openTab('Speech');

    expect(screen.getByLabelText('AssemblyAI key')).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText('Live transcription'), 'deepgram');

    expect(screen.getByLabelText('Deepgram key')).toBeInTheDocument();
  });

  /**
   * A speech key that the service already holds, so the Test button is live.
   * The bug this guards needs both halves: a testable key, and a vendor the
   * operator can change out from under it.
   */
  const WITH_SPEECH_KEY: ServiceSettings = {
    ...CONFIGURED,
    secrets: CONFIGURED.secrets.map((secret) =>
      secret.key === 'asr_vendor_api_key'
        ? { ...secret, configured: true, hint: '8285' }
        : secret,
    ),
  };

  it('will not test a speech key against a vendor the service has not been told about', async () => {
    // The field is renamed the moment the dropdown changes, but the service
    // probes whichever vendor it has *saved*. Testing across that gap answered
    // "Deepgram rejected the credential (401)" underneath a field labelled
    // "AssemblyAI key" -- an answer about a question the operator never asked.
    const test = vi.fn().mockResolvedValue('Deepgram rejected the credential (401)');
    render(<SettingsPanel controller={controller({ settings: WITH_SPEECH_KEY, test })} />);

    await openTab('Speech');
    expect(screen.getByRole('button', { name: 'Test' })).toBeEnabled();

    await userEvent.selectOptions(screen.getByLabelText('Live transcription'), 'deepgram');

    expect(screen.getByLabelText('Deepgram key')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Test' })).toBeDisabled();
    expect(test).not.toHaveBeenCalled();
  });

  it('says why a speech key cannot be tested yet, rather than greying out silently', async () => {
    render(<SettingsPanel controller={controller({ settings: WITH_SPEECH_KEY })} />);

    await openTab('Speech');
    await userEvent.selectOptions(screen.getByLabelText('Live transcription'), 'deepgram');

    expect(
      screen.getByText(/Save first .* still set up for AssemblyAI/),
    ).toBeInTheDocument();
  });

  it('will not test a stored key while an unsaved one is in the box', async () => {
    // A test checks the key the service holds. With a new key typed in and not
    // saved, a verdict about the old one reads as a verdict about the new one.
    const test = vi.fn();
    render(<SettingsPanel controller={controller({ settings: WITH_SPEECH_KEY, test })} />);

    await openTab('Speech');
    await userEvent.type(screen.getByLabelText('AssemblyAI key'), 'a-new-key');

    expect(screen.getByRole('button', { name: 'Test' })).toBeDisabled();
    expect(screen.getByText(/Save first .* the key it has stored/)).toBeInTheDocument();
    expect(test).not.toHaveBeenCalled();
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
            secrets: CONFIGURED.secrets.map((secret) =>
              secret.key === 'asr_vendor_api_key'
                ? { ...secret, configured: true, hint: 'wxyz' }
                : secret,
            ),
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
