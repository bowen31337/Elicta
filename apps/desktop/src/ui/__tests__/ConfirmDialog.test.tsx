import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ConfirmDialog } from '../ConfirmDialog';

/**
 * The question asked before something is taken away.
 *
 * A destructive action has obligations a plain button does not, and they are
 * assertions rather than notes because each is a way this could ship looking
 * finished and be wrong: it must say *what* is being removed rather than
 * "this item", the safe way out must be where a reflex lands, and dismissing
 * it must not count as agreeing.
 */
function open(overrides: Partial<Parameters<typeof ConfirmDialog>[0]> = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      open
      title="Remove Northwind Logistics?"
      body="Its meetings, documents and vocabulary go with it. Nothing is erased."
      confirmLabel="Remove"
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onConfirm, onCancel };
}

describe('confirming something destructive', () => {
  it('names the thing it is about to remove', () => {
    open();

    expect(screen.getByRole('dialog')).toHaveAccessibleName('Remove Northwind Logistics?');
  });

  it('says what removal actually does, since the answer depends on it', () => {
    open();

    expect(screen.getByText(/Nothing is erased/)).toBeInTheDocument();
  });

  it('does nothing until it is agreed to', () => {
    const { onConfirm } = open();

    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('removes when that is chosen', async () => {
    const { onConfirm } = open();

    await userEvent.click(screen.getByRole('button', { name: 'Remove' }));

    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it('puts the reflex on the safe side', async () => {
    /* Enter is what a hurried operator presses. It must not be the one that
       destroys — so the cancel is what holds focus when this opens. */
    open();

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Keep it' })).toHaveFocus(),
    );
  });

  it('treats Escape as declining, not as agreeing', async () => {
    const { onConfirm, onCancel } = open();

    await userEvent.keyboard('{Escape}');

    expect(onConfirm).not.toHaveBeenCalled();
    expect(onCancel).toHaveBeenCalled();
  });

  it('is not in the page at all until it is asked for', () => {
    render(
      <ConfirmDialog
        open={false}
        title="Remove Northwind Logistics?"
        body="anything"
        confirmLabel="Remove"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
