import { shellAvailable } from './shell';

/**
 * Why there is no service, when there is none.
 *
 * Asked for rather than listened for. The shell resolves this in `setup`,
 * before the page exists, so an event sent at that moment has no listener and
 * is simply lost; it keeps the reason and the page asks once it is running.
 *
 * The commonest reason is another copy of the app holding port 8000 — a
 * `.dmg` installed weeks ago, still on the port, serving an API the panel in
 * front of you does not match. The only account of that used to be a line on
 * a stderr nobody opening a `.dmg` will ever read, so what the operator saw
 * was every screen empty, which is indistinguishable from a product with
 * nothing in it.
 *
 * `null` means there is nothing wrong: either a service is running, or this
 * is a browser run where the question does not arise.
 */
export type Invoke = (command: string) => Promise<unknown>;

async function shellInvoke(command: string): Promise<unknown> {
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke(command);
}

export async function serviceFault(invoke: Invoke = shellInvoke): Promise<string | null> {
  if (invoke === shellInvoke && !shellAvailable()) return null;
  try {
    const reason = await invoke('service_fault');
    return typeof reason === 'string' && reason.length > 0 ? reason : null;
  } catch {
    // No shell, or a shell too old to answer. Neither is a fault worth
    // putting on screen — the screens' own "cannot reach the service" message
    // already covers a service that is simply absent.
    return null;
  }
}
