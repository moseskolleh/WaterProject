import { useCallback, useMemo, useState } from 'react';
import {
  STAGES,
  type DecisionRecord,
  type StageId,
} from '../domain/decision';
import { DEFAULT_MARKUP, defaultRates, type Markup } from '../domain/costing';
import type { WaterSample } from '../domain/quality';
import type { Borehole, ScreenInterval } from '../domain/types';
import { DesignStage, type SectionView } from './stages/DesignStage';
import { WaterQualityStage } from './stages/WaterQualityStage';
import { CostingStage } from './stages/CostingStage';

export type Ledger = Partial<Record<StageId, DecisionRecord>>;

interface Props {
  borehole: Borehole;
  sample: WaterSample;
  /** Fires whenever the ledger changes, so the host can record the sign-offs. */
  onLedgerChange?: (ledger: Ledger) => void;
}

/**
 * One shell for the whole borehole.
 *
 * Stages are the lifecycle, not a tab list: each carries the state of its own
 * decision, so "where are we?" is answered by the header rather than by opening
 * things. The sign-off layer lives on each stage's rail — no second application.
 */
export function Workspace({ borehole: bh, sample, onLedgerChange }: Props) {
  const baseline = useMemo<ScreenInterval>(
    () => ({
      screenTop: bh.construction.screenTop,
      screenBase: bh.construction.screenBase,
    }),
    [bh],
  );

  const [stage, setStage] = useState<StageId>('design');
  const [view, setView] = useState<SectionView>('section');
  const [screen, setScreen] = useState<ScreenInterval>(baseline);
  const [rates, setRates] = useState<Record<string, number>>(defaultRates);
  const [markup, setMarkup] = useState<Markup>(DEFAULT_MARKUP);
  const [ledger, setLedger] = useState<Ledger>({});

  const decide = useCallback(
    (id: StageId) => (record: DecisionRecord | null) => {
      setLedger((prev) => {
        const next = { ...prev };
        if (record) next[id] = record;
        else delete next[id];
        onLedgerChange?.(next);
        return next;
      });
    },
    [onLedgerChange],
  );

  // Editing the design after signing it off reopens that decision — a signature
  // has to belong to the numbers that were in front of the person at the time.
  const changeScreen = useCallback(
    (next: ScreenInterval) => {
      setScreen(next);
      setLedger((prev) => {
        if (!prev.design && !prev.costing) return prev;
        const out = { ...prev };
        delete out.design;
        delete out.costing;
        onLedgerChange?.(out);
        return out;
      });
    },
    [onLedgerChange],
  );

  const changeRate = useCallback((id: string, rate: number) => {
    setRates((prev) => ({ ...prev, [id]: Number.isFinite(rate) ? rate : 0 }));
    setLedger((prev) => {
      if (!prev.costing) return prev;
      const out = { ...prev };
      delete out.costing;
      return out;
    });
  }, []);

  const signed = STAGES.filter((s) => ledger[s.id]).length;

  return (
    <div className="workspace">
      <header className="ws-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
          <div className="logo-mark">G</div>
          <span className="brand">Geomentaqua</span>
        </div>
        <div className="vrule" />
        <span className="bh-name">{bh.name}</span>
        <span className="bh-meta">
          {bh.locality} · {bh.terrain}
        </span>

        <nav className="stage-nav" aria-label="Stage">
          {STAGES.map((s) => {
            const record = ledger[s.id];
            return (
              <button
                key={s.id}
                type="button"
                aria-current={stage === s.id ? 'page' : undefined}
                className={stage === s.id ? 'is-current' : undefined}
                onClick={() => setStage(s.id)}
              >
                <span
                  className={`stage-dot is-${record ? record.status : 'pending'}`}
                />
                {s.label}
              </button>
            );
          })}
        </nav>

        <div className="spacer" />
        <span className="ledger-count">
          {signed}/{STAGES.length} signed
        </span>

        {stage === 'design' && (
          <div className="segmented" role="group" aria-label="View">
            {(['section', 'plan', 'tables'] as SectionView[]).map((v) => (
              <button
                key={v}
                type="button"
                aria-pressed={view === v}
                onClick={() => setView(v)}
              >
                {v[0].toUpperCase() + v.slice(1)}
              </button>
            ))}
          </div>
        )}
        <button type="button" className="ghost-btn">
          {stage === 'costing' ? 'Export BoQ ↓' : 'Drawing sheet ↓'}
        </button>
      </header>

      {stage === 'design' && (
        <DesignStage
          bh={bh}
          screen={screen}
          baseline={baseline}
          onScreenChange={changeScreen}
          view={view}
          decision={ledger.design ?? null}
          onDecide={decide('design')}
        />
      )}
      {stage === 'quality' && (
        <WaterQualityStage
          sample={sample}
          decision={ledger.quality ?? null}
          onDecide={decide('quality')}
        />
      )}
      {stage === 'costing' && (
        <CostingStage
          bh={bh}
          screen={screen}
          rates={rates}
          onRateChange={changeRate}
          markup={markup}
          onMarkupChange={setMarkup}
          decision={ledger.costing ?? null}
          onDecide={decide('costing')}
        />
      )}
    </div>
  );
}
