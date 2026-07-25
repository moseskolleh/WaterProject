import { useCallback, useEffect, useRef, useState } from 'react';
import { PX_PER_M } from '../domain/scale';
import type { ScreenInterval } from '../domain/types';

export type HandleId = 'top' | 'base';

/** Depth is committed at 0.1 m — one pixel at the spine's scale. */
const STEP = 0.1;
const round = (n: number) => Math.round(n * 10) / 10;

interface Options {
  screen: ScreenInterval;
  onChange: (next: ScreenInterval) => void;
}

/**
 * Direct manipulation of the screened interval.
 *
 * Pointer drag moves one edge; dragging the body of the screen moves both and
 * keeps the length. Arrow keys do the same thing from the keyboard, because a
 * design decision this consequential should not be mouse-only.
 */
export function useScreenDrag({ screen, onChange }: Options) {
  const [dragging, setDragging] = useState<HandleId | 'body' | null>(null);
  const origin = useRef({ y: 0, top: 0, base: 0 });

  const start = useCallback(
    (which: HandleId | 'body') => (e: React.PointerEvent) => {
      e.preventDefault();
      (e.target as Element).setPointerCapture?.(e.pointerId);
      origin.current = {
        y: e.clientY,
        top: screen.screenTop,
        base: screen.screenBase,
      };
      setDragging(which);
    },
    [screen.screenTop, screen.screenBase],
  );

  useEffect(() => {
    if (!dragging) return;

    const move = (e: PointerEvent) => {
      const dm = round((e.clientY - origin.current.y) / PX_PER_M);
      const { top, base } = origin.current;
      if (dragging === 'top') {
        onChange({ screenTop: round(top + dm), screenBase: base });
      } else if (dragging === 'base') {
        onChange({ screenTop: top, screenBase: round(base + dm) });
      } else {
        onChange({ screenTop: round(top + dm), screenBase: round(base + dm) });
      }
    };
    const end = () => setDragging(null);

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', end);
    window.addEventListener('pointercancel', end);
    return () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', end);
      window.removeEventListener('pointercancel', end);
    };
  }, [dragging, onChange]);

  const keyDown = useCallback(
    (which: HandleId) => (e: React.KeyboardEvent) => {
      const coarse = e.shiftKey ? 10 : 1;
      let dm = 0;
      if (e.key === 'ArrowUp') dm = -STEP * coarse;
      else if (e.key === 'ArrowDown') dm = STEP * coarse;
      else return;
      e.preventDefault();
      onChange(
        which === 'top'
          ? { screenTop: round(screen.screenTop + dm), screenBase: screen.screenBase }
          : { screenTop: screen.screenTop, screenBase: round(screen.screenBase + dm) },
      );
    },
    [onChange, screen.screenTop, screen.screenBase],
  );

  return { dragging, start, keyDown };
}
