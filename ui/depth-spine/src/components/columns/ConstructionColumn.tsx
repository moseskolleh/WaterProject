import { TRACK_H, y } from '../../domain/scale';
import type { Derived } from '../../domain/derive';
import { RULES } from '../../domain/derive';
import type { Borehole } from '../../domain/types';
import type { HandleId } from '../useScreenDrag';

interface Props {
  bh: Borehole;
  d: Derived;
  dragging: HandleId | 'body' | null;
  onHandleDown: (which: HandleId | 'body') => (e: React.PointerEvent) => void;
  onHandleKey: (which: HandleId) => (e: React.KeyboardEvent) => void;
}

/** Slot hatching, spaced so a 12 m screen reads as eight lines. */
function slots(topPx: number, basePx: number) {
  const out: number[] = [];
  for (let t = topPx + 8; t < basePx - 6; t += 14) out.push(t);
  return out;
}

/**
 * The construction column — the only editable thing on the spine.
 * Everything else on screen is evidence; this is the decision.
 */
export function ConstructionColumn({ bh, d, dragging, onHandleDown, onHandleKey }: Props) {
  const { totalDepth, sanitarySealBase, casingDiameter, casingMaterial } = bh.construction;
  const topPx = y(d.screenTop);
  const basePx = y(d.screenBase);
  const deepest = totalDepth - RULES.sumpLength;

  return (
    <div className="col-construction">
      <div className="col-head">Construction</div>
      <div className="track" style={{ height: TRACK_H }}>
        {/* Drilled hole */}
        <div className="bore-wall" style={{ height: y(totalDepth) }} />

        {/* Annulus: grout above the pack, gravel pack across the screen */}
        {[34, 78].map((left) => (
          <div key={left}>
            <div
              className="annulus is-grout"
              style={{ left, top: 0, height: y(d.packTop) }}
            />
            <div
              className="annulus is-pack"
              style={{ left, top: y(d.packTop), height: y(d.packBase) - y(d.packTop) }}
            />
          </div>
        ))}

        {/* Plain casing, sanitary seal, screen, sump */}
        <div className="casing" style={{ top: 0, height: topPx }} />
        <div className="seal" style={{ top: 0, height: y(sanitarySealBase) }} />
        <div
          className={`screen${dragging ? ' is-dragging' : ''}`}
          style={{ top: topPx, height: basePx - topPx, cursor: 'grab' }}
          onPointerDown={onHandleDown('body')}
        >
          {slots(0, basePx - topPx).map((t) => (
            <div key={t} className="slot" style={{ top: t }} />
          ))}
        </div>
        <div
          className="casing"
          style={{ top: basePx, height: y(d.sumpBase) - basePx }}
        />

        {/* Handles */}
        <button
          type="button"
          role="slider"
          aria-label="Top of screened interval, metres below ground level"
          aria-valuemin={sanitarySealBase}
          aria-valuemax={d.screenBase - RULES.minScreenLength}
          aria-valuenow={d.screenTop}
          aria-valuetext={`${d.screenTop.toFixed(1)} metres`}
          className={`handle${dragging === 'top' ? ' is-dragging' : ''}`}
          style={{ top: topPx }}
          onPointerDown={onHandleDown('top')}
          onKeyDown={onHandleKey('top')}
        />
        <button
          type="button"
          role="slider"
          aria-label="Base of screened interval, metres below ground level"
          aria-valuemin={d.screenTop + RULES.minScreenLength}
          aria-valuemax={deepest}
          aria-valuenow={d.screenBase}
          aria-valuetext={`${d.screenBase.toFixed(1)} metres`}
          className={`handle${dragging === 'base' ? ' is-dragging' : ''}`}
          style={{ top: basePx }}
          onPointerDown={onHandleDown('base')}
          onKeyDown={onHandleKey('base')}
        />

        <div className="handle-value" style={{ top: topPx }}>
          {d.screenTop.toFixed(1)}
        </div>
        <div className="handle-value" style={{ top: basePx }}>
          {d.screenBase.toFixed(1)}
        </div>

        <div className="screen-caption" style={{ top: (topPx + basePx) / 2 }}>
          screen
          <br />
          <span>
            {d.screenLength.toFixed(d.screenLength % 1 ? 1 : 0)} m · slot{' '}
            {bh.construction.screen.slotWidth.toFixed(1)}
          </span>
        </div>

        <div className="construction-note" style={{ top: y(sanitarySealBase) / 2 }}>
          grout
          <br />0–{sanitarySealBase}
        </div>
        <div
          className="construction-note"
          style={{ top: (y(sanitarySealBase) + topPx) / 2 }}
        >
          {casingMaterial} {casingDiameter}
          <br />
          plain
        </div>
        {d.sumpBase > d.screenBase && (
          <div
            className="construction-note"
            style={{ top: (basePx + y(d.sumpBase)) / 2 }}
          >
            sump {d.sumpBase.toFixed(0)}
          </div>
        )}

        <div className="td-line" style={{ top: y(totalDepth) }} />
        <div className="td-label" style={{ top: y(totalDepth) + 6 }}>
          TD {totalDepth.toFixed(1)}
        </div>
      </div>
    </div>
  );
}
