import { useState } from 'react';
import {
  SIGNATORY,
  timestamp,
  type DecisionRecord,
  type StageId,
} from '../domain/decision';

export type OverrideSpec =
  | {
      kind: 'number';
      label: string;
      unit: string;
      start: number;
      step: number;
      min: number;
      max: number;
      format: (n: number) => string;
    }
  | { kind: 'choice'; label: string; options: string[]; start: string };

interface Props {
  stage: StageId;
  /** The toolkit's recommendation, formatted for display. */
  recommended: string;
  /** Short form for the button when the recommendation is a sentence. */
  acceptLabel?: string;
  /** What accepting means, in one line. */
  writesTo: string;
  decision: DecisionRecord | null;
  /** False when a check is still flagged — accepting anyway is recorded. */
  clean: boolean;
  override: OverrideSpec;
  /** Nothing can receive a decision here, so do not offer to take one. */
  readOnly?: boolean;
  onDecide: (record: DecisionRecord | null) => void;
  /** Design stage only: discard edits to the screen. */
  revert?: { enabled: boolean; onRevert: () => void };
}

/**
 * The sign-off layer (2b) as a strip on the stage's own rail.
 *
 * Accepting is one press. Overriding costs a value and a reason, because the
 * override is the thing that ends up in front of the client with a name on it.
 */
export function SignOff({
  stage,
  recommended,
  acceptLabel,
  writesTo,
  decision,
  clean,
  override,
  readOnly = false,
  onDecide,
  revert,
}: Props) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState('');
  const [numberValue, setNumberValue] = useState(
    override.kind === 'number' ? override.start : 0,
  );
  const [choiceValue, setChoiceValue] = useState(
    override.kind === 'choice' ? override.start : '',
  );

  const accept = () => {
    onDecide({
      stage,
      status: 'accepted',
      value: recommended,
      recommended,
      signatory: SIGNATORY,
      at: timestamp(),
      clean,
    });
  };

  const recordOverride = () => {
    if (!reason.trim()) return;
    const value =
      override.kind === 'number' ? override.format(numberValue) : choiceValue;
    onDecide({
      stage,
      status: 'overridden',
      value,
      recommended,
      reason: reason.trim(),
      signatory: SIGNATORY,
      at: timestamp(),
      clean,
    });
    setOpen(false);
    setReason('');
  };

  if (readOnly) {
    return (
      <div className="signoff">
        <div className="signoff-note">
          Toolkit recommends <b>{recommended}</b>. {writesTo}. Signing off needs
          the full application — this build can show the decision but not record
          it.
        </div>
      </div>
    );
  }

  if (decision) {
    return (
      <div className={`signed is-${decision.status}`}>
        <div className="signed-row">
          <span className={`badge is-${decision.status === 'accepted' ? 'ok' : 'warn'}`}>
            {decision.status === 'accepted' ? '✓' : '↺'}
          </span>
          <div className="signed-body">
            <div className="signed-title">
              {decision.status === 'accepted' ? 'Accepted' : 'Overridden'} —{' '}
              {decision.value}
            </div>
            <div className="signed-meta">
              {decision.signatory} · {decision.at}
              {!decision.clean && ' · signed over an open flag'}
            </div>
            {decision.status === 'overridden' && (
              <div className="signed-reason">
                <span>toolkit said {decision.recommended}.</span> {decision.reason}
              </div>
            )}
          </div>
        </div>
        <button type="button" className="signed-reopen" onClick={() => onDecide(null)}>
          Reopen decision
        </button>
      </div>
    );
  }

  return (
    <div className="signoff">
      {open && (
        <div className="override-form">
          <div className="override-head">Override the recommendation</div>
          {override.kind === 'number' ? (
            <label className="override-field">
              <span>{override.label}</span>
              <span className="override-input">
                <input
                  type="number"
                  value={numberValue}
                  step={override.step}
                  min={override.min}
                  max={override.max}
                  onChange={(e) => setNumberValue(Number(e.target.value))}
                />
                <em>{override.unit}</em>
              </span>
            </label>
          ) : (
            <label className="override-field">
              <span>{override.label}</span>
              <select
                value={choiceValue}
                onChange={(e) => setChoiceValue(e.target.value)}
              >
                {override.options.map((o) => (
                  <option key={o} value={o}>
                    {o}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="override-field is-stacked">
            <span>Reason — required, and it goes in the report</span>
            <textarea
              rows={3}
              value={reason}
              placeholder="e.g. dry-season static level is 3 m lower; certifying the conservative figure."
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <div className="override-actions">
            <button type="button" onClick={() => setOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="is-primary"
              disabled={!reason.trim()}
              onClick={recordOverride}
            >
              Record override
            </button>
          </div>
        </div>
      )}

      {!open && (
        <div className="signoff-note">
          {clean ? writesTo : `${writesTo} · one check is still flagged`}
        </div>
      )}

      <div className="rail-footer">
        {revert ? (
          <button
            type="button"
            className="revert"
            disabled={!revert.enabled}
            onClick={revert.onRevert}
          >
            Revert
          </button>
        ) : (
          <button type="button" className="revert" onClick={() => setOpen((v) => !v)}>
            Override…
          </button>
        )}
        {revert && (
          <button type="button" className="revert" onClick={() => setOpen((v) => !v)}>
            Override…
          </button>
        )}
        <button type="button" className="accept" onClick={accept}>
          Accept {acceptLabel ?? recommended} →
        </button>
      </div>
    </div>
  );
}
