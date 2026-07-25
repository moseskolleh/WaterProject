import { MAJOR_TICKS, MINOR_TICKS, TRACK_H, y } from '../../domain/scale';

/** The shared ruler. Everything to its right is registered against these ticks. */
export function DepthRuler() {
  return (
    <div className="col-ruler">
      <div className="col-head">m</div>
      <div className="track" style={{ height: TRACK_H }}>
        <div className="ruler-spine" />
        {MINOR_TICKS.map((d) => (
          <div key={d} className="tick-minor" style={{ top: y(d) }} />
        ))}
        {MAJOR_TICKS.map((d) => (
          <div key={d}>
            <div className="tick-major" style={{ top: y(d) }} />
            <div className="tick-label" style={{ top: y(d) }}>
              {d}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
