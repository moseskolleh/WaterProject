import { useCallback, useState } from 'react';
import { STAGES, type DecisionRecord, type StageId } from '../domain/decision';
import type { SpineView } from '../domain/view';
import { DesignStage } from './stages/DesignStage';
import { WaterQualityStage } from './stages/WaterQualityStage';
import { CostingStage } from './stages/CostingStage';
import type { Interval } from './useScreenDrag';

export type Ledger = Partial<Record<StageId, DecisionRecord>>;

interface Props {
  view: SpineView;
  /** True while Python is re-deriving after a screen move. */
  busy: boolean;
  onScreens: (screens: [number, number][] | null) => void;
  onLedgerChange: (ledger: Ledger) => void;
}

/**
 * One shell for the whole borehole.
 *
 * Stages are the lifecycle, not a tab list: each carries the state of its own
 * decision, so "where are we?" is answered by the header. The sign-off layer
 * lives on each stage's rail — no second application.
 */
export function Workspace({ view, busy, onScreens, onLedgerChange }: Props) {
  const [stage, setStage] = useState<StageId>('design');
  const [preview, setPreview] = useState<Interval[] | null>(null);
  const [ledger, setLedger] = useState<Ledger>({});

  const decide = useCallback(
    (id: StageId) => (record: DecisionRecord | null) => {
      setLedger((prev) => {
        const next = { ...prev };
        if (record) next[id] = record;
        else delete next[id];
        onLedgerChange(next);
        return next;
      });
    },
    [onLedgerChange],
  );

  // Moving a screen invalidates the design and costing sign-offs: a signature
  // has to belong to the numbers that were in front of the person at the time.
  const commit = useCallback(
    (screens: Interval[]) => {
      onScreens(screens.map((s) => [s.top, s.base] as [number, number]));
      setLedger((prev) => {
        if (!prev.design && !prev.costing) return prev;
        const next = { ...prev };
        delete next.design;
        delete next.costing;
        onLedgerChange(next);
        return next;
      });
    },
    [onLedgerChange, onScreens],
  );

  const reset = useCallback(() => {
    setPreview(null);
    onScreens(null);
  }, [onScreens]);

  const stages = STAGES.filter((s) => s.id !== 'quality' || view.quality);
  const signed = stages.filter((s) => ledger[s.id]).length;
  const site = view.site;

  return (
    <div className="workspace">
      <header className="ws-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div className="logo-mark">G</div>
          <span className="brand">Geomentaqua</span>
        </div>
        <div className="vrule" />
        <span className="bh-name">
          {site.community}
          {site.boreholeRef && ` · ${site.boreholeRef}`}
        </span>
        <span className="bh-meta">
          {[site.district, view.section.drillingMethod].filter(Boolean).join(' · ')}
        </span>

        <nav className="stage-nav" aria-label="Stage">
          {stages.map((s) => {
            const record = ledger[s.id];
            return (
              <button
                key={s.id}
                type="button"
                aria-current={stage === s.id ? 'page' : undefined}
                className={stage === s.id ? 'is-current' : undefined}
                onClick={() => setStage(s.id)}
              >
                <span className={`stage-dot is-${record ? record.status : 'pending'}`} />
                {s.label}
              </button>
            );
          })}
        </nav>

        <div className="spacer" />
        {view.edited && <span className="edited-badge">design edited</span>}
        <span className="ledger-count">
          {signed}/{stages.length} signed
        </span>
        <button type="button" className="ghost-btn">
          {stage === 'costing' ? 'Export BoQ ↓' : 'Drawing sheet ↓'}
        </button>
      </header>

      {stage === 'design' && (
        <DesignStage
          view={view}
          preview={preview}
          onPreview={setPreview}
          onCommit={commit}
          onReset={reset}
          edited={view.edited}
          busy={busy}
          decision={ledger.design ?? null}
          onDecide={decide('design')}
        />
      )}
      {stage === 'quality' && view.quality && (
        <WaterQualityStage
          quality={view.quality}
          decision={ledger.quality ?? null}
          onDecide={decide('quality')}
        />
      )}
      {stage === 'costing' && (
        <CostingStage
          view={view}
          decision={ledger.costing ?? null}
          onDecide={decide('costing')}
        />
      )}
    </div>
  );
}
