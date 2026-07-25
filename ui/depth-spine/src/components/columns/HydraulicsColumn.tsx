import { TRACK_H, y } from '../../domain/scale';
import type { Derived } from '../../domain/derive';
import { RULES } from '../../domain/derive';
import type { Borehole } from '../../domain/types';

interface Props {
  bh: Borehole;
  d: Derived;
}

/** Rest level, pumping level, drawdown and the pump intake — all on the spine. */
export function HydraulicsColumn({ bh, d }: Props) {
  const { restLevel, pumpingLevel } = bh.hydraulics;
  const restPx = y(restLevel);
  const pumpingPx = y(pumpingLevel);
  const intakePx = y(d.pumpSetting);
  const shallow = d.submergence < RULES.minSubmergence;

  return (
    <div className="col-hydraulics">
      <div className="col-head">Hydraulics</div>
      <div className="track" style={{ height: TRACK_H }}>
        <div className="saturated" style={{ top: restPx }} />
        <div className="rest-level" style={{ top: restPx }} />
        <div className="level-label is-rest" style={{ top: restPx - 20 }}>
          SWL {restLevel.toFixed(1)} m
        </div>

        <div className="pumping-level" style={{ top: pumpingPx }} />
        <div className="level-label is-pumping" style={{ top: pumpingPx + 6 }}>
          pumping level {pumpingLevel.toFixed(1)} m
        </div>

        <div
          className="drawdown-bar"
          style={{ top: restPx, height: pumpingPx - restPx }}
        />
        <div className="drawdown-label" style={{ top: (restPx + pumpingPx) / 2 }}>
          s = {d.drawdown.toFixed(1)} m
        </div>

        <div className="intake" style={{ top: intakePx }}>
          <span className="intake-badge">PMP</span>
          <span className="intake-label">intake {d.pumpSetting.toFixed(1)} m</span>
        </div>

        <div
          className={`submergence-note${shallow ? ' is-warn' : ''}`}
          style={{ top: intakePx + 18 }}
        >
          {shallow
            ? `Only ${d.submergence.toFixed(1)} m of water above the intake at design yield — ` +
              `raise the screen or accept a shallower setting.`
            : `${d.submergence.toFixed(1)} m submergence above intake at design yield — within handpump limits.`}
        </div>
      </div>
    </div>
  );
}
