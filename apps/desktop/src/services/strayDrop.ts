/**
 * Refuses a file dropped anywhere that does not accept one.
 *
 * The webview's default for an unhandled drop is to navigate to the file. In
 * a browser that costs a refresh; in the packaged app it costs the window —
 * there is no address bar to type the app back into, and the operator is left
 * looking at a PDF where Elicta was.
 *
 * This could not happen until the window stopped intercepting OS drags.
 * Tauri's interception is what made the dropzone dead in the bundle, and
 * turning it off is what puts this default back within reach, so the guard
 * belongs with that change rather than after the first report of it.
 *
 * Listening on the bubble phase, not capture, is the whole of the design: an
 * element that wants the drop calls `preventDefault` in its own handler, the
 * event reaches here afterwards already claimed, and this leaves it alone. So
 * there is no list of drop targets to keep in step with the screens — a new
 * one works by handling its own event, which it had to do anyway.
 */
export function refuseStrayDrops(target: EventTarget = document): () => void {
  const refuse = (event: Event) => {
    // Claimed by something that wanted it. `dropEffect` and the upload are
    // that handler's business, not this one's.
    if (event.defaultPrevented) return;
    event.preventDefault();
  };

  // Both, because they are one behaviour: a `dragover` left unprevented tells
  // the browser this is not a drop target, and it then never fires `drop` at
  // all — so guarding the drop alone would guard an event that never arrives.
  target.addEventListener('dragover', refuse);
  target.addEventListener('drop', refuse);

  return () => {
    target.removeEventListener('dragover', refuse);
    target.removeEventListener('drop', refuse);
  };
}
