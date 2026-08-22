import '../prep/screens.css';

import { useState } from 'react';

import { useCurrentEngagement } from '../../services/selection';
import { ScreenEyebrow } from '../../ui/Mark';
import { ScreenState } from '../../ui/ScreenState';
import { createEngagement, deleteEngagement } from './engagementActions';

/**
 * Which client you are working on.
 *
 * The navigation follows the arc of one engagement — before, during and after
 * a meeting — and had no step for choosing which engagement that is. So
 * creating and removing clients ended up at the foot of the Preparation
 * screen: a page headed with one client's name that two-thirds of the way down
 * offered a blank form for a different one, with a button that removed the
 * whole client sharing its colour and its scroll with the small, reversible
 * edits above it.
 *
 * This is that missing step. Preparation goes back to being what its own
 * caption says it is — what you know going in, and the questions worth asking
 * — about one client, chosen here.
 */
export interface EngagementSummaryRow {
  readonly id: string;
  readonly clientOrganisation: string;
  readonly sector: string;
  readonly commercialContext: string;
}

export interface EngagementsActions {
  readonly open: (engagementId: string) => void;
  readonly create: (engagement: {
    clientOrganisation: string;
    sector: string;
    commercialContext: string;
  }) => Promise<void>;
  readonly remove: (engagementId: string) => Promise<void>;
}

export interface EngagementsScreenProps {
  readonly engagements: readonly EngagementSummaryRow[];
  readonly currentId: string | null;
  readonly actions: EngagementsActions;
}

function useWrite() {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (write: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await write();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  };

  return { error, busy, run };
}

export function EngagementsScreen({
  engagements,
  currentId,
  actions,
}: EngagementsScreenProps) {
  const write = useWrite();
  const [clientOrganisation, setClientOrganisation] = useState('');
  const [sector, setSector] = useState('');
  const [commercialContext, setCommercialContext] = useState('');

  const complete =
    clientOrganisation.trim() !== '' && sector.trim() !== '' && commercialContext.trim() !== '';

  const create = () => {
    if (!complete) return;
    void write.run(async () => {
      await actions.create({
        clientOrganisation: clientOrganisation.trim(),
        sector: sector.trim(),
        commercialContext: commercialContext.trim(),
      });
      setClientOrganisation('');
      setSector('');
      setCommercialContext('');
    });
  };

  return (
    <main className="screen" aria-labelledby="engagements-title">
      <header className="screen-head">
        <ScreenEyebrow>Engagements</ScreenEyebrow>
        <h1 className="t-large-title" id="engagements-title">
          Your clients
        </h1>
      </header>

      {write.error === null ? null : (
        <p className="t-footnote prep-error" role="alert">
          {write.error}
        </p>
      )}

      <section aria-labelledby="list-title">
        <h2 className="t-section" id="list-title">
          Engagements
        </h2>
        <div className="group">
          {engagements.length === 0 ? (
            <div className="row">
              <div className="row-main">
                <span className="t-body">No engagements yet</span>
                <span className="t-footnote">
                  An engagement is one client. Everything else in Elicta hangs
                  off one, so this is the first thing to make.
                </span>
              </div>
            </div>
          ) : (
            engagements.map((engagement) => (
              <div className="row" key={engagement.id}>
                <div className="row-main">
                  <span className="t-body">{engagement.clientOrganisation}</span>
                  <span className="t-footnote">
                    {engagement.sector} · {engagement.commercialContext}
                  </span>
                </div>
                {engagement.id === currentId ? (
                  // Not "Open": the button beside it says that, and a status
                  // sharing a word with the action next to it reads as two
                  // buttons, one of which appears broken.
                  <span className="pill pill--ok">Current</span>
                ) : null}
                <button
                  type="button"
                  className="btn"
                  disabled={write.busy}
                  aria-label={`Open ${engagement.clientOrganisation}`}
                  onClick={() => actions.open(engagement.id)}
                >
                  Open
                </button>
                <button
                  type="button"
                  className="btn btn--danger"
                  disabled={write.busy}
                  aria-label={`Remove ${engagement.clientOrganisation}`}
                  onClick={() => void write.run(() => actions.remove(engagement.id))}
                >
                  Remove
                </button>
              </div>
            ))
          )}
        </div>
        <p className="t-footnote hint">
          Opening one makes it the client every other screen is about. Removing
          one takes it off this list along with its meetings, documents and
          vocabulary — nothing is erased, and it can be brought back.
        </p>
      </section>

      <section aria-labelledby="new-title">
        <h2 className="t-section" id="new-title">
          New engagement
        </h2>
        <div className="group">
          <Field
            id="new-client"
            label="Client organisation"
            placeholder="Northwind Logistics"
            value={clientOrganisation}
            onChange={setClientOrganisation}
          />
          <Field
            id="new-sector"
            label="Sector"
            placeholder="Freight and logistics"
            value={sector}
            onChange={setSector}
          />
          <Field
            id="new-commercial"
            label="Commercial context"
            placeholder="Fixed-price discovery, three meetings"
            value={commercialContext}
            onChange={setCommercialContext}
          />
        </div>
        <p className="t-footnote hint">
          The sector and the commercial shape are not filing. They are what lets
          Elicta work out which languages to expect in the room.
        </p>

        <div className="group">
          <div className="row">
            <div className="row-main">
              <span className="t-body">Ready when all three are filled in</span>
            </div>
            <button
              type="button"
              className="btn btn--filled"
              disabled={write.busy || !complete}
              onClick={create}
            >
              Create engagement
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}

function Field({
  id,
  label,
  placeholder,
  value,
  onChange,
}: {
  readonly id: string;
  readonly label: string;
  readonly placeholder: string;
  readonly value: string;
  readonly onChange: (next: string) => void;
}) {
  return (
    <div className="row row--form">
      <div className="row-main">
        <label className="t-footnote" htmlFor={id}>
          {label}
        </label>
        <input
          id={id}
          type="text"
          className="field"
          placeholder={placeholder}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      </div>
    </div>
  );
}

export default function EngagementsRoute() {
  const current = useCurrentEngagement();

  // `idle` is not a state this screen can be in: with no engagements it is not
  // waiting for one to be chosen, it is the place you make the first.
  if (current.status === 'loading' || current.status === 'error') {
    return <ScreenState eyebrow="Engagements" status={current.status} error={current.error} />;
  }

  const actions: EngagementsActions = {
    open: (engagementId) => {
      current.select(engagementId);
      // Preparation is what an operator wants next: they picked a client in
      // order to work on one, not to admire the list.
      window.location.hash = '#/prep';
    },
    create: async (engagement) => {
      await createEngagement(engagement);
      current.reload();
    },
    remove: async (engagementId) => {
      await deleteEngagement(engagementId);
      current.reload();
    },
  };

  return (
    <EngagementsScreen
      engagements={current.engagements.map((engagement) => ({
        id: engagement.engagement_id,
        clientOrganisation: engagement.client_organisation,
        sector: engagement.sector,
        commercialContext: engagement.commercial_context,
      }))}
      currentId={current.engagementId}
      actions={actions}
    />
  );
}
