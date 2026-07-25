import type { DecisionRecord } from '../../domain/decision';
import type { CostingBlock, SpineView } from '../../domain/view';
import { FlagsList } from '../FlagsList';
import { SignOff } from '../SignOff';

interface Props {
  view: SpineView;
  decision: DecisionRecord | null;
  onDecide: (record: DecisionRecord | null) => void;
}

const usd = (n: number) => n.toLocaleString('en-US', { maximumFractionDigits: 0 });

const qty = (n: number, unit: string) =>
  unit === 'm3' || unit === 'm³' ? n.toFixed(2) : Number.isInteger(n) ? String(n) : n.toFixed(1);

/** Quantities the design drives, so the analyst can see what moved with it. */
const DESIGN_DRIVEN = /casing|screen|gravel|grout|seal|drill/i;

const STAGE_COLOURS = [
  'oklch(0.72 0.13 190)',
  'oklch(0.66 0.12 210)',
  'oklch(0.7 0.13 145)',
  'oklch(0.78 0.13 110)',
  'oklch(0.8 0.14 75)',
  'oklch(0.72 0.11 40)',
  'oklch(0.68 0.13 20)',
  'oklch(0.7 0.1 300)',
];

export function CostingStage({ view, decision, onDecide }: Props) {
  const c: CostingBlock = view.costing;
  const stages = [...new Set(c.items.map((i) => i.stage))];
  const colourFor = (stage: string) =>
    STAGE_COLOURS[stages.indexOf(stage) % STAGE_COLOURS.length];

  return (
    <div className="ws-body">
      <div className="spine">
        <div className="metrics">
          <div className="metric-row">
            <div>
              <div className="metric-label">Direct cost</div>
              <div className="metric-value">US$ {usd(c.directCost)}</div>
            </div>
            <div>
              <div className="metric-label">Cost to build</div>
              <div className="metric-value">US$ {usd(c.totalCost)}</div>
            </div>
            <div>
              <div className="metric-label">Price to client</div>
              <div className="metric-value is-aquifer">US$ {usd(c.price)}</div>
            </div>
            <div>
              <div className="metric-label">Per metre</div>
              <div className="metric-value">US$ {usd(c.costPerMetre)}</div>
            </div>
          </div>
          <div className="legend">
            <span>
              RWSN Cost-Effective Boreholes · quantities from the design · cost ≠ price
            </span>
          </div>
        </div>

        <div className="boq">
          <div className="boq-row is-head">
            <span className="boq-desc">Item</span>
            <span className="boq-unit">Unit</span>
            <span className="boq-qty">Quantity</span>
            <span className="boq-rate">Unit cost US$</span>
            <span className="boq-cost">Amount US$</span>
          </div>

          {stages.map((stage) => {
            const lines = c.items.filter((i) => i.stage === stage);
            const subtotal = lines.reduce((s, l) => s + l.amount, 0);
            return (
              <div key={stage}>
                <div className="boq-row is-stage">
                  <span className="boq-desc">
                    <span className="boq-swatch" style={{ background: colourFor(stage) }} />
                    {stage}
                  </span>
                  <span className="boq-unit" />
                  <span className="boq-qty" />
                  <span className="boq-rate" />
                  <span className="boq-cost">{usd(subtotal)}</span>
                </div>
                {lines.map((l) => (
                  <div className="boq-row" key={l.code}>
                    <span className="boq-desc">
                      {l.item}
                      {l.note && <em>{l.note}</em>}
                    </span>
                    <span className="boq-unit">{l.unit}</span>
                    <span
                      className={`boq-qty${DESIGN_DRIVEN.test(l.item) ? ' is-derived' : ''}`}
                    >
                      {qty(l.quantity, l.unit)}
                    </span>
                    <span className="boq-rate is-static">{usd(l.unitCost)}</span>
                    <span className="boq-cost">{usd(l.amount)}</span>
                  </div>
                ))}
              </div>
            );
          })}

          <div className="boq-row is-total">
            <span className="boq-desc">Direct works cost</span>
            <span className="boq-unit" />
            <span className="boq-qty" />
            <span className="boq-rate" />
            <span className="boq-cost">{usd(c.directCost)}</span>
          </div>
        </div>

        <div className="boq-note">
          Quantities in teal come from the borehole design — move a screen on the
          Design stage and the casing, screen and gravel pack lines follow, because
          both come from the same <code>BoreholeDesign</code>. Unit costs are the
          contractor's cost from the toolkit's rate table, not the price; overheads
          and margin are applied once, on the right.
        </div>

        {c.assumptions.length > 0 && (
          <div className="boq-note is-assumptions">
            <strong>Assumptions filled in where the design is silent:</strong>
            <ul>
              {c.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      <aside className="rail">
        <div className="rail-head">Derived decisions</div>

        <div className="yield-card">
          <div className="eyebrow">Price to client</div>
          <div className="yield-value">
            <span className="unit">US$</span> {usd(c.price)}
          </div>
          <div className="yield-method">
            Direct {usd(c.directCost)} + overheads {c.overheadsPercent}% ({usd(c.overheads)})
            = cost {usd(c.totalCost)}; + margin {c.marginPercent}% ({usd(c.margin)}).
            {c.contingencyPercent > 0 &&
              ` A ${c.contingencyPercent}% client-side contingency is shown separately, so the contract price stays honest.`}
          </div>
          <div className="chip-row">
            <span className="chip">US$ {usd(c.costPerMetre)} / m</span>
            <span className="chip">
              SLE {usd(c.price * c.exchangeRate)}
            </span>
          </div>
        </div>

        <div className="rail-head">By stage</div>
        <div className="split-bar">
          {c.byStage.map((s) => (
            <span
              key={s.label}
              style={{ width: `${s.share}%`, background: colourFor(s.label) }}
              title={s.label}
            />
          ))}
        </div>
        <div className="split-legend">
          {c.byStage.map((s) => (
            <span key={s.label}>
              <span className="boq-swatch" style={{ background: colourFor(s.label) }} />
              {s.label}
              <em>{s.share}%</em>
            </span>
          ))}
        </div>

        <div className="rail-head">By category</div>
        <div className="checks">
          {c.byCategory.map((r) => (
            <div className="check" key={r.label}>
              <span className="check-label">{r.label}</span>
              <span className="check-value">
                {usd(r.amount)} · {r.share}%
              </span>
            </div>
          ))}
        </div>

        <div className="rail-head">Quantities from the design</div>
        <div className="checks">
          {[
            ['Total depth', c.quantityBasis.totalDepthM, 'm'],
            ['Plain casing', c.quantityBasis.casingM, 'm'],
            ['Screen', c.quantityBasis.screenM, 'm'],
            ['Gravel pack interval', c.quantityBasis.gravelIntervalM, 'm'],
            ['Overburden', c.quantityBasis.overburdenM, 'm'],
          ].map(([label, value, unit]) => (
            <div className="check" key={label as string}>
              <span className="check-label">{label as string}</span>
              <span className="check-value">
                {value ?? '—'} {unit as string}
              </span>
            </div>
          ))}
        </div>

        <div className="rail-head">Flags on this estimate</div>
        <FlagsList flags={c.flags} empty="No flags raised on the estimate." />

        <div className="spacer" />

        <SignOff
          stage="costing"
          recommended={`US$ ${usd(c.price)}`}
          writesTo="accepting writes to the cost estimate and the bill of quantities"
          decision={decision}
          clean={c.flags.every((f) => f.level === 'info')}
          onDecide={onDecide}
          override={{
            kind: 'number',
            label: 'Price to client',
            unit: 'US$',
            start: Math.round(c.price),
            step: 50,
            min: 0,
            max: 500000,
            format: (n) => `US$ ${usd(n)}`,
          }}
        />
      </aside>
    </div>
  );
}
