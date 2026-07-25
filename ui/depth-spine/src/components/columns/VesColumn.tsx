import { h, rhoWidth, TRACK_H, y } from '../../domain/scale';
import type { VesLayer } from '../../domain/types';

/** Fill / edge treatment per layer, top to bottom, with the aquifer picked out. */
const PALETTE = [
  { bg: 'oklch(0.58 0.06 60 / .5)', top: 'rgba(255,255,255,.18)', edge: 'oklch(0.75 0.09 60)' },
  { bg: 'oklch(0.55 0.05 60 / .38)', top: 'rgba(255,255,255,.14)', edge: 'oklch(0.7 0.08 60)' },
  { bg: 'oklch(0.5 0.05 30 / .35)', top: 'rgba(255,255,255,.14)', edge: 'oklch(0.66 0.09 30)' },
  { bg: 'rgba(255,255,255,.11)', top: 'rgba(255,255,255,.3)', edge: 'rgba(255,255,255,.55)' },
];

const AQUIFER = {
  bg: 'oklch(0.72 0.13 190 / .3)',
  top: 'oklch(0.72 0.13 190 / .6)',
  edge: 'oklch(0.75 0.13 190)',
};

/** Bar width encodes resistivity on a log scale; height is true depth. */
export function VesColumn({ layers }: { layers: VesLayer[] }) {
  let plain = 0;
  return (
    <div className="col-ves">
      <div className="col-head">VES model ρ</div>
      <div className="track" style={{ height: TRACK_H }}>
        {layers.map((l) => {
          const skin = l.aquifer ? AQUIFER : PALETTE[Math.min(plain++, PALETTE.length - 1)];
          const height = h(l.top, l.base);
          return (
            <div key={l.top}>
              <div
                className="ves-layer"
                style={{
                  top: y(l.top),
                  height,
                  width: `${(rhoWidth(l.rho) * 100).toFixed(0)}%`,
                  background: skin.bg,
                  borderTopColor: skin.top,
                  borderRightColor: skin.edge,
                }}
              />
              {height >= 40 && (
                <div
                  className={`ves-rho${l.aquifer ? ' is-aquifer' : ''}`}
                  style={{ top: y(l.top) + height / 2 }}
                >
                  {l.rho}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
