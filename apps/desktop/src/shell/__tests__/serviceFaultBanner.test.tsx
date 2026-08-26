import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ServiceFaultBanner } from '../ServiceFaultBanner';

/**
 * The one failure that makes every screen look empty at once.
 *
 * When the shell cannot start its service — almost always because another
 * copy of the app is holding port 8000 — nothing works and nothing says why.
 * Every screen reports what it individually found, which is nothing, and an
 * operator reads a product with no data in it rather than two copies of one
 * app fighting over a port.
 *
 * So it is said once, above everything, in the words the shell used.
 */
describe('the service fault banner', () => {
  it('says what the shell said, as an alert', async () => {
    const ask = vi.fn(async () => 'Another copy of Elicta is already running its service.');
    render(<ServiceFaultBanner ask={ask} />);

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent(/Another copy of Elicta/),
    );
  });

  it('renders nothing at all when the service is running', async () => {
    const ask = vi.fn(async () => null);
    const { container } = render(<ServiceFaultBanner ask={ask} />);

    await waitFor(() => expect(ask).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
