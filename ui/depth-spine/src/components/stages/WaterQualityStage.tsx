import type { DecisionRecord } from '../../domain/decision';
import type { QualityBlock } from '../../domain/view';
import { FlagsList } from '../FlagsList';
import { SignOff } from '../SignOff';
import { GuidelineSpine } from '../charts/GuidelineSpine';
import { PiperDiagram } from '../charts/PiperDiagram';
import { StiffDiagram } from '../charts/StiffDiagram';

interface Props {
  quality: QualityBlock;
  decision: DecisionRecord | null;
  readOnly?: boolean;
  onDecide: (record: DecisionRecord | null) => void;
}

function headline(q: QualityBlock): { label: string; tone: 'ok' | 'warn' | 'error' } {
  if (q.healthExceedances.length) return { label: 'Not suitable for drinking', tone: 'error' };
  if (q.nationalExceedances.length)
    return { label: 'Fails the national standard', tone: 'warn' };
  if (q.aestheticExceedances.length)
    return { label: 'Potable — acceptability exceeded', tone: 'warn' };
  return { label: 'Complies', tone: 'ok' };
}

export function WaterQualityStage({
  quality: q,
  decision,
  readOnly = false,
  onDecide,
}: Props) {
  const verdict = headline(q);
  const judged = q.rows.filter((r) => r.status !== 'no_guideline');
  const within = judged.filter((r) => !r.status.startsWith('exceeds'));
  const clean = verdict.tone === 'ok';
  const c = q.corrosivity;

  return (
    <div className="ws-body">
      <div className="spine">
        <div className="metrics">
          <div className="metric-row">
            <div>
              <div className="metric-label">Sampled</div>
              <div className="metric-value is-small">{q.sampleDate || '—'}</div>
            </div>
            <div>
              <div className="metric-label">Within limits</div>
              <div className="metric-value">
                {within.length} / {judged.length}
              </div>
            </div>
            <div>
              <div className="metric-label">Health exceedances</div>
              <div
                className={`metric-value${q.healthExceedances.length ? ' is-error' : ''}`}
              >
                {q.healthExceedances.length || 'none'}
              </div>
            </div>
            {q.ionic && (
              <div>
                <div className="metric-label">Ionic balance</div>
                <div className="metric-value">{q.ionic.errorPercent} %</div>
              </div>
            )}
            {c && (
              <div>
                <div className="metric-label">Corrosivity</div>
                <div className={`metric-value is-small${c.isAggressive ? ' is-warn' : ''}`}>
                  {c.classification}
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="quality-body">
          <div className="quality-main">
            <div className="panel-head">
              Every determinand as a multiple of its own binding limit
            </div>
            <GuidelineSpine rows={q.rows} />
            <div className="panel-foot">
              Limits from the toolkit's standards table — WHO health-based guideline
              values, WHO acceptability values and the national standard column,
              whichever binds. {q.laboratory && `Analysis by ${q.laboratory}.`}
            </div>

            <div className="quality-row">
              {q.ionic && (
                <div className="panel">
                  <div className="panel-head">Ionic balance</div>
                  <div className="balance">
                    <div className="balance-side">
                      <span className="balance-label">Σ cations</span>
                      <span className="balance-value">{q.ionic.cationsMeq}</span>
                    </div>
                    <div className="balance-bar">
                      <span
                        className={`balance-fill${Math.abs(q.ionic.errorPercent) > 5 ? ' is-warn' : ''}`}
                        style={{
                          width: `${Math.min(Math.abs(q.ionic.errorPercent) * 8, 50)}%`,
                          left: q.ionic.errorPercent < 0 ? 'auto' : '50%',
                          right: q.ionic.errorPercent < 0 ? '50%' : 'auto',
                        }}
                      />
                    </div>
                    <div className="balance-side is-right">
                      <span className="balance-label">Σ anions</span>
                      <span className="balance-value">{q.ionic.anionsMeq}</span>
                    </div>
                  </div>
                  <div className="panel-foot">
                    Error {q.ionic.errorPercent > 0 ? '+' : ''}
                    {q.ionic.errorPercent} % against a ±5 % acceptance limit
                    {Math.abs(q.ionic.errorPercent) <= 5
                      ? ' — the analysis is internally consistent, so the rest of this page can be relied on.'
                      : ' — the analysis does not balance; treat every figure here with caution.'}
                    {q.ionic.usedAlkalinity && ' Bicarbonate inferred from alkalinity.'}
                  </div>
                </div>
              )}

              {c && (
                <div className="panel">
                  <div className="panel-head">Corrosivity indices</div>
                  <div className="provenance">
                    <div className="mini-row">
                      <span>Langelier (LSI)</span>
                      <span>{c.lsi ?? '—'}</span>
                    </div>
                    <div className="mini-row">
                      <span>Ryznar (RSI)</span>
                      <span>{c.rsi ?? '—'}</span>
                    </div>
                    <div className="mini-row">
                      <span>Aggressive index</span>
                      <span>{c.aggressiveIndex ?? '—'}</span>
                    </div>
                    <div className="mini-row">
                      <span>Larson-Skold</span>
                      <span>{c.larsonSkold ?? '—'}</span>
                    </div>
                    <div className="mini-row is-total">
                      <span>Classification</span>
                      <span>{c.classification}</span>
                    </div>
                  </div>
                  <div className="panel-foot">{c.verdict}</div>
                </div>
              )}
            </div>
          </div>

          {q.piper && (
            <div className="quality-side">
              <div className="panel">
                <div className="panel-head">Piper — hydrochemical facies</div>
                <PiperDiagram data={q.piper} />
              </div>
              <div className="panel">
                <div className="panel-head">Stiff — ionic shape</div>
                <StiffDiagram data={q.piper} />
              </div>
            </div>
          )}
        </div>
      </div>

      <aside className="rail">
        <div className="rail-head">Derived decisions</div>

        <div className={`yield-card is-${verdict.tone}`}>
          <div className="eyebrow">Suitability</div>
          <div className="yield-value is-text">{verdict.label}</div>
          <div className="yield-method">{q.verdict}</div>
          {q.wqi && (
            <div className="chip-row">
              <span className="chip">WQI {q.wqi.value}</span>
              <span className="chip">{q.wqi.rating}</span>
            </div>
          )}
        </div>

        {c && (
          <div className={`verdict is-${c.isAggressive ? 'warn' : 'ok'}`}>
            <span className={`badge is-${c.isAggressive ? 'warning' : 'ok'}`}>
              {c.isAggressive ? '!' : '✓'}
            </span>
            <div>
              <div className="verdict-title">Handpump materials</div>
              <div className="verdict-detail">
                {c.materialsNote || c.verdict}
              </div>
            </div>
          </div>
        )}

        <div className="rail-head">Exceedances</div>
        <div className="checks">
          {[
            ['Health-based', q.healthExceedances, 'error'],
            ['National standard', q.nationalExceedances, 'warning'],
            ['Acceptability', q.aestheticExceedances, 'warning'],
          ].map(([label, list, level]) => {
            const names = list as string[];
            return (
              <div className="check" key={label as string}>
                <span className={`badge is-${names.length ? (level as string) : 'ok'}`}>
                  {names.length ? '!' : '✓'}
                </span>
                <span className="check-label">{label as string}</span>
                <span className={`check-value${names.length ? ' is-warn' : ''}`}>
                  {names.length ? names.join(', ') : 'none'}
                </span>
              </div>
            );
          })}
        </div>

        <div className="rail-head">Flags on this analysis</div>
        <FlagsList flags={q.flags} empty="No flags raised on the sample." />

        {c && c.assumptions.length > 0 && (
          <div className="hint">
            <div className="hint-title">Assumptions behind the indices</div>
            <div className="hint-body">{c.assumptions.join(' ')}</div>
          </div>
        )}

        <div className="spacer" />

        <SignOff
          stage="quality"
          readOnly={readOnly}
          recommended={verdict.label}
          acceptLabel="the verdict"
          writesTo="accepting writes to the water-quality and handover reports"
          decision={decision}
          clean={clean}
          onDecide={onDecide}
          override={{
            kind: 'choice',
            label: 'Certified verdict',
            options: [
              'Complies',
              'Potable — acceptability exceeded',
              'Potable after treatment',
              'Fails the national standard',
              'Not suitable for drinking',
            ],
            start: verdict.label,
          }}
        />
      </aside>
    </div>
  );
}
