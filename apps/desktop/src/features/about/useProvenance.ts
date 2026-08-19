import { useEffect, useState } from 'react';

import { shellAvailable } from '../capture/useCapture';

/**
 * What the desktop shell can find out about this build from the OS.
 *
 * The About screen used to render whatever it was handed, which meant a build
 * that had lost its signature would go on claiming to be signed. These values
 * come from `codesign` / `Get-AuthenticodeSignature` and the platform's
 * management state instead.
 *
 * `null` means "not established" throughout, and the screen renders it
 * distinctly from `false`. An IT reviewer told "unsigned" makes a different
 * decision from one told "we could not check", so the two must not collapse.
 */
export interface SigningStatus {
  readonly signed: boolean | null;
  readonly signedBy: string | null;
  readonly source: string;
}

export interface InstallStatus {
  readonly managed: boolean | null;
  readonly source: string;
}

export interface UpdateStatus {
  readonly available: boolean;
  readonly version: string | null;
  readonly notes: string | null;
  readonly error: string | null;
}

export interface Provenance {
  readonly signing: SigningStatus | null;
  readonly install: InstallStatus | null;
  readonly update: UpdateStatus | null;
}

async function callShell<T>(command: string): Promise<T | null> {
  if (!shellAvailable()) return null;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    return await invoke<T>(command);
  } catch {
    return null;
  }
}

export function useProvenance(): Provenance {
  const [provenance, setProvenance] = useState<Provenance>({
    signing: null,
    install: null,
    update: null,
  });

  useEffect(() => {
    let live = true;
    void (async () => {
      // The update check crosses the network and the other two do not, so
      // they are issued together rather than in sequence — otherwise the
      // signing row waits on a release host that may not answer at all.
      const [signing, install, update] = await Promise.all([
        callShell<SigningStatus>('signing_status'),
        callShell<InstallStatus>('install_status'),
        callShell<UpdateStatus>('check_for_update'),
      ]);
      if (live) setProvenance({ signing, install, update });
    })();
    return () => {
      live = false;
    };
  }, []);

  return provenance;
}

/** The one-line summary the About screen shows for the update channel. */
export function updateChannelSummary(update: UpdateStatus | null): string {
  if (update === null) return 'Update status is only available in the desktop app.';
  if (update.error !== null) return update.error;
  if (update.available) {
    return `Version ${update.version} is available. It installs when you choose, never mid-meeting.`;
  }
  return 'This is the current version. Elicta checks on launch and never updates itself unasked.';
}
