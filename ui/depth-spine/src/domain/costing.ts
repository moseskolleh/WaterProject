/**
 * Cost estimate and bill of quantities, RWSN Cost-Effective Boreholes method.
 *
 * Two things the methodology insists on, and this module enforces:
 *   1. Quantities come from the design, not from a typing exercise. Drag the
 *      screen on the spine and the casing, screen, gravel pack and grout lines
 *      here move with it.
 *   2. Cost and price are different numbers. Cost is what it takes to build;
 *      price is cost plus overhead plus margin. They are never conflated.
 */

import type { Borehole } from './types';
import type { Derived } from './derive';

export type Stage =
  | 'mobilisation'
  | 'drilling'
  | 'materials'
  | 'development'
  | 'wellhead'
  | 'services';

export type Resource = 'plant' | 'labour' | 'materials' | 'transport' | 'services';

export const STAGE_LABELS: Record<Stage, string> = {
  mobilisation: 'Mobilisation',
  drilling: 'Drilling',
  materials: 'Materials & construction',
  development: 'Development & testing',
  wellhead: 'Wellhead & pump',
  services: 'Services & supervision',
};

export const STAGE_COLOURS: Record<Stage, string> = {
  mobilisation: 'oklch(0.72 0.13 190)',
  drilling: 'oklch(0.66 0.12 210)',
  materials: 'oklch(0.7 0.13 145)',
  development: 'oklch(0.78 0.13 110)',
  wellhead: 'oklch(0.8 0.14 75)',
  services: 'oklch(0.72 0.11 40)',
};

export const RESOURCE_LABELS: Record<Resource, string> = {
  plant: 'Plant & equipment',
  labour: 'Labour',
  materials: 'Materials',
  transport: 'Transport',
  services: 'Services',
};

export interface RateItem {
  id: string;
  description: string;
  unit: string;
  stage: Stage;
  resource: Resource;
  /** Unit cost to the contractor, US$. Editable. */
  rate: number;
  /** How the quantity falls out of the design. */
  quantity: (bh: Borehole, d: Derived) => number;
  /** Shown under the description when the quantity is design-driven. */
  basis?: string;
}

/** Annulus volume between the drilled hole and the casing, m³ per metre. */
function annulusPerMetre(bh: Borehole): number {
  const bore = bh.construction.boreDiameter / 1000;
  const casing = bh.construction.casingDiameter / 1000;
  return (Math.PI / 4) * (bore * bore - casing * casing);
}

export const RATE_SCHEDULE: RateItem[] = [
  {
    id: 'mob',
    description: 'Mobilisation and demobilisation of rig and crew',
    unit: 'sum',
    stage: 'mobilisation',
    resource: 'transport',
    rate: 1150,
    quantity: () => 1,
  },
  {
    id: 'site-prep',
    description: 'Site preparation, access and set-up',
    unit: 'sum',
    stage: 'mobilisation',
    resource: 'labour',
    rate: 180,
    quantity: () => 1,
  },
  {
    id: 'drill-overburden',
    description: 'Drilling 165 mm through overburden',
    unit: 'm',
    stage: 'drilling',
    resource: 'plant',
    rate: 42,
    basis: 'to base of weathered zone',
    quantity: (_bh, d) => d.overburden,
  },
  {
    id: 'drill-rock',
    description: 'Drilling 165 mm in fresh and fractured basement',
    unit: 'm',
    stage: 'drilling',
    resource: 'plant',
    rate: 68,
    basis: 'overburden base to TD',
    quantity: (bh, d) => bh.construction.totalDepth - d.overburden,
  },
  {
    id: 'temp-casing',
    description: 'Temporary casing through unstable overburden',
    unit: 'm',
    stage: 'drilling',
    resource: 'plant',
    rate: 12,
    quantity: (_bh, d) => d.overburden,
  },
  {
    id: 'plain-casing',
    description: 'uPVC 125 mm plain casing, supply and install',
    unit: 'm',
    stage: 'materials',
    resource: 'materials',
    rate: 20,
    basis: 'surface to screen top, plus sump',
    quantity: (_bh, d) => d.screenTop + (d.sumpBase - d.screenBase),
  },
  {
    id: 'screen',
    description: 'uPVC 125 mm slotted screen, supply and install',
    unit: 'm',
    stage: 'materials',
    resource: 'materials',
    rate: 34,
    basis: 'screened interval',
    quantity: (_bh, d) => d.screenLength,
  },
  {
    id: 'gravel-pack',
    description: 'Graded gravel pack placed by tremie',
    unit: 'm³',
    stage: 'materials',
    resource: 'materials',
    rate: 220,
    basis: 'annulus over pack interval',
    quantity: (bh, d) => annulusPerMetre(bh) * (d.packBase - d.packTop),
  },
  {
    id: 'seal',
    description: 'Sanitary seal, cement grout',
    unit: 'm³',
    stage: 'materials',
    resource: 'materials',
    rate: 260,
    basis: 'annulus over seal depth',
    quantity: (bh) => annulusPerMetre(bh) * bh.construction.sanitarySealBase,
  },
  {
    id: 'backfill',
    description: 'Formation backfill above gravel pack',
    unit: 'm³',
    stage: 'materials',
    resource: 'materials',
    rate: 60,
    basis: 'seal base to pack top',
    quantity: (bh, d) =>
      annulusPerMetre(bh) *
      Math.max(0, d.packTop - bh.construction.sanitarySealBase),
  },
  {
    id: 'development',
    description: 'Well development by air-lifting to clear discharge',
    unit: 'h',
    stage: 'development',
    resource: 'plant',
    rate: 95,
    quantity: () => 4,
  },
  {
    id: 'pumping-test',
    description: 'Constant-rate pumping test with recovery',
    unit: 'no.',
    stage: 'development',
    resource: 'services',
    rate: 560,
    quantity: () => 1,
  },
  {
    id: 'water-quality',
    description: 'Water quality sampling and laboratory analysis',
    unit: 'no.',
    stage: 'development',
    resource: 'services',
    rate: 210,
    quantity: () => 1,
  },
  {
    id: 'disinfection',
    description: 'Disinfection of well and rising main',
    unit: 'sum',
    stage: 'development',
    resource: 'materials',
    rate: 45,
    quantity: () => 1,
  },
  {
    id: 'wellhead',
    description: 'Wellhead works, apron and drainage channel',
    unit: 'no.',
    stage: 'wellhead',
    resource: 'labour',
    rate: 420,
    quantity: () => 1,
  },
  {
    id: 'handpump',
    description: 'Handpump supply and installation, India Mk II',
    unit: 'no.',
    stage: 'wellhead',
    resource: 'materials',
    rate: 1050,
    quantity: () => 1,
  },
  {
    id: 'rising-main',
    description: 'Rising main and pump rods to setting depth',
    unit: 'm',
    stage: 'wellhead',
    resource: 'materials',
    rate: 18,
    basis: 'pump setting depth',
    quantity: (_bh, d) => d.pumpSetting,
  },
  {
    id: 'supervision',
    description: 'Supervision, records and completion reporting',
    unit: 'sum',
    stage: 'services',
    resource: 'services',
    rate: 460,
    quantity: () => 1,
  },
];

export interface Markup {
  /** Site and head-office overhead, per cent of cost. */
  overheadPct: number;
  /** Profit margin, per cent of cost plus overhead. */
  marginPct: number;
}

export const DEFAULT_MARKUP: Markup = { overheadPct: 4, marginPct: 6 };

export interface BoqLine {
  id: string;
  description: string;
  basis?: string;
  unit: string;
  stage: Stage;
  resource: Resource;
  quantity: number;
  rate: number;
  cost: number;
  /** True when the quantity comes from the borehole design. */
  designDriven: boolean;
}

export interface CostDerived {
  lines: BoqLine[];
  cost: number;
  overhead: number;
  margin: number;
  price: number;
  pricePerMetre: number;
  byStage: { stage: Stage; cost: number; share: number }[];
  byResource: { resource: Resource; cost: number; share: number }[];
  /** Lines whose quantity moved with the current screen interval. */
  designDrivenCost: number;
}

export function deriveCost(
  bh: Borehole,
  d: Derived,
  rates: Record<string, number>,
  markup: Markup,
): CostDerived {
  const lines: BoqLine[] = RATE_SCHEDULE.map((item) => {
    const quantity = item.quantity(bh, d);
    const rate = rates[item.id] ?? item.rate;
    return {
      id: item.id,
      description: item.description,
      basis: item.basis,
      unit: item.unit,
      stage: item.stage,
      resource: item.resource,
      quantity,
      rate,
      cost: quantity * rate,
      designDriven: Boolean(item.basis),
    };
  });

  const cost = lines.reduce((sum, l) => sum + l.cost, 0);
  const overhead = cost * (markup.overheadPct / 100);
  const margin = (cost + overhead) * (markup.marginPct / 100);
  const price = cost + overhead + margin;

  const group = <K extends string>(key: (l: BoqLine) => K) => {
    const totals = new Map<K, number>();
    for (const l of lines) totals.set(key(l), (totals.get(key(l)) ?? 0) + l.cost);
    return [...totals.entries()]
      .map(([k, v]) => ({ key: k, cost: v, share: v / cost }))
      .sort((a, b) => b.cost - a.cost);
  };

  return {
    lines,
    cost,
    overhead,
    margin,
    price,
    pricePerMetre: price / bh.construction.totalDepth,
    byStage: group((l) => l.stage).map(({ key, cost: c, share }) => ({
      stage: key,
      cost: c,
      share,
    })),
    byResource: group((l) => l.resource).map(({ key, cost: c, share }) => ({
      resource: key,
      cost: c,
      share,
    })),
    designDrivenCost: lines
      .filter((l) => l.designDriven)
      .reduce((s, l) => s + l.cost, 0),
  };
}

/** Rates as a plain record, for editing. */
export function defaultRates(): Record<string, number> {
  return Object.fromEntries(RATE_SCHEDULE.map((i) => [i.id, i.rate]));
}

/** Multi-borehole programme view — shared mobilisation and expected dry holes. */
export interface ProgrammeInput {
  boreholes: number;
  /** Probability a given attempt is dry, from the siting outlook. */
  dryRate: number;
}

export interface ProgrammeDerived {
  attempts: number;
  dryAttempts: number;
  sharedSaving: number;
  total: number;
  perSuccessful: number;
}

export function deriveProgramme(
  unit: CostDerived,
  rates: Record<string, number>,
  input: ProgrammeInput,
): ProgrammeDerived {
  const attempts = input.boreholes / (1 - input.dryRate);
  const dryAttempts = attempts - input.boreholes;
  // Mobilisation is paid once for the programme, not once per borehole.
  const markupFactor = unit.cost > 0 ? unit.price / unit.cost : 1;
  const mobLine = unit.lines.find((l) => l.id === 'mob');
  const mob = (mobLine?.cost ?? rates.mob ?? 0) * markupFactor;
  const sharedSaving = mob * (input.boreholes - 1);
  // A dry hole still costs drilling and mobilisation-adjacent work, not
  // materials, pump or testing.
  const dryCost =
    unit.lines
      .filter((l) => l.stage === 'drilling' || l.id === 'site-prep')
      .reduce((s, l) => s + l.cost, 0) * markupFactor;
  const total =
    unit.price * input.boreholes - sharedSaving + dryCost * dryAttempts;
  return {
    attempts,
    dryAttempts,
    sharedSaving,
    total,
    perSuccessful: total / input.boreholes,
  };
}
