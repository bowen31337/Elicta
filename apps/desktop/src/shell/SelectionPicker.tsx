import {
  useCurrentEngagement,
  useCurrentMeeting,
  type EngagementSummary,
  type MeetingSummary,
} from '../services/selection';

/**
 * Which engagement — and which of its meetings — the app is about.
 *
 * `useCurrentEngagement` has always exposed `select()`, and until now nothing
 * called it. So the app was permanently about whichever engagement the service
 * listed first, and on a machine holding nine of them that is the oldest one,
 * which had no meetings: every screen reported there was nothing to show while
 * the operator's actual work sat one row down the list.
 *
 * It lives in the toolbar rather than on a screen because the choice is not
 * about any one screen — it scopes all of them, the way a Mac window's toolbar
 * carries the controls that apply to whatever is in the pane.
 *
 * Plain `<select>` elements, deliberately. Keyboard reach, focus ring,
 * type-ahead and the platform's own menu come from the element; a custom
 * popover would mean re-implementing all four, and this control is the one
 * thing an operator must be able to reach before anything else works.
 */

/**
 * Menu rows, with an id added only to the ones that would otherwise be
 * indistinguishable.
 *
 * Found by running the real thing: the service held nine engagements, six of
 * which were identical in every field the list returns — same client, same
 * sector, same commercial context. A menu of six rows reading "Northwind
 * Logistics" offers no choice at all. The id is ugly and it is the only thing
 * that actually differs, so it appears exactly where it is needed and nowhere
 * else.
 */
export function optionLabels(
  options: readonly { readonly id: string; readonly label: string }[],
): string[] {
  const seen = new Map<string, number>();
  for (const option of options) {
    seen.set(option.label, (seen.get(option.label) ?? 0) + 1);
  }
  return options.map((option) =>
    (seen.get(option.label) ?? 0) > 1 ? `${option.label} · ${option.id}` : option.label,
  );
}

/** A meeting's row in the menu — never an invented one. */
export function meetingOptionLabel(meeting: MeetingSummary): string {
  if (meeting.session_purpose !== null && meeting.session_purpose !== '') {
    return meeting.session_purpose;
  }
  if (meeting.scheduled_at !== null) {
    const at = new Date(meeting.scheduled_at);
    if (!Number.isNaN(at.getTime())) return at.toLocaleString(undefined, { dateStyle: 'medium' });
  }
  // Nothing to call it by. The id is at least true, and reads as the gap it is.
  return meeting.meeting_id;
}

export interface SelectionPickerViewProps {
  readonly engagements: readonly EngagementSummary[];
  readonly engagementId: string | null;
  readonly onSelectEngagement: (engagementId: string) => void;
  readonly meetings: readonly MeetingSummary[];
  readonly meetingId: string | null;
  readonly onSelectMeeting: (meetingId: string) => void;
}

/**
 * The control itself, on fixed props.
 *
 * Separate from the connected component so the fixed-scene harness can show a
 * populated one — which is what puts it in front of the accessibility audit.
 * The toolbar is a translucent material and composites darker than a card, so
 * this is exactly the ground `audit-a11y.mjs` exists to measure, and a control
 * that only ever appears when a service is answering would never be measured
 * at all.
 */
export function SelectionPickerView({
  engagements,
  engagementId,
  onSelectEngagement,
  meetings,
  meetingId,
  onSelectMeeting,
}: SelectionPickerViewProps) {
  const engagementLabels = optionLabels(
    engagements.map((candidate) => ({
      id: candidate.engagement_id,
      label: candidate.client_organisation,
    })),
  );
  const meetingLabels = optionLabels(
    meetings.map((candidate) => ({
      id: candidate.meeting_id,
      label: meetingOptionLabel(candidate),
    })),
  );

  // Nothing to choose between: a service still loading, one that cannot be
  // reached, or one that genuinely holds no engagements. The screen in the
  // pane says which of those it is — a menu with no options here would only
  // add a second, vaguer account of the same thing.
  if (engagements.length === 0) return null;

  return (
    <div className="toolbar-picker">
      <div className="picker-field">
        <label className="picker-label t-caption" htmlFor="current-engagement">
          Engagement
        </label>
        <select
          className="picker-select t-subhead"
          id="current-engagement"
          value={engagementId ?? ''}
          onChange={(event) => onSelectEngagement(event.target.value)}
        >
          {engagementLabels.map((label, index) => (
            <option key={engagements[index].engagement_id} value={engagements[index].engagement_id}>
              {label}
            </option>
          ))}
        </select>
      </div>

      {meetings.length > 0 ? (
        <div className="picker-field">
          <label className="picker-label t-caption" htmlFor="current-meeting">
            Meeting
          </label>
          <select
            className="picker-select t-subhead"
            id="current-meeting"
            value={meetingId ?? ''}
            onChange={(event) => onSelectMeeting(event.target.value)}
          >
            {meetingLabels.map((label, index) => (
              <option key={meetings[index].meeting_id} value={meetings[index].meeting_id}>
                {label}
              </option>
            ))}
          </select>
        </div>
      ) : null}
    </div>
  );
}

/** The same control, reading and writing the app's actual selection. */
export function SelectionPicker() {
  const engagement = useCurrentEngagement();
  const meeting = useCurrentMeeting(engagement.engagementId);

  return (
    <SelectionPickerView
      engagements={engagement.engagements}
      engagementId={engagement.engagementId}
      onSelectEngagement={engagement.select}
      meetings={meeting.meetings}
      meetingId={meeting.meetingId}
      onSelectMeeting={meeting.select}
    />
  );
}
