/**
 * Whether the desktop shell is around us.
 *
 * Its own module, and two lines, because two very different decisions turn on
 * it and one of them cannot import the other. Capture asks in order to choose
 * a backend — Rust normalises the audio in the shell, and the browser has to
 * read the samples itself. The service's address asks because a page served
 * from the shell's own protocol cannot reach the service with a relative path.
 */
export function shellAvailable(): boolean {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
}
