/**
 * What is not configured, and what it costs.
 *
 * The screen below this already lists every secret and whether it is set. That
 * is a list of facts, and facts are not warnings: `deepgram_api_key:
 * configured=false` sat on this screen the whole time a meeting recorded
 * cleanly, produced a transcript, and never showed a single nudge — because
 * the chunk upload forks into the live lane and that fork returns early
 * without a recogniser. Nothing said so anywhere.
 *
 * So the service now says which capabilities cannot run and what stops, and
 * this is where an operator reads it. Two rules keep it worth reading:
 *
 * - **What stops, not which field is blank.** The field is right there.
 * - **Required and optional are kept apart.** Sending somebody to configure
 *   Entra ID for a feature they are not using is how a warning becomes noise,
 *   and noise is how the one that mattered got missed.
 */

export interface CapabilityReadiness {
  readonly capability: string;
  readonly ready: boolean;
  readonly missing: readonly string[];
  readonly consequence: string;
  readonly optional?: boolean;
}

/** What each capability is called in the operator's terms. */
const TITLES: Record<string, string> = {
  inference: 'AI provider',
  live_nudges: 'Nudges during a meeting',
  record_transcription: 'Transcribing a finished meeting',
  document_links: 'Attaching documents by link',
};

function title(capability: string): string {
  return TITLES[capability] ?? capability.replace(/_/g, ' ');
}

export function ReadinessWarnings({
  readiness,
}: {
  readonly readiness: readonly CapabilityReadiness[];
}) {
  const blocked = readiness.filter((entry) => !entry.ready && !entry.optional);
  const unavailable = readiness.filter((entry) => !entry.ready && entry.optional);
  if (blocked.length === 0 && unavailable.length === 0) return null;

  return (
    <>
      {blocked.length > 0 ? (
        // `role="alert"` on the group rather than per entry: several missing
        // credentials on a fresh install are one situation, and announcing
        // each separately reads as several unrelated emergencies.
        <div className="group settings-readiness settings-readiness--blocked" role="alert">
          <p className="settings-readiness-lead">
            Some of what Elicta does cannot run until these are set.
          </p>
          {blocked.map((entry) => (
            <div className="row settings-readiness-row" key={entry.capability}>
              <div>
                <p className="settings-readiness-title">{title(entry.capability)}</p>
                <p className="settings-readiness-consequence">{entry.consequence}</p>
              </div>
              <p className="settings-readiness-keys">{entry.missing.join(', ')}</p>
            </div>
          ))}
        </div>
      ) : null}

      {unavailable.length > 0 ? (
        // Deliberately not an alert. Nothing is broken; a feature is simply
        // not available, and an operator who does not want it should not be
        // told twice that they have a problem.
        <div className="group settings-readiness settings-readiness--optional">
          <p className="settings-readiness-lead">
            Available once configured, and not needed otherwise.
          </p>
          {unavailable.map((entry) => (
            <div className="row settings-readiness-row" key={entry.capability}>
              <div>
                <p className="settings-readiness-title">{title(entry.capability)}</p>
                <p className="settings-readiness-consequence">{entry.consequence}</p>
              </div>
              <p className="settings-readiness-keys">{entry.missing.join(', ')}</p>
            </div>
          ))}
        </div>
      ) : null}
    </>
  );
}
