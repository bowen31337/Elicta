import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

/**
 * `<dialog>`'s modal methods, which jsdom still does not implement.
 *
 * A gap in the test environment, not in the platform: every browser has had
 * these for years, and the focus trap, Escape handling and inert background
 * they bring are the reason `ConfirmDialog` uses a real `<dialog>` rather
 * than reimplementing four accessibility behaviours by hand. Standing in for
 * them here is the same job the DOM shims above do — what must not happen is
 * the production component being reshaped to suit jsdom.
 */
if (typeof HTMLDialogElement !== 'undefined' && !HTMLDialogElement.prototype.showModal) {
  HTMLDialogElement.prototype.showModal = function showModal(this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
    this.open = false;
    this.dispatchEvent(new Event('close'));
  };
  // Escape on an open modal fires `cancel`, then `close`. Spec'd behaviour
  // that jsdom does not perform, so a component relying on it would look
  // broken here and work everywhere. Dispatched rather than handled in the
  // component: which key dismisses a dialog is the platform's business, and
  // hard-coding it would be one more behaviour to keep in step with it.
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    for (const dialog of document.querySelectorAll('dialog[open]')) {
      const cancelled = !dialog.dispatchEvent(
        new Event('cancel', { cancelable: true }),
      );
      if (!cancelled) (dialog as HTMLDialogElement).close();
    }
  });
}

afterEach(() => {
  cleanup();
});
