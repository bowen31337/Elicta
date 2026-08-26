import { describe, expect, it, vi, afterEach } from 'vitest';

import { serviceFault } from '../serviceFault';

/**
 * Why there is no service, asked for rather than listened for.
 *
 * The shell resolves this before the page exists, so an event sent at that
 * moment has no listener and is lost. It keeps the reason instead and the page
 * asks once it is running.
 *
 * The reason matters more than it looks: the commonest one is another copy of
 * the app holding port 8000, and until now the only account of that was a line
 * on a stderr nobody opening a `.dmg` will ever read. What the operator saw
 * was every screen empty, which is what a product with nothing in it looks
 * like.
 */
afterEach(() => vi.unstubAllGlobals());

describe('asking the shell why there is no service', () => {
  it('returns what the shell is holding', async () => {
    const invoke = vi.fn(async () => 'Another copy of Elicta is already running its service.');
    expect(await serviceFault(invoke)).toMatch(/Another copy/);
  });

  it('is null when a service is running, which is the ordinary case', async () => {
    expect(await serviceFault(vi.fn(async () => null))).toBeNull();
  });

  it('is null outside the shell, where the question does not arise', async () => {
    // A browser run reaches the service through the dev server's proxy and
    // starts nothing, so there is no shell to ask and no fault to report.
    const invoke = vi.fn(async () => {
      throw new Error('not in the shell');
    });
    expect(await serviceFault(invoke)).toBeNull();
  });
});
