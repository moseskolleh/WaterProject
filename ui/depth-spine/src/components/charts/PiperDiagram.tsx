import type { PiperData } from '../../domain/view';

/**
 * Trilinear Piper plot, drawn from the milliequivalents the ionic balance
 * already computed.
 *
 * The construction only works when the gap between the triangles equals their
 * side: that is what puts the diamond's lower vertex at apex height and makes
 * the 60-degree projection rays land where they should.
 */

const T = 90;
const H = Math.sqrt(3) / 2;
const PAD = 18;
const X0 = PAD;
const X1 = PAD + 2 * T;
const DIAMOND_H = T * Math.sqrt(3);
const CX = X0 + 1.5 * T;
const BASE_Y = PAD + DIAMOND_H + T * H;
const W = 3 * T + PAD * 2;
const HGT = BASE_Y + 16;

type P = { x: number; y: number };

function intersect(p1: P, d1: P, p2: P, d2: P): P {
  const det = d1.x * -d2.y - -d2.x * d1.y;
  const t = ((p2.x - p1.x) * -d2.y - -d2.x * (p2.y - p1.y)) / det;
  return { x: p1.x + d1.x * t, y: p1.y + d1.y * t };
}

function triangle(x: number) {
  return `${x},${BASE_Y} ${x + T},${BASE_Y} ${x + T / 2},${BASE_Y - T * H}`;
}

function gridLines(x: number) {
  const out: [P, P][] = [];
  for (let i = 1; i < 5; i++) {
    const f = i / 5;
    out.push([
      { x: x + (T * f) / 2, y: BASE_Y - T * H * f },
      { x: x + T - (T * f) / 2, y: BASE_Y - T * H * f },
    ]);
    out.push([
      { x: x + T * f, y: BASE_Y },
      { x: x + T * f + (T * (1 - f)) / 2, y: BASE_Y - T * H * (1 - f) },
    ]);
    out.push([
      { x: x + T * f, y: BASE_Y },
      { x: x + (T * f) / 2, y: BASE_Y - T * H * f },
    ]);
  }
  return out;
}

export function PiperDiagram({ data }: { data: PiperData }) {
  const p = data.percent;
  const cation: P = { x: X0 + (p.naK + p.mg / 2) * T, y: BASE_Y - p.mg * T * H };
  const anion: P = { x: X1 + (p.cl + p.so4 / 2) * T, y: BASE_Y - p.so4 * T * H };
  const projected = intersect(cation, { x: 0.5, y: -H }, anion, { x: -0.5, y: -H });

  const bottom: P = { x: CX, y: BASE_Y - T * H };
  const diamond = [
    bottom,
    { x: CX + T / 2, y: bottom.y - DIAMOND_H / 2 },
    { x: CX, y: bottom.y - DIAMOND_H },
    { x: CX - T / 2, y: bottom.y - DIAMOND_H / 2 },
  ];

  const grid = 'rgba(255,255,255,.07)';
  const edge = 'rgba(255,255,255,.28)';
  const label = 'rgba(255,255,255,.45)';

  return (
    <svg
      viewBox={`0 0 ${W} ${HGT}`}
      style={{ width: W, height: HGT }}
      role="img"
      aria-label="Piper trilinear diagram of the water sample"
    >
      {[X0, X1].map((x) => (
        <g key={x}>
          {gridLines(x).map(([a, b], i) => (
            <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={grid} />
          ))}
          <polygon points={triangle(x)} fill="none" stroke={edge} />
        </g>
      ))}

      {[1, 2, 3, 4].map((i) => {
        const f = i / 5;
        return (
          <g key={f} stroke={grid}>
            <line
              x1={CX - (T / 2) * f}
              y1={bottom.y - (DIAMOND_H / 2) * f}
              x2={CX + (T / 2) * (1 - f)}
              y2={bottom.y - DIAMOND_H + (DIAMOND_H / 2) * (1 - f)}
            />
            <line
              x1={CX + (T / 2) * f}
              y1={bottom.y - (DIAMOND_H / 2) * f}
              x2={CX - (T / 2) * (1 - f)}
              y2={bottom.y - DIAMOND_H + (DIAMOND_H / 2) * (1 - f)}
            />
          </g>
        );
      })}
      <polygon points={diamond.map((d) => `${d.x},${d.y}`).join(' ')} fill="none" stroke={edge} />

      <line x1={cation.x} y1={cation.y} x2={projected.x} y2={projected.y}
        stroke="oklch(0.72 0.13 190 / .4)" strokeDasharray="3 3" />
      <line x1={anion.x} y1={anion.y} x2={projected.x} y2={projected.y}
        stroke="oklch(0.72 0.13 190 / .4)" strokeDasharray="3 3" />

      {[cation, anion].map((pt, i) => (
        <circle key={i} cx={pt.x} cy={pt.y} r={3} fill="oklch(0.72 0.13 190)" />
      ))}
      <circle cx={projected.x} cy={projected.y} r={5} fill="oklch(0.78 0.13 190)"
        stroke="#12181a" strokeWidth={1.5} />

      <g fontFamily="'IBM Plex Mono', monospace" fontSize={8.5} fill={label}>
        <text x={X0 - 2} y={BASE_Y + 11} textAnchor="middle">Ca</text>
        <text x={X0 + T + 2} y={BASE_Y + 11} textAnchor="middle">Na+K</text>
        <text x={X0 + T / 2 - 7} y={BASE_Y - T * H - 5} textAnchor="end">Mg</text>
        <text x={X1 - 2} y={BASE_Y + 11} textAnchor="middle">HCO₃</text>
        <text x={X1 + T + 2} y={BASE_Y + 11} textAnchor="middle">Cl</text>
        <text x={X1 + T / 2 + 7} y={BASE_Y - T * H - 5}>SO₄</text>
        <text x={CX - T / 2 - 5} y={bottom.y - DIAMOND_H / 2 + 3} textAnchor="end">Ca+Mg</text>
        <text x={CX + T / 2 + 5} y={bottom.y - DIAMOND_H / 2 + 3}>Cl+SO₄</text>
      </g>
    </svg>
  );
}
