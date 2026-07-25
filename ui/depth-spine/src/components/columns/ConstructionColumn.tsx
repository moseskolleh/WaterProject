import type { Scale } from '../../domain/scale';
import type { Section } from '../../domain/view';
import type { DragState, Edge, Interval } from '../useScreenDrag';

interface Props {
  scale: Scale;
  section: Section;
  /** The intervals currently drawn — the live drag preview, not the payload. */
  screens: Interval[];
  dragging: DragState | null;
  onHandleDown: (index: number, edge: Edge) => (e: React.PointerEvent) => void;
  onHandleKey: (
    index: number,
    edge: 'top' | 'base',
  ) => (e: React.KeyboardEvent) => void;
}

/** Slot hatching, dense enough to read as a screen at any scale. */
function slots(height: number): number[] {
  const out: number[] = [];
  for (let t = 6; t < height - 4; t += 9) out.push(t);
  return out;
}

/**
 * The construction column — the only editable thing on the section.
 *
 * Everything else is evidence. This is the decision, and it is the analyst's:
 * the handles move the screens, and Python re-derives the string, the annulus,
 * the checks and the bill of quantities around them.
 */
export function ConstructionColumn({
  scale,
  section,
  screens,
  dragging,
  onHandleDown,
  onHandleKey,
}: Props) {
  const { totalDepth, gravelPack, backfill, sanitarySeal, screenLimits } = section;
  // Plain casing and sump come from the payload; the screens are drawn from the
  // live intervals so the drawing keeps up with the pointer.
  const fixed = section.segments.filter((s) => s.kind !== 'screen');

  return (
    <div className="col-construction">
      <div className="col-head">Construction</div>
      <div className="track" style={{ height: scale.height }}>
        <div className="bore-wall" style={{ height: scale.y(totalDepth) }} />

        {[34, 78].map((left) => (
          <div key={left}>
            <div
              className="annulus is-grout"
              style={{
                left,
                top: scale.y(backfill[0]),
                height: scale.h(backfill[0], backfill[1]),
              }}
            />
            <div
              className="annulus is-pack"
              style={{
                left,
                top: scale.y(gravelPack[0]),
                height: scale.h(gravelPack[0], gravelPack[1]),
              }}
            />
          </div>
        ))}

        {fixed.map((s) => (
          <div
            key={`${s.kind}-${s.top}`}
            className="casing"
            style={{ top: scale.y(s.top), height: scale.h(s.top, s.base) }}
          />
        ))}

        <div
          className="seal"
          style={{
            top: scale.y(sanitarySeal[0]),
            height: scale.h(sanitarySeal[0], sanitarySeal[1]),
          }}
        />

        {screens.map((s, i) => {
          const top = scale.y(s.top);
          const height = scale.h(s.top, s.base);
          const active = dragging?.index === i;
          return (
            <div key={i}>
              <div
                className={`screen${active ? ' is-dragging' : ''}`}
                style={{ top, height, cursor: 'grab' }}
                onPointerDown={onHandleDown(i, 'body')}
              >
                {slots(height).map((t) => (
                  <div key={t} className="slot" style={{ top: t }} />
                ))}
              </div>

              <button
                type="button"
                role="slider"
                aria-label={`Top of screen ${i + 1}, metres below ground level`}
                aria-valuemin={screenLimits.top}
                aria-valuemax={s.base - screenLimits.minLength}
                aria-valuenow={s.top}
                aria-valuetext={`${s.top.toFixed(1)} metres`}
                className={`handle${active && dragging?.edge === 'top' ? ' is-dragging' : ''}`}
                style={{ top }}
                onPointerDown={onHandleDown(i, 'top')}
                onKeyDown={onHandleKey(i, 'top')}
              />
              <button
                type="button"
                role="slider"
                aria-label={`Base of screen ${i + 1}, metres below ground level`}
                aria-valuemin={s.top + screenLimits.minLength}
                aria-valuemax={screenLimits.base}
                aria-valuenow={s.base}
                aria-valuetext={`${s.base.toFixed(1)} metres`}
                className={`handle${active && dragging?.edge === 'base' ? ' is-dragging' : ''}`}
                style={{ top: top + height }}
                onPointerDown={onHandleDown(i, 'base')}
                onKeyDown={onHandleKey(i, 'base')}
              />

              <div className="handle-value" style={{ top }}>
                {s.top.toFixed(1)}
              </div>
              <div className="handle-value" style={{ top: top + height }}>
                {s.base.toFixed(1)}
              </div>
              {height > 22 && (
                <div className="screen-caption" style={{ top: top + height / 2 }}>
                  screen {i + 1}
                  <br />
                  <span>{(s.base - s.top).toFixed(1)} m</span>
                </div>
              )}
            </div>
          );
        })}

        <div
          className="construction-note"
          style={{ top: scale.y(sanitarySeal[1]) / 2 }}
        >
          seal
          <br />
          {sanitarySeal[0]}–{sanitarySeal[1]}
        </div>

        <div className="td-line" style={{ top: scale.y(totalDepth) }} />
        <div className="td-label" style={{ top: scale.y(totalDepth) + 6 }}>
          TD {totalDepth.toFixed(1)}
        </div>
      </div>
    </div>
  );
}
