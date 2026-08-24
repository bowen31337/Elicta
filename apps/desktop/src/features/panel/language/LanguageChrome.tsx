import type { DetectedLanguage, SupportTier } from './types';
import { TIER_CAPABILITY_SUMMARY, TIER_LABEL } from './tierCapability';
import './LanguageChrome.css';

export interface LanguageChromeProps {
  languages: readonly DetectedLanguage[];
  activeTier: SupportTier | null;
}

/**
 * Renders the panel chrome's language strip: every language detected so far
 * this meeting (PRD FR-2.20), plus a badge for the active support tier. This
 * lives in the persistent chrome rather than the transient nudge feed, so a
 * code-switched meeting keeps showing every language it has ever detected
 * instead of only whichever one currently dominates.
 *
 * A language reaches the strip two ways, and they are not the same claim: the
 * engagement expects it in the room (FR-2.14), or it has actually been heard.
 * The strip shows both and distinguishes them, because it spent a long time
 * saying "No language detected" about meetings whose expected set the service
 * had already worked out.
 */
export function LanguageChrome({ languages, activeTier }: LanguageChromeProps) {
  // Everything on the strip is expected and nothing has been heard, so the
  // strip says which of those it means. Without this an operator reads two
  // tags and assumes the room has been transcribed.
  const awaiting = languages.length > 0 && languages.every((lang) => !lang.heard);

  return (
    <div className="language-chrome">
      {/* Ahead of the tags, not after them: it is the label the tags need, and
          "EN ZH Listening for" reads as a state that arrived late. */}
      {awaiting ? <span className="language-chrome__awaiting">Listening for</span> : null}

      <ul className="language-chrome__languages" aria-label="Detected languages">
        {languages.length > 0 ? (
          languages.map((lang) => (
            <li
              key={lang.language}
              className={
                lang.heard
                  ? 'language-chrome__language'
                  : 'language-chrome__language language-chrome__language--expected'
              }
              title={
                lang.heard
                  ? `${lang.language.toUpperCase()} — heard in this meeting`
                  : `${lang.language.toUpperCase()} — expected in this room, not heard yet`
              }
            >
              {lang.language.toUpperCase()}
            </li>
          ))
        ) : (
          <li className="language-chrome__empty">No language detected</li>
        )}
      </ul>

      {activeTier ? (
        <span
          className={`language-chrome__tier language-chrome__tier--${activeTier}`}
          title={TIER_CAPABILITY_SUMMARY[activeTier]}
        >
          {TIER_LABEL[activeTier]}
        </span>
      ) : null}
    </div>
  );
}
