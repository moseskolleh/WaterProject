import { useState, type ReactNode } from 'react';
import type { Derived } from '../domain/derive';
import type { Borehole } from '../domain/types';
import { ChecksList } from './ChecksList';

interface Props {
  bh: Borehole;
  d: Derived;
  /** The sign-off strip — supplied by the stage so the ledger stays one layer. */
  footer: ReactNode;
}

/**
 * Derived decisions for the design stage.
 *
 * Nothing here is typed in — every figure falls out of the spine, so the rail
 * is the readout of the design, and signing it off is the decision.
 */
export function DecisionsRail({ bh, d, footer }: Props) {
  const [why, setWhy] = useState(false);
  const { testRate, testDuration, safetyFactor, drawdownPerLogCycle } = bh.hydraulics;
  const hours = Math.round(testDuration / 60);

  return (
    <aside className="rail">
      <div className="rail-head">Derived decisions</div>

      <div className="yield-card">
        <div className="eyebrow">Recommended safe yield</div>
        <div className="yield-value">
          {d.safeYield.toFixed(2)} <span className="unit">L/s</span>
        </div>
        <div className="yield-method">
          Cooper-Jacob on {hours} h constant rate. Safety factor{' '}
          {safetyFactor.toFixed(1)} on {testRate.toFixed(2)} L/s test rate.
        </div>
        <div className="chip-row">
          <span className="chip">T = {d.transmissivity.toFixed(0)} m²/d</span>
          <button
            type="button"
            className="chip"
            aria-expanded={why}
            onClick={() => setWhy((v) => !v)}
          >
            {why ? 'hide' : 'why?'}
          </button>
        </div>
        {why && (
          <div className="yield-method" style={{ marginTop: 9, opacity: 0.85 }}>
            Δs {drawdownPerLogCycle.toFixed(2)} m per log cycle over the{' '}
            {testDuration} min fit window → T = 2.3Q/4πΔs ={' '}
            {d.transmissivity.toFixed(1)} m²/d. Drawdown {d.drawdown.toFixed(1)} m
            from SWL {bh.hydraulics.restLevel.toFixed(1)} m. Signed daily log,
            A. Kamara.
          </div>
        )}
      </div>

      <div className="tile-row">
        <div className="tile">
          <div className="tile-label">Pump setting</div>
          <div className="tile-value">{d.pumpSetting.toFixed(1)} m</div>
          <div className="tile-sub">2 m above screen base</div>
        </div>
        <div className="tile">
          <div className="tile-label">Open area</div>
          <div className="tile-value">{d.openAreaPct.toFixed(1)} %</div>
          <div className="tile-sub">
            {d.openAreaM2.toFixed(2)} m² over {d.screenLength.toFixed(1)} m
          </div>
        </div>
      </div>

      <div className={`verdict is-${d.verdict.status}`}>
        <span className={`badge is-${d.verdict.status}`}>
          {d.verdict.status === 'ok' ? '✓' : '!'}
        </span>
        <div>
          <div className="verdict-title">{d.verdict.title}</div>
          <div className="verdict-detail">{d.verdict.detail}</div>
        </div>
      </div>

      <div className="rail-head">Live checks against the spine</div>
      <ChecksList checks={d.checks} />

      <div className="hint">
        <div className="hint-title">Editing the screen?</div>
        <div className="hint-body">
          Dragging either handle recomputes open area, pump setting and the BoQ
          casing/screen lines — and reflags any check it breaks. Arrow keys move
          the selected handle by 0.1 m, Shift for 1 m.
        </div>
      </div>

      <div className="spacer" />
      {footer}
    </aside>
  );
}
