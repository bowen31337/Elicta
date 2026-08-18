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
 */
export function LanguageChrome({ languages, activeTier }: LanguageChromeProps) {
  return (
    <div className="language-chrome">
      <ul className="language-chrome__languages" aria-label="Detected languages">
        {languages.length > 0 ? (
          languages.map((lang) => (
            <li key={lang.language} className="language-chrome__language">
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
