import { useMemo, useState } from 'react';
import type { DecisionRecord } from '../../domain/decision';
import { derive } from '../../domain/derive';
import {
  deriveCost,
  deriveProgramme,
  RESOURCE_LABELS,
  STAGE_COLOURS,
  STAGE_LABELS,
  type Markup,
  type Stage,
} from '../../domain/costing';
import type { Borehole, ScreenInterval } from '../../domain/types';
import { SignOff } from '../SignOff';

interface Props {
  bh: Borehole;
  screen: ScreenInterval;
  rates: Record<string, number>;
  onRateChange: (id: string, rate: number) => void;
  markup: Markup;
  onMarkupChange: (next: Markup) => void;
  decision: DecisionRecord | null;
  onDecide: (record: DecisionRecord | null) => void;
}

const usd = (n: number) =>
  n.toLocaleString('en-US', { maximumFractionDigits: 0 });

const qty = (n: number, unit: string) =>
  unit === 'm³' ? n.toFixed(3) : unit === 'sum' || unit === 'no.' ? n.toFixed(0) : n.toFixed(1);

export function CostingStage({
  bh,
  screen,
  rates,
  onRateChange,
  markup,
  onMarkupChange,
  decision,
  onDecide,
}: Props) {
  const [showProgramme, setShowProgramme] = useState(true);
  const d = useMemo(() => derive(bh, screen), [bh, screen]);
  const c = useMemo(() => deriveCost(bh, d, rates, markup), [bh, d, rates, markup]);
  const programme = useMemo(
    () => deriveProgramme(c, rates, { boreholes: 12, dryRate: 0.22 }),
    [c, rates],
  );

  const stages = [...new Set(c.lines.map((l) => l.stage))] as Stage[];

  return (
    <div className="ws-body">
      <div className="spine">
        <div className="metrics">
          <div className="metric-row">
            <div>
              <div className="metric-label">Cost to build</div>
              <div className="metric-value">US$ {usd(c.cost)}</div>
            </div>
            <div>
              <div className="metric-label">Price to client</div>
              <div className="metric-value is-aquifer">US$ {usd(c.price)}</div>
            </div>
            <div>
              <div className="metric-label">Per metre drilled</div>
              <div className="metric-value">US$ {usd(c.pricePerMetre)}</div>
            </div>
            <div>
              <div className="metric-label">Design-driven</div>
              <div className="metric-value">
                {((c.designDrivenCost / c.cost) * 100).toFixed(0)} %
              </div>
            </div>
          </div>
          <div className="legend">
            <span>RWSN Cost-Effective Boreholes · unit rates editable · cost ≠ price</span>
          </div>
        </div>

        <div className="boq">
          <div className="boq-row is-head">
            <span className="boq-desc">Item</span>
            <span className="boq-unit">Unit</span>
            <span className="boq-qty">Quantity</span>
            <span className="boq-rate">Unit cost US$</span>
            <span className="boq-cost">Cost US$</span>
          </div>

          {stages.map((stage) => {
            const lines = c.lines.filter((l) => l.stage === stage);
            const subtotal = lines.reduce((s, l) => s + l.cost, 0);
            return (
              <div key={stage}>
                <div className="boq-row is-stage">
                  <span className="boq-desc">
                    <span
                      className="boq-swatch"
                      style={{ background: STAGE_COLOURS[stage] }}
                    />
                    {STAGE_LABELS[stage]}
                  </span>
                  <span className="boq-unit" />
                  <span className="boq-qty" />
                  <span className="boq-rate" />
                  <span className="boq-cost">{usd(subtotal)}</span>
                </div>
                {lines.map((l) => (
                  <div className="boq-row" key={l.id}>
                    <span className="boq-desc">
                      {l.description}
                      {l.basis && <em>{l.basis}</em>}
                    </span>
                    <span className="boq-unit">{l.unit}</span>
                    <span className={`boq-qty${l.designDriven ? ' is-derived' : ''}`}>
                      {qty(l.quantity, l.unit)}
                    </span>
                    <span className="boq-rate">
                      <input
                        type="number"
                        value={l.rate}
                        min={0}
                        step={1}
                        aria-label={`Unit cost for ${l.description}`}
                        onChange={(e) => onRateChange(l.id, Number(e.target.value))}
                      />
                    </span>
                    <span className="boq-cost">{usd(l.cost)}</span>
                  </div>
                ))}
              </div>
            );
          })}

          <div className="boq-row is-total">
            <span className="boq-desc">Cost to build</span>
            <span className="boq-unit" />
            <span className="boq-qty" />
            <span className="boq-rate" />
            <span className="boq-cost">{usd(c.cost)}</span>
          </div>
        </div>

        <div className="boq-note">
          Quantities in bold are read from the borehole design — change the screen
          on the Design stage and the casing, screen, gravel pack, grout and rising
          main lines move with it. Unit costs are the contractor&rsquo;s cost, not
          the price; overhead and margin are applied once, on the right, so the two
          are never confused.
        </div>
      </div>

      <aside className="rail">
        <div className="rail-head">Derived decisions</div>

        <div className="yield-card">
          <div className="eyebrow">Price to client</div>
          <div className="yield-value">
            <span className="unit">US$</span> {usd(c.price)}
          </div>
          <div className="yield-method">
            Cost {usd(c.cost)} + overhead {markup.overheadPct}% ({usd(c.overhead)}) +
            margin {markup.marginPct}% ({usd(c.margin)}).
          </div>
          <div className="chip-row">
            <span className="chip">US$ {usd(c.pricePerMetre)} / m</span>
            <span className="chip">{bh.construction.totalDepth} m</span>
          </div>
        </div>

        <div className="markup-row">
          <label>
            <span>Overhead %</span>
            <input
              type="number"
              value={markup.overheadPct}
              min={0}
              max={40}
              step={0.5}
              onChange={(e) =>
                onMarkupChange({ ...markup, overheadPct: Number(e.target.value) })
              }
            />
          </label>
          <label>
            <span>Margin %</span>
            <input
              type="number"
              value={markup.marginPct}
              min={0}
              max={40}
              step={0.5}
              onChange={(e) =>
                onMarkupChange({ ...markup, marginPct: Number(e.target.value) })
              }
            />
          </label>
        </div>

        <div className="rail-head">By stage</div>
        <div className="split-bar">
          {c.byStage.map((s) => (
            <span
              key={s.stage}
              style={{
                width: `${s.share * 100}%`,
                background: STAGE_COLOURS[s.stage],
              }}
              title={STAGE_LABELS[s.stage]}
            />
          ))}
        </div>
        <div className="split-legend">
          {c.byStage.map((s) => (
            <span key={s.stage}>
              <span
                className="boq-swatch"
                style={{ background: STAGE_COLOURS[s.stage] }}
              />
              {STAGE_LABELS[s.stage]}
              <em>{(s.share * 100).toFixed(0)}%</em>
            </span>
          ))}
        </div>

        <div className="rail-head">By resource</div>
        <div className="checks">
          {c.byResource.map((r) => (
            <div className="check" key={r.resource}>
              <span className="check-label">{RESOURCE_LABELS[r.resource]}</span>
              <span className="check-value">
                {usd(r.cost)} · {(r.share * 100).toFixed(0)}%
              </span>
            </div>
          ))}
        </div>

        <div className="hint">
          <button
            type="button"
            className="hint-title as-button"
            aria-expanded={showProgramme}
            onClick={() => setShowProgramme((v) => !v)}
          >
            Programme of 12 boreholes {showProgramme ? '−' : '+'}
          </button>
          {showProgramme && (
            <div className="hint-body">
              <div className="mini-row">
                <span>Expected attempts at 22 % dry</span>
                <span>{programme.attempts.toFixed(1)}</span>
              </div>
              <div className="mini-row">
                <span>Dry holes carried</span>
                <span>{programme.dryAttempts.toFixed(1)}</span>
              </div>
              <div className="mini-row">
                <span>Shared mobilisation saving</span>
                <span className="is-good">−US$ {usd(programme.sharedSaving)}</span>
              </div>
              <div className="mini-row is-total">
                <span>Programme price</span>
                <span>US$ {usd(programme.total)}</span>
              </div>
              <div className="mini-row">
                <span>Per successful borehole</span>
                <span>US$ {usd(programme.perSuccessful)}</span>
              </div>
            </div>
          )}
        </div>

        <div className="spacer" />

        <SignOff
          stage="costing"
          recommended={`US$ ${usd(c.price)}`}
          writesTo="accepting writes to the cost estimate and the bill of quantities"
          decision={decision}
          clean
          onDecide={onDecide}
          override={{
            kind: 'number',
            label: 'Price to client',
            unit: 'US$',
            start: Math.round(c.price),
            step: 50,
            min: 0,
            max: 200000,
            format: (n) => `US$ ${usd(n)}`,
          }}
        />
      </aside>
    </div>
  );
}
