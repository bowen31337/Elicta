import { useEffect, useRef } from 'react';

import './ConfirmDialog.css';

/**
 * The question asked before something is taken away.
 *
 * A native `<dialog>`, opened with `showModal`, and that is the whole design
 * decision. It brings the focus trap, Escape, the inert background and the
 * top layer with it — four things that are easy to hand-roll and easy to get
 * subtly wrong, and that a screen reader and a keyboard both depend on being
 * exactly right. jsdom does not implement it, which is a gap in the test
 * environment rather than a reason to reimplement the platform; `testSetup`
 * stands in for it there.
 *
 * Three obligations a destructive prompt has that an ordinary one does not:
 * it names what is going, it says what going actually means — the answer
 * depends on whether this is recoverable — and the safe way out is where a
 * reflex lands.
 */
export interface ConfirmDialogProps {
  readonly open: boolean;
  readonly title: string;
  readonly body: string;
  readonly confirmLabel: string;
  readonly cancelLabel?: string;
  readonly onConfirm: () => void;
  readonly onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel = 'Keep it',
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null);
  const safe = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    dialog.current?.showModal?.();
    // Explicit rather than `autofocus`: the browser's own choice is the first
    // focusable child, which here would be the button that destroys.
    safe.current?.focus();
  }, [open]);

  if (!open) return null;

  return (
    <dialog
      ref={dialog}
      className="confirm"
      aria-labelledby="confirm-title"
      aria-describedby="confirm-body"
      // Escape closes a native dialog on its own, and closing is declining.
      // Without this the dialog would vanish and the caller would still
      // believe it was open — the state that makes a second attempt do
      // nothing at all.
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onClose={onCancel}
    >
      <h2 className="t-title-3 confirm-title" id="confirm-title">
        {title}
      </h2>
      <p className="t-footnote confirm-body" id="confirm-body">
        {body}
      </p>
      <div className="confirm-actions">
        <button type="button" className="btn" ref={safe} onClick={onCancel}>
          {cancelLabel}
        </button>
        <button type="button" className="btn btn--danger confirm-go" onClick={onConfirm}>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
