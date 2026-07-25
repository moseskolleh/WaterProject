/**
 * The one depth <-> pixel mapping in the application.
 *
 * Every column in the spine — VES model, lithology, construction, hydraulics —
 * calls `y()` and nothing else. That is what makes the alignment true rather
 * than drawn: a screen that misses a water strike cannot look like it hits one.
 */

/** Pixels per metre of depth. */
export const PX_PER_M = 10;

/** Depth at the foot of the track, metres. */
export const TRACK_DEPTH_M = 48;

/** Height of every depth-indexed track, pixels. */
export const TRACK_H = TRACK_DEPTH_M * PX_PER_M;

/** Depth (m) -> offset from the top of a track (px). */
export function y(depth: number): number {
  return depth * PX_PER_M;
}

/** Interval thickness (m) -> height (px). Open-ended intervals run to the foot. */
export function h(top: number, base: number | null): number {
  return y(base ?? TRACK_DEPTH_M) - y(top);
}

/** Offset from the top of a track (px) -> depth (m). */
export function depthAt(px: number): number {
  return px / PX_PER_M;
}

/** Ruler ticks: labelled every 10 m, minor every 5 m. */
export const MAJOR_TICKS = [0, 10, 20, 30, 40];
export const MINOR_TICKS = [5, 15, 25, 35, 45];

/**
 * Resistivity -> width of the VES model bar, as a fraction of the column.
 * Log-linear, fitted to the layer widths in the design study.
 */
export function rhoWidth(rho: number): number {
  const w = 0.392 * Math.log10(rho) - 0.4;
  return Math.min(0.96, Math.max(0.12, w));
}
