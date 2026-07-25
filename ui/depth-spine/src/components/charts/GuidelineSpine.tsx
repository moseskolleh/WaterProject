import type { DeterminandResult } from '../../domain/quality';

/**
 * The guideline spine.
 *
 * Same idea as the depth spine: put everything on one shared axis so the
 * judgement is a line crossed rather than a pair of numbers compared. Here the
 * axis is the guideline value itself — every determinand is drawn as a multiple
 * of its own limit, so a single vertical line separates compliant from not.
 */

const MIN = 0.005;
const MAX = 3;
const SPAN = Math.log10(MAX) - Math.log10(MIN);

/** Ratio -> fraction across the plot, log scale. */
function pos(ratio: number): number {
  const clamped = Math.max(MIN, Math.min(MAX, ratio));
  return (Math.log10(clamped) - Math.log10(MIN)) / SPAN;
}

const TICKS = [0.01, 0.1, 1];

export function GuidelineSpine({ results }: { results: DeterminandResult[] }) {
  const rows = results
    .filter((r) => r.status !== 'none' && r.whoMin === undefined)
    .sort((a, b) => (b.ratio ?? 0) - (a.ratio ?? 0));

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
              {t === 1 ? 'guideline' : `${t}×`}
            </span>
          ))}
        </div>
        <span className="gspine-value" />
      </div>

      <div className="gspine-rows">
        {rows.map((r) => {
          const nil = r.who === 0;
          return (
            <div className="gspine-row" key={r.id}>
              <span className="gspine-label">
                {r.label}
                <em>{r.basis === 'health' ? 'health' : r.basis === 'microbiological' ? 'micro' : 'aesthetic'}</em>
              </span>
              <div className="gspine-plot">
                {TICKS.map((t) => (
                  <span
                    key={t}
                    className={`gspine-gridline${t === 1 ? ' is-guideline' : ''}`}
                    style={{ left: `${pos(t) * 100}%` }}
                  />
                ))}
                {nil ? (
                  <span className="gspine-nil">not detected</span>
                ) : (
                  <span
                    className={`gspine-bar is-${r.status}`}
                    style={{ width: `${pos(r.ratio ?? MIN) * 100}%` }}
                  />
                )}
              </div>
              <span className={`gspine-value${r.status === 'warn' ? ' is-warn' : ''}`}>
                {r.value} <em>{r.unit}</em>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
