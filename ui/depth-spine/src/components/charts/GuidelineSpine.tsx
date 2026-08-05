import type { QualityRow } from '../../domain/view';

/**
 * The guideline spine.
 *
 * Same idea as the depth spine: put everything on one shared axis so the
 * judgement is a line crossed rather than two numbers compared. Here the axis
 * is the guideline itself — each determinand is drawn as a multiple of its own
 * binding limit, computed in Python from the standards table, so one vertical
 * line separates compliant from not.
 */

const MIN = 0.005;
const MAX = 5;
const SPAN = Math.log10(MAX) - Math.log10(MIN);
const TICKS = [0.01, 0.1, 1];

function pos(ratio: number): number {
  const clamped = Math.max(MIN, Math.min(MAX, ratio));
  return (Math.log10(clamped) - Math.log10(MIN)) / SPAN;
}

const BASIS: Record<string, string> = {
  exceeds_health: 'health',
  exceeds_national: 'national',
  exceeds_aesthetic: 'acceptability',
  indeterminate: 'not evaluable',
  not_measured: 'not measured',
};

function barClass(row: QualityRow): string {
  // A national limit is law, not taste, so it reads as badly as a health
  // exceedance. Anything the toolkit could not grade is neither: drawing an
  // unevaluable row green was the same fail-open the verdict used to have.
  if (row.status === 'exceeds_health' || row.status === 'exceeds_national')
    return 'is-error';
  if (row.status === 'exceeds_aesthetic') return 'is-warn';
  if (row.status === 'indeterminate' || row.status === 'not_measured')
    return 'is-unknown';
  return 'is-ok';
}

export function GuidelineSpine({ rows }: { rows: QualityRow[] }) {
  // Determinands with no guideline are not judged, so they are not plotted;
  // they stay in the table, where they belong.
  const plotted = rows
    .filter((r) => r.status !== 'no_guideline' && r.status !== 'not_measured')
    .sort((a, b) => (b.ratio ?? -1) - (a.ratio ?? -1));

  return (
    <div className="gspine">
      <div className="gspine-axis">
        <span className="gspine-label" />
        <div className="gspine-plot">
          {TICKS.map((t) => (
            <span
              key={t}
              className={`gspine-tick${t === 1 ? ' is-guideline' : ''}`}
              style={{ left: `${pos(t) * 100}%` }}
            >
              {t === 1 ? 'limit' : `${t}×`}
            </span>
          ))}
        </div>
        <span className="gspine-value" />
      </div>

      <div className="gspine-rows">
        {plotted.map((r) => {
          const exceeds = r.status.startsWith('exceeds');
          return (
            <div className="gspine-row" key={r.parameter} title={r.remark}>
              <span className="gspine-label">
                {r.parameter}
                <em>
                  {exceeds ? BASIS[r.status] : r.limitName || (r.belowDetection ? 'nd' : '')}
                </em>
              </span>
              <div className="gspine-plot">
                {TICKS.map((t) => (
                  <span
                    key={t}
                    className={`gspine-gridline${t === 1 ? ' is-guideline' : ''}`}
                    style={{ left: `${pos(t) * 100}%` }}
                  />
                ))}
                {r.belowDetection ? (
                  <span className="gspine-nil">below detection</span>
                ) : r.ratio === null ? (
                  <span className={`gspine-nil${exceeds ? ' is-warn' : ''}`}>
                    {exceeds ? 'detected — limit is nil' : 'not detected'}
                  </span>
                ) : (
                  <span
                    className={`gspine-bar ${barClass(r)}`}
                    style={{ width: `${pos(r.ratio) * 100}%` }}
                  />
                )}
              </div>
              <span className={`gspine-value${exceeds ? ' is-warn' : ''}`}>
                {r.value ?? '—'} <em>{r.unit}</em>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
