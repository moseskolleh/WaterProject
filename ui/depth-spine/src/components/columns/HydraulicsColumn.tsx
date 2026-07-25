import type { Scale } from '../../domain/scale';
import type { Section } from '../../domain/view';

/** Rest level, the level the test reached, and the pump intake — on the spine. */
export function HydraulicsColumn({ scale, section }: { scale: Scale; section: Section }) {
  const { restLevel, pumpingLevel, pumpIntake, stabilised, maxDrawdown } = section.levels;

  return (
    <div className="col-hydraulics">
      <div className="col-head">Hydraulics</div>
      <div className="track" style={{ height: scale.height }}>
        {restLevel !== undefined && (
          <>
            <div className="saturated" style={{ top: scale.y(restLevel) }} />
            <div className="rest-level" style={{ top: scale.y(restLevel) }} />
            <div className="level-label is-rest" style={{ top: scale.y(restLevel) - 20 }}>
              SWL {restLevel.toFixed(2)} m
            </div>
          </>
        )}

        {pumpingLevel !== undefined && (
          <>
            <div className="pumping-level" style={{ top: scale.y(pumpingLevel) }} />
            <div
              className="level-label is-pumping"
              style={{ top: scale.y(pumpingLevel) + 6 }}
            >
              {stabilised ? 'pumping level' : 'deepest level'} {pumpingLevel.toFixed(2)} m
            </div>
          </>
        )}

        {restLevel !== undefined && pumpingLevel !== undefined && (
          <>
            <div
              className="drawdown-bar"
              style={{
                top: scale.y(restLevel),
                height: scale.h(restLevel, pumpingLevel),
              }}
            />
            <div
              className="drawdown-label"
              style={{ top: (scale.y(restLevel) + scale.y(pumpingLevel)) / 2 }}
            >
              s = {(maxDrawdown ?? pumpingLevel - restLevel).toFixed(2)} m
            </div>
          </>
        )}

        {pumpIntake !== undefined && (
          <>
            <div className="intake" style={{ top: scale.y(pumpIntake) }}>
              <span className="intake-badge">PMP</span>
              <span className="intake-label">intake {pumpIntake.toFixed(0)} m</span>
            </div>
          </>
        )}

        {stabilised === false && (
          <div className="submergence-note is-warn" style={{ bottom: 4 }}>
            The water level had not stabilised when the test ended, so the line
            above is the deepest level reached, not a settled pumping level.
          </div>
        )}
      </div>
    </div>
  );
}
