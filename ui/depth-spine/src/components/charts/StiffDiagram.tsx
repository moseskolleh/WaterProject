import type { MeqSet } from '../../domain/quality';

/**
 * Stiff diagram — the shape of the water. Cations left, anions right, each
 * axis in meq/L, so two samples can be compared at a glance.
 */

const W = 250;
const H = 108;
const CX = W / 2;
const ROWS = 3;
const ROW_H = 26;
const TOP = 18;
const HALF = 96; // pixels for the full-scale value

export function StiffDiagram({ m, scaleMax = 1.5 }: { m: MeqSet; scaleMax?: number }) {
  const rows: { left: [string, number]; right: [string, number] }[] = [
    { left: ['Na+K', m.naK], right: ['Cl', m.cl] },
    { left: ['Ca', m.ca], right: ['HCO₃', m.hco3] },
    { left: ['Mg', m.mg], right: ['SO₄', m.so4] },
  ];

  const x = (v: number, side: -1 | 1) =>
    CX + side * Math.min(v / scaleMax, 1) * HALF;
  const y = (i: number) => TOP + i * ROW_H;

  const polygon = [
    ...rows.map((r, i) => `${x(r.left[1], -1)},${y(i)}`),
    ...rows.map((r, i) => `${x(r.right[1], 1)},${y(i)}`).reverse(),
  ].join(' ');

  const label = 'rgba(255,255,255,.42)';

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: W, height: H }} role="img"
      aria-label="Stiff diagram of the water sample">
      {rows.map((_, i) => (
        <line
          key={i}
          x1={CX - HALF}
          y1={y(i)}
          x2={CX + HALF}
          y2={y(i)}
          stroke="rgba(255,255,255,.09)"
        />
      ))}
      <line
        x1={CX}
        y1={y(0) - 6}
        x2={CX}
        y2={y(ROWS - 1) + 6}
        stroke="rgba(255,255,255,.22)"
      />

      <polygon
        points={polygon}
        fill="oklch(0.72 0.13 190 / .28)"
        stroke="oklch(0.75 0.13 190)"
        strokeWidth={1.4}
      />

      <g fontFamily="'IBM Plex Mono', monospace" fontSize={9} fill={label}>
        {rows.map((r, i) => (
          <g key={r.left[0]}>
            <text x={CX - HALF - 6} y={y(i) + 3} textAnchor="end">
              {r.left[0]}
            </text>
            <text x={CX + HALF + 6} y={y(i) + 3}>
              {r.right[0]}
            </text>
          </g>
        ))}
        <text x={CX} y={H - 6} textAnchor="middle" fontSize={8.5}>
          meq/L · {scaleMax.toFixed(1)} full scale
        </text>
      </g>
    </svg>
  );
}
