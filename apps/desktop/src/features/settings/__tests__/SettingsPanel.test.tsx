import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { SettingsPanel } from '../SettingsPanel';
import type { SecretKey, ServiceSettings, UseSettingsResult } from '../useSettings';

const CONFIGURED: ServiceSettings = {
  inference: { model: 'claude-opus-5', base_url: null, auth_mode: 'api_key' },
  vendors: { asr_base_url: null, capture_base_url: null },
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

  it('distinguishes a configured credential from an unset one', () => {
    render(<SettingsPanel controller={controller()} />);

    expect(screen.getByText('A key is stored. Leave this blank to keep it.')).toBeInTheDocument();
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

  it('cannot test a credential that has not been configured', () => {
    render(<SettingsPanel controller={controller()} />);

    const [anthropicTest, asrTest] = screen.getAllByRole('button', { name: 'Test' });

    expect(anthropicTest).toBeEnabled();
    expect(asrTest).toBeDisabled();
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
    expect(screen.getByText('· in use')).toBeInTheDocument();
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

  it('offers a field for the token as well as the key', () => {
    render(<SettingsPanel controller={controller()} />);

    expect(screen.getByLabelText(/Anthropic OAuth token/)).toBeInTheDocument();
  });
});
