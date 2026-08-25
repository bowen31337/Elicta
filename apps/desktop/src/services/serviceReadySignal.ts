import { announceServiceReady } from './useResource';
import { shellAvailable } from './shell';

/**
 * Relays the shell's readiness announcement to the screens.
 *
 * The shell starts the service and brings the window up without waiting for
 * it — a frozen Python takes seconds to unpack, and blocking means no window
 * at all for that long. It emits `service://ready` when the service starts
 * answering; without something listening, the screens that were refused
 * during those seconds stay refused for the life of the window.
 *
 * Browser builds have nothing to subscribe to and need nothing: there the
 * service is already up, because you navigated to something it served.
 */
export async function listenForServiceReady(): Promise<void> {
  if (!shellAvailable()) return;
  try {
    const { listen } = await import('@tauri-apps/api/event');
    await listen('service://ready', () => {
      announceServiceReady();
    });
  } catch {
    // Nothing to do about it and nothing to say: the screens keep their own
    // reload, which is what an operator would reach for anyway.
  }
}
