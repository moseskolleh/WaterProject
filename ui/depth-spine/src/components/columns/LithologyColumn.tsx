import type { Scale } from '../../domain/scale';
import type { LithologyInterval } from '../../domain/view';

interface Props {
  scale: Scale;
  units: LithologyInterval[];
  strikes: number[];
}

/** Fill chosen from the driller's own words, not from an invented rock code. */
function fillFor(description: string, aquifer: boolean): string {
  const text = description.toLowerCase();
  if (aquifer) return 'fill-fractured';
  if (text.includes('topsoil') || text.includes('laterit')) return 'fill-topsoil';
  if (text.includes('clay')) return 'fill-clayey-sand';
  if (text.includes('saprolite') || text.includes('weathered')) return 'fill-saprolite';
  return 'fill-fresh';
}

interface Placed<T> {
  item: T;
  /** Where the label is drawn. */
  y: number;
  /** Where it belongs — a leader line is drawn when the two differ. */
  anchor: number;
}

/**
 * Lay labels out down the column without overlap.
 *
 * A 70 m hole logged in 5 m units puts fourteen descriptions in the space of
 * eight, so labels have to be nudged and connected to their interval with a
 * leader rather than left to overprint each other. Water strikes are placed
 * first: they are single depths and must stay on their line.
 */
function declutter<T>(
  items: { at: number; height: number; item: T }[],
  limit: number,
  reserved: number[] = [],
): Placed<T>[] {
  const out: Placed<T>[] = [];
  let cursor = 0;
  for (const { at, height, item } of items) {
    let y = Math.max(at, cursor + height / 2);
    // Step over any reserved band (a strike callout) this label would hit.
    for (const r of reserved) {
      if (Math.abs(y - r) < height / 2 + 7) y = r + height / 2 + 7;
    }
    y = Math.min(y, limit - height / 2);
    out.push({ item, y, anchor: at });
    cursor = y + height / 2 + 2;
  }
  return out;
}

// Descriptions are clamped to one line so every label is the same height and
// the declutter spacing below is exact. The full text stays on hover and on
// the block itself — truncating it in the lane is better than overprinting it.
const LABEL_H = 30;

export function LithologyColumn({ scale, units, strikes }: Props) {
  const strikeYs = strikes.map((d) => scale.y(d));
  const placed = declutter(
    units.map((u) => ({
      at: scale.y(u.top) + scale.h(u.top, u.base) / 2,
      height: LABEL_H,
      item: u,
    })),
    scale.height,
    strikeYs,
  );

  return (
    <div className="col-litho">
      <div className="col-head">Lithology — cuttings</div>
      <div className="track" style={{ height: scale.height }}>
        {units.map((u) => (
          <div
            key={`${u.top}-${u.base}`}
            className={`litho-block ${fillFor(u.description, u.aquifer)}${
              u.aquifer ? ' is-aquifer' : ''
            }`}
            style={{ top: scale.y(u.top), height: scale.h(u.top, u.base) }}
            title={`${u.top}–${u.base} m · ${u.description}`}
          />
        ))}

        {placed.map(({ item: u, y, anchor }) => (
          <div key={`label-${u.top}`}>
            {Math.abs(y - anchor) > 2 && (
              <svg className="leader" style={{ top: Math.min(y, anchor) }}
                width={12} height={Math.abs(y - anchor) || 1}>
                <line
                  x1={0}
                  y1={anchor < y ? 0 : Math.abs(y - anchor)}
                  x2={12}
                  y2={anchor < y ? Math.abs(y - anchor) : 0}
                  stroke="rgba(255,255,255,.18)"
                />
              </svg>
            )}
            <div
              className={`litho-label${u.aquifer ? ' is-aquifer' : ''}`}
              style={{ top: y }}
              title={u.description}
            >
              <div className="litho-name">{u.description}</div>
              <div className="litho-note">
                {u.top}–{u.base} m
              </div>
            </div>
          </div>
        ))}

        {strikes.map((d) => (
          <div key={d}>
            <div className="strike-line" style={{ top: scale.y(d) }} />
            <div className="strike-label" style={{ top: scale.y(d) }}>
              strike {d.toFixed(1)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
