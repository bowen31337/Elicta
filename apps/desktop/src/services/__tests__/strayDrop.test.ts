import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { refuseStrayDrops } from '../strayDrop';

/**
 * A file dropped anywhere but the dropzone.
 *
 * The webview's default for that is to *navigate to the file*, which in a
 * browser costs a refresh and in the packaged app costs the window: there is
 * no address bar to type the app's URL back into, and the operator is left
 * looking at a PDF where Elicta was.
 *
 * It could not happen until now. Tauri intercepted OS drags before they
 * reached the page, so a miss did nothing; turning that off to make the
 * dropzone work is what puts the default back in reach. The guard ships with
 * the change that needs it.
 */
describe('a document dropped where nothing accepts it', () => {
  let stop: () => void;

  beforeEach(() => {
    stop = refuseStrayDrops();
  });
  afterEach(() => {
    stop();
    vi.restoreAllMocks();
  });

  function fire(type: 'dragover' | 'drop', target: EventTarget = document.body) {
    const event = new Event(type, { bubbles: true, cancelable: true });
    target.dispatchEvent(event);
    return event;
  }

  it('is refused rather than opened', () => {
    expect(fire('drop').defaultPrevented).toBe(true);
  });

  it('refuses the drag before the drop, or the drop never arrives', () => {
    // A dragover that is not prevented means the browser has already decided
    // this is not a drop target, and the drop event does not fire at all.
    expect(fire('dragover').defaultPrevented).toBe(true);
  });

  it('leaves a real drop target alone', () => {
    const zone = document.createElement('div');
    zone.dataset.dropzone = 'true';
    document.body.appendChild(zone);

    // The zone's own handler calls preventDefault and does the upload; the
    // guard must not claim the event on its way past.
    const event = new Event('drop', { bubbles: true, cancelable: true });
    let sawItFirst = false;
    zone.addEventListener('drop', () => {
      sawItFirst = !event.defaultPrevented;
    });
    zone.dispatchEvent(event);

    expect(sawItFirst).toBe(true);
    zone.remove();
  });

  it('stops guarding when it is torn down', () => {
    stop();

    expect(fire('drop').defaultPrevented).toBe(false);
  });
});
