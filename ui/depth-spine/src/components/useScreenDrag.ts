import { useCallback, useEffect, useRef, useState } from 'react';
import type { Scale } from '../domain/scale';
import type { ScreenLimits } from '../domain/view';

export interface Interval {
  top: number;
  base: number;
}

export type Edge = 'top' | 'base' | 'body';

export interface DragState {
  index: number;
  edge: Edge;
}

interface Options {
  screens: Interval[];
  limits: ScreenLimits;
  scale: Scale;
  /** Local, per-frame: moves the drawing only. */
  onPreview: (screens: Interval[]) => void;
  /** On release: hands the intervals to Python to re-derive everything. */
  onCommit: (screens: Interval[]) => void;
}

const round = (n: number) => Math.round(n * 10) / 10;

/**
 * Direct manipulation of the screened intervals.
 *
 * Dragging moves the drawing locally, because a pointer has to feel attached to
 * what it is dragging. Releasing hands the intervals to Python, which re-runs
 * design_borehole and everything downstream of it. No hydrogeological rule is
 * applied here — the clamping below is only enough to keep the drawing sane
 * while the pointer is down; the real validation is the designer's.
 */
export function useScreenDrag({ screens, limits, scale, onPreview, onCommit }: Options) {
  const [dragging, setDragging] = useState<DragState | null>(null);
  const origin = useRef({ y: 0, screens: [] as Interval[] });
  const latest = useRef<Interval[]>(screens);

  const clamp = useCallback(
    (list: Interval[]): Interval[] =>
      list.map((s) => {
        const top = Math.max(limits.top, Math.min(s.top, limits.base - limits.minLength));
        const base = Math.max(top + limits.minLength, Math.min(s.base, limits.base));
        return { top: round(top), base: round(base) };
      }),
    [limits],
  );

  const start = useCallback(
    (index: number, edge: Edge) => (e: React.PointerEvent) => {
      e.preventDefault();
      e.stopPropagation();
      (e.target as Element).setPointerCapture?.(e.pointerId);
      origin.current = { y: e.clientY, screens: screens.map((s) => ({ ...s })) };
      latest.current = screens;
      setDragging({ index, edge });
    },
    [screens],
  );

  useEffect(() => {
    if (!dragging) return;

    const move = (e: PointerEvent) => {
      const dm = round(scale.depthAt(e.clientY - origin.current.y));
      const next = origin.current.screens.map((s, i) => {
        if (i !== dragging.index) return { ...s };
        if (dragging.edge === 'top') return { top: round(s.top + dm), base: s.base };
        if (dragging.edge === 'base') return { top: s.top, base: round(s.base + dm) };
        return { top: round(s.top + dm), base: round(s.base + dm) };
      });
      const clamped = clamp(next);
      latest.current = clamped;
      onPreview(clamped);
    };

    const end = () => {
      setDragging(null);
      onCommit(latest.current);
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
    };
  }, [dragging, scale, clamp, onPreview, onCommit]);

  const keyDown = useCallback(
    (index: number, edge: Exclude<Edge, 'body'>) => (e: React.KeyboardEvent) => {
      const step = e.shiftKey ? 1 : 0.1;
      let dm = 0;
      if (e.key === 'ArrowUp') dm = -step;
      else if (e.key === 'ArrowDown') dm = step;
      else return;
      e.preventDefault();
      const next = clamp(
        screens.map((s, i) =>
          i !== index
            ? { ...s }
            : edge === 'top'
              ? { top: round(s.top + dm), base: s.base }
              : { top: s.top, base: round(s.base + dm) },
        ),
      );
      onPreview(next);
      onCommit(next);
    },
    [clamp, onCommit, onPreview, screens],
  );

  return { dragging, start, keyDown };
}
