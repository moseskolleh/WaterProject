import { useCallback, useMemo } from 'react';
import { clampScreen, derive } from '../../domain/derive';
import type { DecisionRecord } from '../../domain/decision';
import type { Borehole, ScreenInterval } from '../../domain/types';
import { DepthRuler } from '../columns/DepthRuler';
import { VesColumn } from '../columns/VesColumn';
import { LithologyColumn } from '../columns/LithologyColumn';
import { ConstructionColumn } from '../columns/ConstructionColumn';
import { HydraulicsColumn } from '../columns/HydraulicsColumn';
import { DecisionsRail } from '../DecisionsRail';
import { SignOff } from '../SignOff';
import { useScreenDrag } from '../useScreenDrag';

export type SectionView = 'section' | 'plan' | 'tables';

interface Props {
  bh: Borehole;
  screen: ScreenInterval;
  baseline: ScreenInterval;
  onScreenChange: (next: ScreenInterval) => void;
  view: SectionView;
  decision: DecisionRecord | null;
  onDecide: (record: DecisionRecord | null) => void;
}

/** The Depth Spine — one shared depth axis, evidence left, decision right. */
export function DesignStage({
  bh,
  screen,
  baseline,
  onScreenChange,
  view,
  decision,
  onDecide,
}: Props) {
  const change = useCallback(
    (next: ScreenInterval) => onScreenChange(clampScreen(bh, next)),
    [bh, onScreenChange],
  );

  const { dragging, start, keyDown } = useScreenDrag({ screen, onChange: change });
  const d = useMemo(() => derive(bh, screen), [bh, screen]);

  const dirty =
    d.screenTop !== baseline.screenTop || d.screenBase !== baseline.screenBase;
  const clean =
    d.verdict.status === 'ok' && d.checks.every((c) => c.status === 'ok');

  return (
    <div className="ws-body">
      {view === 'section' ? (
        <div className="spine">
          <div className="metrics">
            <div className="metric-row">
              <div>
                <div className="metric-label">Overburden</div>
                <div className="metric-value">{d.overburden.toFixed(1)} m</div>
              </div>
              <div>
                <div className="metric-label">Fractured zone</div>
                <div className="metric-value is-aquifer">
                  {d.aquiferTop.toFixed(0)} – {d.aquiferBase.toFixed(0)} m
                </div>
              </div>
              <div>
                <div className="metric-label">Drilled</div>
                <div className="metric-value">
                  {bh.construction.totalDepth.toFixed(1)} m
                </div>
              </div>
              <div>
                <div className="metric-label">Water strikes</div>
                <div className="metric-value">{bh.waterStrikes.length}</div>
              </div>
            </div>
            <div className="legend">
              <span>
                <span className="sw-block" />
                aquifer
              </span>
              <span>
                <span
                  className="sw-line"
                  style={{ background: 'oklch(0.72 0.15 235)' }}
                />
                rest level
              </span>
              <span>
                <span
                  className="sw-line"
                  style={{ background: 'oklch(0.72 0.16 55)' }}
                />
                pumping level
              </span>
            </div>
          </div>

          <div className="columns">
            <DepthRuler />
            <VesColumn layers={bh.ves} />
            <LithologyColumn units={bh.lithology} strikes={bh.waterStrikes} />
            <ConstructionColumn
              bh={bh}
              d={d}
              dragging={dragging}
              onHandleDown={start}
              onHandleKey={keyDown}
            />
            <HydraulicsColumn bh={bh} d={d} />
          </div>
        </div>
      ) : (
        <div className="spine">
          <div className="other-view">
            <div className="title">{view} view</div>
            <div className="body">
              Site plan and the tabular record of the same model.
              <br />
              Not part of this build — the section is the spine.
            </div>
          </div>
        </div>
      )}

      <DecisionsRail
        bh={bh}
        d={d}
        footer={
          <SignOff
            stage="design"
            recommended={`${d.safeYield.toFixed(2)} L/s`}
            writesTo="accepting writes to the completion and pumping-test reports"
            decision={decision}
            clean={clean}
            onDecide={onDecide}
            revert={{ enabled: dirty, onRevert: () => onScreenChange(baseline) }}
            override={{
              kind: 'number',
              label: 'Certified safe yield',
              unit: 'L/s',
              start: Number(d.safeYield.toFixed(2)),
              step: 0.01,
              min: 0.05,
              max: 5,
              format: (n) => `${n.toFixed(2)} L/s`,
            }}
          />
        }
      />
    </div>
  );
}
