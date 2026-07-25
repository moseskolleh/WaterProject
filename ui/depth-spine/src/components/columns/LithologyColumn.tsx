import { h, TRACK_H, y } from '../../domain/scale';
import type { LithologyUnit } from '../../domain/types';

/** Fracture traces drawn inside the fractured-granite block. */
const FRACTURES = [
  { at: 0.082, rotate: 24, opacity: 0.75 },
  { at: 0.306, rotate: -18, opacity: 0.55 },
  { at: 0.506, rotate: 30, opacity: 0.75 },
  { at: 0.741, rotate: -22, opacity: 0.6 },
];

interface Props {
  units: LithologyUnit[];
  strikes: number[];
}

/**
 * Unit names share a lane with the water-strike callouts, so nudge a name clear
 * of any strike it would sit on top of rather than letting the two overprint.
 */
function labelY(centre: number, strikes: number[]): number {
  const clash = (at: number) => strikes.some((s) => Math.abs(y(s) - at) < 22);
  if (!clash(centre)) return centre;
  for (const offset of [-26, 26, -44, 44]) {
    if (!clash(centre + offset)) return centre + offset;
  }
  return centre;
}

/** The drillers' cuttings log, plus the depths at which water was struck. */
export function LithologyColumn({ units, strikes }: Props) {
  return (
    <div className="col-litho">
      <div className="col-head">Lithology — cuttings</div>
      <div className="track" style={{ height: TRACK_H }}>
        {units.map((u) => {
          const height = h(u.top, u.base);
          const thickness = (u.base ?? 0) - u.top;
          return (
            <div key={u.top}>
              <div
                className={`litho-block fill-${u.fill}${u.aquifer ? ' is-aquifer' : ''}`}
                style={{ top: y(u.top), height }}
              >
                {u.fill === 'fractured' &&
                  FRACTURES.map((f) => (
                    <div
                      key={f.at}
                      className="fracture"
                      style={{
                        top: height * f.at,
                        transform: `rotate(${f.rotate}deg)`,
                        background: `oklch(0.8 0.11 190 / ${f.opacity})`,
                      }}
                    />
                  ))}
              </div>
              <div
                className={`litho-label${u.aquifer ? ' is-aquifer' : ''}`}
                style={{ top: labelY(y(u.top) + height / 2, strikes) }}
              >
                <div className="litho-name">{u.name}</div>
                {u.note && (
                  <div className="litho-note">
                    {u.aquifer && u.base
                      ? `${u.note} · ${thickness.toFixed(0)} m`
                      : u.note}
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {strikes.map((d) => (
          <div key={d}>
            <div className="strike-line" style={{ top: y(d) }} />
            <div className="strike-label" style={{ top: y(d) }}>
              strike {d.toFixed(1)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
