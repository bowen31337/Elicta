import { useEffect, useRef } from 'react';

import type { IndexEntry } from './sectionIndex';
import { flattenEntries, revealOffset } from './sectionIndex';

/**
 * The page's table of contents, pinned beside it.
 *
 * Preparation is the one screen whose length is data rather than design, and
 * the data won: with a real compiled bank open it is 11,021px — twelve
 * viewports — and the Meetings section, which is the next thing an operator
 * does, starts at 10,235px. There was no route to it but the wheel.
 *
 * The idiom is the one a long document gets on this platform: a contents rail
 * in the margin at desk width, and the same rows as a scrolling row of
 * capsules under the chrome when there is no margin to put them in. One
 * component, two presentations — `screens.css` decides which, so the rows,
 * their order and their "you are here" cannot drift apart between widths.
 *
 * Rows are real anchors, so the pointer gets a target it can copy and open and
 * the keyboard gets one it can reach, both from the platform rather than from
 * us. Their default action is *not* taken: this app routes on the fragment
 * (`#/prep`), so letting an `href="#prep-meetings"` navigate would rewrite the
 * route to a screen that does not exist and throw the operator off the page
 * they were reading. `onJump` scrolls and moves focus instead.
 */
export interface SectionIndexProps {
  readonly entries: readonly IndexEntry[];
  /** Which row is marked. `null` before anything has been measured. */
  readonly currentId: string | null;
  readonly onJump: (entry: IndexEntry) => void;
}

export function SectionIndex({ entries, currentId, onJump }: SectionIndexProps) {
  /**
   * Every row on the trail down to the current one, not just the last of them.
   *
   * Two reasons, and either alone would be enough. It is the truer claim — a
   * reader inside Operations is inside the Question bank — and at narrow widths
   * the bank's own rows are not drawn at all, so a mark that lived only on the
   * innermost row would land on something CSS had removed: no capsule marked
   * for the eye, and nothing current for a screen reader either. CSS cannot fix
   * an ARIA problem, so the answer is not to create one.
   */
  const trail = new Set<string>();
  if (currentId !== null) {
    const walk = (level: readonly IndexEntry[]): boolean =>
      level.some((entry) => {
        const hit = entry.id === currentId || walk(entry.children ?? []);
        if (hit) trail.add(entry.id);
        return hit;
      });
    walk(entries);
    // A current id naming nothing in the index marks nothing, rather than
    // marking the first row and quietly lying about where the reader is.
    if (!flattenEntries(entries).some((entry) => entry.id === currentId)) trail.clear();
  }

  return (
    <nav className="section-index" aria-label="On this page" ref={useRevealed(currentId)}>
      {/* Hidden from the accessibility tree because the nav is already named
          the same thing, and a heading repeating its own container's label is
          the same words twice to anyone listening. The eye needs it: without a
          caption a column of quiet text in the margin is a stray menu rather
          than the page's contents. */}
      <p className="index-caption t-caption" aria-hidden="true">
        On this page
      </p>
      <IndexList
        entries={entries}
        trail={trail}
        onJump={onJump}
        label="Sections of this page"
      />
    </nav>
  );
}

function IndexList({
  entries,
  trail,
  onJump,
  label,
  nested = false,
}: {
  readonly entries: readonly IndexEntry[];
  readonly trail: ReadonlySet<string>;
  readonly onJump: (entry: IndexEntry) => void;
  readonly label: string;
  readonly nested?: boolean;
}) {
  return (
    <ul className={`index-list${nested ? ' index-list--nested' : ''}`} aria-label={label}>
      {entries.map((entry) => (
        <li key={entry.id}>
          <a
            className="index-row"
            href={`#${entry.id}`}
            /* `true`, not `page`: the sidebar already claims `page` for the
               screen this is a screen of, and a second `page` in the same
               window would be two answers to one question. */
            aria-current={trail.has(entry.id) ? 'true' : undefined}
            onClick={(event) => {
              event.preventDefault();
              onJump(entry);
            }}
          >
            <span className="index-row-label">{entry.label}</span>
            {entry.count === undefined ? null : (
              <>
                {' '}
                <span className="t-caption tabular index-row-count">{entry.count}</span>
              </>
            )}
          </a>
          {entry.children === undefined || entry.children.length === 0 ? null : (
            <IndexList
              entries={entry.children}
              trail={trail}
              onJump={onJump}
              label={entry.childrenLabel ?? `${entry.label} sections`}
              nested
            />
          )}
        </li>
      ))}
    </ul>
  );
}

/**
 * Keeps the marked capsule inside the bar it lives in.
 *
 * Where there is no margin for a rail the index is a row of capsules that
 * scrolls sideways, and the mark drifts out of it as the reader moves down the
 * page — on a 390px display, reading the Question bank, the capsule saying so
 * sat off the right-hand edge, which is an index failing at the one thing it
 * is for.
 *
 * Only the bar ever moves. The scroll is set on the list directly rather than
 * asked for with `scrollIntoView`, which would have been free to scroll the
 * *page* as well, and a table of contents that scrolls the document out from
 * under the reader while they are reading it is worse than one that does
 * nothing. Where the list does not overflow — the rail, at desk width — the
 * arithmetic returns the offset it was given and nothing is written.
 */
function useRevealed(currentId: string | null) {
  const navRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const nav = navRef.current;
    if (nav === null) return;

    // The outermost marked row: at narrow widths the nested ones are not
    // drawn, and the trail guarantees there is always an outermost one.
    const row = nav.querySelector<HTMLElement>('.index-list > li > .index-row[aria-current]');
    const list = row?.parentElement?.parentElement;
    if (row === undefined || row === null || !(list instanceof HTMLElement)) return;

    const gutter = parseFloat(getComputedStyle(list).paddingLeft) || 0;
    const next = revealOffset(row.offsetLeft, row.offsetWidth, list.scrollLeft, list.clientWidth, gutter);
    if (next !== list.scrollLeft) list.scrollLeft = next;
  }, [currentId]);

  return navRef;
}
