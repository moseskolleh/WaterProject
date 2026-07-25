/**
 * The one depth <-> pixel mapping in the application.
 *
 * Every column calls the same scale, which is what makes the alignment between
 * the cuttings log, the casing string and the water levels true rather than
 * drawn: a screen that misses a water strike cannot be rendered as though it
 * hits one. The scale is built from the payload, so a 70 m hole and a 30 m hole
 * both fill the track.
 */

export const TRACK_H = 560;

export interface Scale {
  /** Depth (m) -> offset from the top of a track (px). */
  y: (depth: number) => number;
  /** Interval thickness (m) -> height (px). */
  h: (top: number, base: number) => number;
  /** Offset (px) -> depth (m). */
  depthAt: (px: number) => number;
  pxPerM: number;
  height: number;
  domain: number;
  majorTicks: number[];
  minorTicks: number[];
}

/** A tick step that gives roughly six to eight labels over the hole. */
function tickStep(domain: number): number {
  for (const step of [1, 2, 5, 10, 20, 25, 50, 100]) {
    if (domain / step <= 8) return step;
  }
  return 100;
}

export function makeScale(domain: number, height = TRACK_H): Scale {
  const pxPerM = height / domain;
  const step = tickStep(domain);
  const majorTicks: number[] = [];
  for (let d = 0; d <= domain; d += step) majorTicks.push(d);
  const minorTicks: number[] = [];
  for (let d = step / 2; d <= domain; d += step) minorTicks.push(d);

  return {
    y: (depth) => depth * pxPerM,
    h: (top, base) => (base - top) * pxPerM,
    depthAt: (px) => px / pxPerM,
    pxPerM,
    height,
    domain,
    majorTicks,
    minorTicks,
  };
}
