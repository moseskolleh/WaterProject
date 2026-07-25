import type { Scale } from '../../domain/scale';

/** The shared ruler. Everything to its right is registered against these ticks. */
export function DepthRuler({ scale }: { scale: Scale }) {
  return (
    <div className="col-ruler">
      <div className="col-head">m</div>
      <div className="track" style={{ height: scale.height }}>
        <div className="ruler-spine" />
        {scale.minorTicks.map((d) => (
          <div key={d} className="tick-minor" style={{ top: scale.y(d) }} />
        ))}
        {scale.majorTicks.map((d) => (
          <div key={d}>
            <div className="tick-major" style={{ top: scale.y(d) }} />
            <div className="tick-label" style={{ top: scale.y(d) }}>
              {d}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
