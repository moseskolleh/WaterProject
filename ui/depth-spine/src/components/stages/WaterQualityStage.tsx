import { useMemo } from 'react';
import type { DecisionRecord } from '../../domain/decision';
import { deriveQuality, type WaterSample } from '../../domain/quality';
import { ChecksList } from '../ChecksList';
import { SignOff } from '../SignOff';
import { GuidelineSpine } from '../charts/GuidelineSpine';
import { PiperDiagram } from '../charts/PiperDiagram';
import { StiffDiagram } from '../charts/StiffDiagram';

interface Props {
  sample: WaterSample;
  decision: DecisionRecord | null;
  onDecide: (record: DecisionRecord | null) => void;
}

const VERDICT_LABEL = {
  potable: 'Potable',
  'potable-with-caveat': 'Potable — aesthetic exceedance',
  'not-potable': 'Not potable without treatment',
} as const;

export function WaterQualityStage({ sample, decision, onDecide }: Props) {
  const q = useMemo(() => deriveQuality(sample), [sample]);
  const clean = q.checks.every((c) => c.status === 'ok');
  const ph = q.results.find((r) => r.id === 'ph');
  const ec = q.results.find((r) => r.id === 'ec');

  return (
    <div className="ws-body">
      <div className="spine">
        <div className="metrics">
          <div className="metric-row">
            <div>
              <div className="metric-label">Sampled</div>
              <div className="metric-value is-small">{sample.sampledOn}</div>
            </div>
            <div>
              <div className="metric-label">Within guideline</div>
              <div className="metric-value">
                {q.withinCount} / {q.judgedCount}
              </div>
            </div>
            <div>
              <div className="metric-label">pH</div>
              <div className={`metric-value${ph?.status === 'warn' ? ' is-warn' : ''}`}>
                {ph?.value}
              </div>
            </div>
            <div>
              <div className="metric-label">Conductivity</div>
              <div className="metric-value">{ec?.value} µS/cm</div>
            </div>
            <div>
              <div className="metric-label">Water type</div>
              <div className="metric-value is-aquifer">{q.waterType}</div>
            </div>
          </div>
          <div className="legend">
            <span>
              <span className="sw-block" />
              within guideline
            </span>
            <span>
              <span className="sw-block" style={{ background: 'oklch(0.75 0.15 65)' }} />
              exceeds
            </span>
          </div>
        </div>

        <div className="quality-body">
          <div className="quality-main">
            <div className="panel-head">
              WHO guideline value — every determinand as a multiple of its own limit
            </div>
            <GuidelineSpine results={q.results} />
            <div className="panel-foot">
              WHO Guidelines for Drinking-water Quality, 4th edition incorporating
              the 1st and 2nd addenda. Sierra Leone national standards adopt these
              values for the determinands shown. Analysis by {sample.laboratory}.
            </div>

            <div className="quality-row">
              <div className="panel">
                <div className="panel-head">Ionic balance</div>
                <div className="balance">
                  <div className="balance-side">
                    <span className="balance-label">Σ cations</span>
                    <span className="balance-value">{q.meq.cations.toFixed(2)}</span>
                  </div>
                  <div className="balance-bar">
                    <span
                      className={`balance-fill${Math.abs(q.balanceError) > 5 ? ' is-warn' : ''}`}
                      style={{
                        width: `${Math.min(Math.abs(q.balanceError) * 8, 50)}%`,
                        left: q.balanceError < 0 ? 'auto' : '50%',
                        right: q.balanceError < 0 ? '50%' : 'auto',
                      }}
                    />
                  </div>
                  <div className="balance-side is-right">
                    <span className="balance-label">Σ anions</span>
                    <span className="balance-value">{q.meq.anions.toFixed(2)}</span>
                  </div>
                </div>
                <div className="panel-foot">
                  Error {q.balanceError > 0 ? '+' : ''}
                  {q.balanceError.toFixed(1)} % against a ±5 % acceptance limit — the
                  analysis is internally consistent, so the rest of this page can be
                  relied on.
                </div>
              </div>

              <div className="panel">
                <div className="panel-head">Provenance of this analysis</div>
                <div className="provenance">
                  <div className="mini-row">
                    <span>Sampled</span>
                    <span>{sample.sampledOn} · after 20 min purge</span>
                  </div>
                  <div className="mini-row">
                    <span>Preservation</span>
                    <span>
                      {sample.preserved ? 'filtered 0.45 µm, acidified' : 'unpreserved'}
                    </span>
                  </div>
                  <div className="mini-row">
                    <span>Transit to laboratory</span>
                    <span>{sample.transitHours} h, chilled</span>
                  </div>
                  <div className="mini-row">
                    <span>Laboratory</span>
                    <span>{sample.laboratory}</span>
                  </div>
                  <div className="mini-row">
                    <span>Field temperature</span>
                    <span>{sample.temperatureC} °C</span>
                  </div>
                </div>
                <div className="panel-foot">
                  Every determinand above traces to this one signed chain of
                  custody — the ionic balance is what proves it held.
                </div>
              </div>
            </div>
          </div>

          <div className="quality-side">
            <div className="panel">
              <div className="panel-head">Piper — hydrochemical facies</div>
              <PiperDiagram p={q.pct} />
              <div className="panel-foot">
                {q.waterType} · fresh, recently recharged water typical of a
                weathered-basement aquifer.
              </div>
            </div>
            <div className="panel">
              <div className="panel-head">Stiff — ionic shape</div>
              <StiffDiagram m={q.meq} />
            </div>
          </div>
        </div>
      </div>

      <aside className="rail">
        <div className="rail-head">Derived decisions</div>

        <div
          className={`yield-card${q.potability === 'not-potable' ? ' is-warn' : ''}`}
        >
          <div className="eyebrow">Potability verdict</div>
          <div className="yield-value is-text">{VERDICT_LABEL[q.potability]}</div>
          <div className="yield-method">{q.verdict.detail}</div>
          <div className="chip-row">
            <span className="chip">balance {q.balanceError.toFixed(1)} %</span>
            <span className="chip">{q.waterType}</span>
          </div>
        </div>

        <div className="tile-row">
          <div className="tile">
            <div className="tile-label">Corrosion risk</div>
            <div className={`tile-value${q.corrosion.level !== 'low' ? ' is-warn' : ''}`}>
              {q.corrosion.level[0].toUpperCase() + q.corrosion.level.slice(1)}
            </div>
            <div className="tile-sub">LSI {q.lsi.toFixed(1)}</div>
          </div>
          <div className="tile">
            <div className="tile-label">Hardness</div>
            <div className="tile-value">
              {(50 * (q.meq.ca + q.meq.mg)).toFixed(0)}
            </div>
            <div className="tile-sub">mg/L as CaCO₃ · soft</div>
          </div>
        </div>

        <div className={`verdict is-${q.corrosion.level === 'low' ? 'ok' : 'warn'}`}>
          <span className={`badge is-${q.corrosion.level === 'low' ? 'ok' : 'warn'}`}>
            {q.corrosion.level === 'low' ? '✓' : '!'}
          </span>
          <div>
            <div className="verdict-title">Handpump material specification</div>
            <div className="verdict-detail">{q.corrosion.advice}</div>
          </div>
        </div>

        <div className="rail-head">Checks against WHO &amp; the analysis</div>
        <ChecksList checks={q.checks} />

        <div className="hint">
          <div className="hint-title">Iron at 0.40 mg/L</div>
          <div className="hint-body">
            Aesthetic, not health-based — but it stains laundry and gives a
            metallic taste, and communities abandon sources over it. Aeration and
            filtration at the wellhead, or accept and monitor. The corrosion
            finding above will make it worse if galvanised components are used.
          </div>
        </div>

        <div className="spacer" />

        <SignOff
          stage="quality"
          recommended={VERDICT_LABEL[q.potability]}
          acceptLabel="verdict"
          writesTo="accepting writes to the water-quality and handover reports"
          decision={decision}
          clean={clean}
          onDecide={onDecide}
          override={{
            kind: 'choice',
            label: 'Certified verdict',
            options: [
              'Potable',
              'Potable — aesthetic exceedance',
              'Potable after treatment',
              'Not potable without treatment',
            ],
            start: VERDICT_LABEL[q.potability],
          }}
        />
      </aside>
    </div>
  );
}
