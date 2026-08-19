import { useMemo, useState } from 'react';
import { makeScale } from '../../domain/scale';
import type { DecisionRecord } from '../../domain/decision';
import type { SpineView } from '../../domain/view';
import { DepthRuler } from '../columns/DepthRuler';
import { LithologyColumn } from '../columns/LithologyColumn';
import { ConstructionColumn } from '../columns/ConstructionColumn';
import { HydraulicsColumn } from '../columns/HydraulicsColumn';
import { FlagsList } from '../FlagsList';
import { SignOff } from '../SignOff';
import { useScreenDrag, type Interval } from '../useScreenDrag';

interface Props {
  view: SpineView;
  /** Live drag preview; null when showing exactly what Python returned. */
  preview: Interval[] | null;
  onPreview: (screens: Interval[] | null) => void;
  onCommit: (screens: Interval[]) => void;
  onReset: () => void;
  edited: boolean;
  busy: boolean;
  readOnly?: boolean;
  decision: DecisionRecord | null;
  onDecide: (record: DecisionRecord | null) => void;
}

export function DesignStage({
  view,
  preview,
  onPreview,
  onCommit,
  onReset,
  edited,
  busy,
  readOnly = false,
  decision,
  onDecide,
}: Props) {
  const [why, setWhy] = useState(false);
  const { section, design } = view;
  const scale = useMemo(() => makeScale(section.domain), [section.domain]);
  const screens = preview ?? design.screens.map((s) => ({ top: s.top, base: s.base }));

  const { dragging, start, keyDown } = useScreenDrag({
    screens,
    limits: section.screenLimits,
    scale,
    onPreview,
    onCommit,
  });

  const y = design.yield;
  const errors = design.flags.filter((f) => f.level === 'error');
  const clean = errors.length === 0 && design.flags.every((f) => f.level === 'info');
  const recommended = y.rangeText ?? 'pending';

  return (
    <div className="ws-body">
      <div className="spine">
        <div className="metrics">
          <div className="metric-row">
            <div>
              <div className="metric-label">Drilled</div>
              <div className="metric-value">{section.totalDepth.toFixed(1)} m</div>
            </div>
            <div>
              <div className="metric-label">Water strikes</div>
              <div className="metric-value">
                {section.waterStrikes.length
                  ? section.waterStrikes.map((s) => s.toFixed(0)).join(', ') + ' m'
                  : 'none'}
              </div>
            </div>
            <div>
              <div className="metric-label">Screened</div>
              <div className="metric-value is-aquifer">
                {design.totalScreenM} m <span className="unit-note">{design.screenShare}%</span>
              </div>
            </div>
            <div>
              <div className="metric-label">Casing</div>
              <div className="metric-value">
                {section.casingDiameterIn}″ {section.casingMaterial}
              </div>
            </div>
            <div>
              <div className="metric-label">Slot</div>
              <div className="metric-value">{section.slotMm} mm</div>
            </div>
          </div>
          <div className="legend">
            <span>
              <span className="sw-block" />
              screened
            </span>
            <span>
              <span className="sw-line" style={{ background: 'oklch(0.72 0.15 var(--water-h))' }} />
              rest level
            </span>
            <span>
              <span className="sw-line" style={{ background: 'oklch(0.72 0.16 55)' }} />
              {section.levels.stabilised ? 'pumping level' : 'deepest level'}
            </span>
          </div>
        </div>

        <div className={`columns${busy ? ' is-busy' : ''}`}>
          <DepthRuler scale={scale} />
          <LithologyColumn
            scale={scale}
            units={section.lithology}
            strikes={section.waterStrikes}
          />
          <ConstructionColumn
            scale={scale}
            section={section}
            screens={screens}
            dragging={dragging}
            readOnly={readOnly}
            onHandleDown={start}
            onHandleKey={keyDown}
          />
          <HydraulicsColumn scale={scale} section={section} />
        </div>
      </div>

      <aside className="rail">
        <div className="rail-head">
          Derived decisions
          {busy && <span className="rail-busy">re-deriving…</span>}
        </div>

        {y.pending ? (
          <div className="yield-card is-pending">
            <div className="eyebrow">Recommended safe yield</div>
            <div className="yield-value is-text">Pending</div>
            <div className="yield-method">{y.pending}</div>
          </div>
        ) : (
          <div className="yield-card">
            <div className="eyebrow">Recommended safe yield</div>
            <div className="yield-value">
              {y.safeYieldM3PerH} <span className="unit">m³/h</span>
            </div>
            {y.lowM3PerH != null && y.highM3PerH != null && (
              <div className="yield-range">
                <span>{y.lowM3PerH}</span>
                <span className="yield-range-bar">
                  <i />
                </span>
                <span>{y.highM3PerH}</span>
              </div>
            )}
            <div className="yield-method">
              Projected to {y.designPeriodDays} days, safety factor {y.safetyFactor}.
              The band is the plausible range over the assumptions it rests on.
            </div>
            <div className="chip-row">
              <span className="chip">T = {y.transmissivity} m²/d</span>
              <span className="chip">pump {y.pumpDepthM} m</span>
              <button type="button" className="chip" aria-expanded={why}
                onClick={() => setWhy((v) => !v)}>
                {why ? 'hide' : 'why?'}
              </button>
            </div>
            {why && (
              <div className="yield-method" style={{ marginTop: 9, opacity: 0.85 }}>
                {y.basis}
                {y.envelopeBasis ? ` ${y.envelopeBasis}` : ''}
              </div>
            )}
          </div>
        )}

        {y.methods && y.methods.length > 0 && (
          <div className="methods">
            <div className="tile-label">Transmissivity by method — m²/d</div>
            {y.methods.map((m) => (
              <div className="mini-row" key={m.label}>
                <span>{m.label}</span>
                <span>{m.transmissivity}</span>
              </div>
            ))}
            <div className="mini-row is-total">
              <span>Preferred</span>
              <span>{y.transmissivity}</span>
            </div>
          </div>
        )}

        <div className="rail-head">Design basis</div>
        <ul className="basis-list">
          {design.basis.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>

        <div className="rail-head">Flags on this design</div>
        <FlagsList flags={design.flags} empty="No flags raised on the design or the test." />

        <div className="hint">
          <div className="hint-title">
            {readOnly ? 'Moving a screen' : 'Moving a screen'}
          </div>
          <div className="hint-body">
            {readOnly
              ? 'Screens are set from the page below in this build. Every figure ' +
                'here is still computed by the toolkit — the section, the flags ' +
                'and the bill of quantities all come from the same design.'
              : 'Drag a handle, or focus one and use the arrow keys — 0.1 m a ' +
                'press, 1 m with Shift. On release the toolkit re-runs the ' +
                'design: the casing string, the annulus, the flags and the bill ' +
                'of quantities all come back from Python, so nothing here is a ' +
                'second opinion.'}
          </div>
        </div>

        <div className="spacer" />

        {edited && !readOnly && (
          <button type="button" className="reset-link" onClick={onReset}>
            Back to the generated design
          </button>
        )}

        <SignOff
          stage="design"
          readOnly={readOnly}
          recommended={recommended}
          acceptLabel="the design"
          writesTo="accepting writes to the completion and pumping-test reports"
          decision={decision}
          clean={clean}
          onDecide={onDecide}
          override={{
            kind: 'number',
            label: 'Certified safe yield',
            unit: 'm³/h',
            start: y.safeYieldM3PerH ?? 0,
            step: 0.01,
            min: 0,
            max: 100,
            format: (n) => `${n} m³/h`,
          }}
        />
      </aside>
    </div>
  );
}
