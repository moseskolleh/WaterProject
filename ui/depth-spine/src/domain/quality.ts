/**
 * Water quality — the assessment, the hydrochemistry and the derived verdict.
 *
 * The spine here is the guideline itself: every determinand is expressed as a
 * multiple of its guideline value, so exceedance is a line crossed rather than
 * a number compared. Piper and Stiff describe the water; the balance check says
 * whether the analysis can be believed at all.
 */

import type { Check, CheckStatus, Verdict } from './derive';

export type Basis = 'health' | 'acceptability' | 'microbiological';

export interface Determinand {
  id: string;
  label: string;
  unit: string;
  value: number;
  /** WHO guideline value. `null` where WHO sets none. */
  who: number | null;
  /** Lower bound where the guideline is a range (pH only). */
  whoMin?: number;
  basis: Basis;
  /** Shown on the trace, not judged. */
  informational?: boolean;
}

/** Ion concentrations in mg/L, for the balance check and the diagrams. */
export interface Ions {
  ca: number;
  mg: number;
  na: number;
  k: number;
  hco3: number;
  cl: number;
  so4: number;
  no3: number;
}

export interface WaterSample {
  boreholeId: string;
  sampledOn: string;
  laboratory: string;
  /** Hours between sampling and analysis. */
  transitHours: number;
  temperatureC: number;
  preserved: boolean;
  determinands: Determinand[];
  ions: Ions;
}

/** Equivalent weights, mg per meq. */
const EQ = {
  ca: 20.04,
  mg: 12.15,
  na: 22.99,
  k: 39.1,
  hco3: 61.02,
  cl: 35.45,
  so4: 48.03,
  no3: 62.0,
} as const;

export const drTimboSample: WaterSample = {
  boreholeId: 'dr-timbo-bh-01',
  sampledOn: '18 March 2026',
  laboratory: 'SLARI Water Laboratory, Freetown',
  transitHours: 26,
  temperatureC: 28,
  preserved: true,
  determinands: [
    { id: 'ecoli', label: 'E. coli', unit: 'cfu/100 mL', value: 0, who: 0, basis: 'microbiological' },
    { id: 'tcoliform', label: 'Total coliforms', unit: 'cfu/100 mL', value: 0, who: 0, basis: 'microbiological' },
    { id: 'arsenic', label: 'Arsenic', unit: 'mg/L', value: 0.002, who: 0.01, basis: 'health' },
    { id: 'fluoride', label: 'Fluoride', unit: 'mg/L', value: 0.35, who: 1.5, basis: 'health' },
    { id: 'nitrate', label: 'Nitrate as NO₃', unit: 'mg/L', value: 4.2, who: 50, basis: 'health' },
    { id: 'manganese', label: 'Manganese', unit: 'mg/L', value: 0.08, who: 0.08, basis: 'health' },
    { id: 'iron', label: 'Iron', unit: 'mg/L', value: 0.4, who: 0.3, basis: 'acceptability' },
    { id: 'turbidity', label: 'Turbidity', unit: 'NTU', value: 1.8, who: 5, basis: 'acceptability' },
    { id: 'tds', label: 'Total dissolved solids', unit: 'mg/L', value: 137, who: 1000, basis: 'acceptability' },
    { id: 'chloride', label: 'Chloride', unit: 'mg/L', value: 18, who: 250, basis: 'acceptability' },
    { id: 'sulphate', label: 'Sulphate', unit: 'mg/L', value: 11, who: 250, basis: 'acceptability' },
    { id: 'hardness', label: 'Hardness as CaCO₃', unit: 'mg/L', value: 70, who: 500, basis: 'acceptability' },
    { id: 'ph', label: 'pH', unit: '', value: 6.4, who: 8.5, whoMin: 6.5, basis: 'acceptability' },
    { id: 'ec', label: 'Conductivity', unit: 'µS/cm', value: 210, who: null, basis: 'acceptability', informational: true },
  ],
  ions: { ca: 18, mg: 6.2, na: 9.5, k: 2.4, hco3: 73, cl: 18, so4: 11, no3: 4.2 },
};

export interface MeqSet {
  ca: number;
  mg: number;
  naK: number;
  hco3: number;
  cl: number;
  so4: number;
  cations: number;
  anions: number;
}

export function toMeq(ions: Ions): MeqSet {
  const ca = ions.ca / EQ.ca;
  const mg = ions.mg / EQ.mg;
  const naK = ions.na / EQ.na + ions.k / EQ.k;
  const hco3 = ions.hco3 / EQ.hco3;
  const cl = ions.cl / EQ.cl;
  const so4 = ions.so4 / EQ.so4;
  const no3 = ions.no3 / EQ.no3;
  return {
    ca,
    mg,
    naK,
    hco3,
    cl,
    so4,
    cations: ca + mg + naK,
    anions: hco3 + cl + so4 + no3,
  };
}

/** Percentage of total cation / anion meq — the Piper and Stiff inputs. */
export interface Percentages {
  ca: number;
  mg: number;
  naK: number;
  hco3: number;
  cl: number;
  so4: number;
}

export function percentages(m: MeqSet): Percentages {
  return {
    ca: m.ca / m.cations,
    mg: m.mg / m.cations,
    naK: m.naK / m.cations,
    hco3: m.hco3 / m.anions,
    cl: m.cl / m.anions,
    so4: m.so4 / m.anions,
  };
}

/** Hill-Piper water type from the dominant ions (>50 % meq, else "mixed"). */
export function waterType(p: Percentages): string {
  const cat = p.ca > 0.5 ? 'Ca' : p.mg > 0.5 ? 'Mg' : p.naK > 0.5 ? 'Na+K' : 'Ca–Mg';
  const an = p.hco3 > 0.5 ? 'HCO₃' : p.cl > 0.5 ? 'Cl' : p.so4 > 0.5 ? 'SO₄' : 'mixed';
  return `${cat}–${an}`;
}

/**
 * Langelier Saturation Index. Negative means the water is undersaturated with
 * respect to calcite — it will dissolve metal, which is the whole question for
 * a galvanised handpump rising main in soft basement groundwater.
 */
export function langelier(sample: WaterSample, m: MeqSet): number {
  const tds = sample.determinands.find((d) => d.id === 'tds')?.value ?? 150;
  const ph = sample.determinands.find((d) => d.id === 'ph')?.value ?? 7;
  const caHardness = 50 * m.ca; // as CaCO3
  const alkalinity = 50 * m.hco3; // as CaCO3
  const A = (Math.log10(tds) - 1) / 10;
  const B = -13.12 * Math.log10(sample.temperatureC + 273.15) + 34.55;
  const C = Math.log10(caHardness) - 0.4;
  const D = Math.log10(alkalinity);
  return ph - (9.3 + A + B - C - D);
}

export interface DeterminandResult extends Determinand {
  /** Value as a multiple of the guideline. 1.0 is the guideline itself. */
  ratio: number | null;
  status: CheckStatus | 'none';
}

export type Potability = 'potable' | 'potable-with-caveat' | 'not-potable';

export interface QualityDerived {
  results: DeterminandResult[];
  meq: MeqSet;
  pct: Percentages;
  waterType: string;
  /** Ionic balance error, per cent. Signed: negative means anion excess. */
  balanceError: number;
  lsi: number;
  corrosion: { level: 'low' | 'moderate' | 'high'; advice: string };
  potability: Potability;
  verdict: Verdict;
  checks: Check[];
  exceedances: DeterminandResult[];
  withinCount: number;
  judgedCount: number;
}

const BALANCE_LIMIT = 5;

export function deriveQuality(sample: WaterSample): QualityDerived {
  const results: DeterminandResult[] = sample.determinands.map((d) => {
    if (d.who === null || d.informational) {
      return { ...d, ratio: null, status: 'none' as const };
    }
    // pH is a range: express distance from whichever bound it breaks.
    if (d.whoMin !== undefined) {
      const inRange = d.value >= d.whoMin && d.value <= d.who;
      return {
        ...d,
        ratio: d.value / d.who,
        status: inRange ? ('ok' as const) : ('warn' as const),
      };
    }
    // A zero guideline (E. coli) is pass/fail, not a ratio.
    if (d.who === 0) {
      return {
        ...d,
        ratio: d.value > 0 ? 2 : 0,
        status: d.value > 0 ? ('warn' as const) : ('ok' as const),
      };
    }
    const ratio = d.value / d.who;
    return { ...d, ratio, status: ratio > 1 ? ('warn' as const) : ('ok' as const) };
  });

  const judged = results.filter((r) => r.status !== 'none');
  const exceedances = judged.filter((r) => r.status === 'warn');
  const healthFails = exceedances.filter(
    (r) => r.basis === 'health' || r.basis === 'microbiological',
  );

  const meq = toMeq(sample.ions);
  const pct = percentages(meq);
  const balanceError =
    ((meq.cations - meq.anions) / (meq.cations + meq.anions)) * 100;
  const lsi = langelier(sample, meq);

  const corrosion =
    lsi < -1.5
      ? {
          level: 'high' as const,
          advice:
            'Strongly undersaturated — specify stainless steel or uPVC rising main and rods. Galvanised iron will corrode and iron will rise in the delivered water.',
        }
      : lsi < -0.5
        ? {
            level: 'moderate' as const,
            advice:
              'Mildly aggressive — avoid galvanised iron below the pumping level; stainless or uPVC preferred.',
          }
        : {
            level: 'low' as const,
            advice: 'Water is close to calcite saturation; standard components are acceptable.',
          };

  const potability: Potability =
    healthFails.length > 0
      ? 'not-potable'
      : exceedances.length > 0
        ? 'potable-with-caveat'
        : 'potable';

  const verdict: Verdict =
    potability === 'not-potable'
      ? {
          status: 'warn',
          title: 'Not potable without treatment',
          detail: `${healthFails.map((r) => r.label).join(', ')} exceeds the WHO health-based guideline value.`,
        }
      : potability === 'potable-with-caveat'
        ? {
            status: 'ok',
            title: 'Potable — aesthetic exceedance',
            detail: `${exceedances.map((r) => `${r.label} ${r.value} ${r.unit}`).join('; ')} — above the acceptability threshold but not a health risk. Expect staining and taste complaints; users may reject the source.`,
          }
        : {
            status: 'ok',
            title: 'Potable',
            detail: `All ${judged.length} judged determinands are within WHO guideline values.`,
          };

  const checks: Check[] = [
    {
      id: 'micro',
      label: 'Bacteriological — E. coli, total coliforms',
      value: '0 / 100 mL',
      status: results
        .filter((r) => r.basis === 'microbiological')
        .every((r) => r.status === 'ok')
        ? 'ok'
        : 'warn',
    },
    {
      id: 'health',
      label: 'Health-based determinands within GV',
      value: `${judged.filter((r) => r.basis === 'health').length - healthFails.filter((r) => r.basis === 'health').length}/${judged.filter((r) => r.basis === 'health').length}`,
      status: healthFails.length === 0 ? 'ok' : 'warn',
    },
    {
      id: 'aesthetic',
      label:
        exceedances.filter((r) => r.basis === 'acceptability').length > 0
          ? `Acceptability — ${exceedances
              .filter((r) => r.basis === 'acceptability')
              .map((r) => r.label)
              .join(', ')}`
          : 'Acceptability thresholds',
      value:
        exceedances.filter((r) => r.basis === 'acceptability').length > 0
          ? 'check'
          : 'pass',
      status:
        exceedances.filter((r) => r.basis === 'acceptability').length > 0
          ? 'warn'
          : 'ok',
    },
    {
      id: 'balance',
      label: `Ionic balance within ±${BALANCE_LIMIT} %`,
      value: `${balanceError > 0 ? '+' : ''}${balanceError.toFixed(1)} %`,
      status: Math.abs(balanceError) <= BALANCE_LIMIT ? 'ok' : 'warn',
    },
    {
      id: 'corrosion',
      label: `Handpump corrosion risk — LSI ${lsi.toFixed(1)}`,
      value: corrosion.level,
      status: corrosion.level === 'low' ? 'ok' : 'warn',
    },
    {
      id: 'handling',
      label: `Sample preserved, ${sample.transitHours} h to laboratory`,
      value: sample.preserved && sample.transitHours <= 48 ? 'pass' : 'check',
      status: sample.preserved && sample.transitHours <= 48 ? 'ok' : 'warn',
    },
  ];

  return {
    results,
    meq,
    pct,
    waterType: waterType(pct),
    balanceError,
    lsi,
    corrosion,
    potability,
    verdict,
    checks,
    exceedances,
    withinCount: judged.length - exceedances.length,
    judgedCount: judged.length,
  };
}
