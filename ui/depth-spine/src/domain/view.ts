/**
 * The view payload, as built by groundwater.depth_spine.view.
 *
 * These are types only. Nothing in this application computes a hydrogeological
 * number: the safe yield, the design, the guideline comparison and the bill of
 * quantities are all produced by the Python package that produces the reports,
 * so the screen and the .docx cannot disagree. The browser owns the depth-to-
 * pixel mapping and the pointer, and that is all.
 */

export interface Site {
  community: string;
  district: string;
  chiefdom: string;
  client: string;
  boreholeRef: string;
  latlon: [number, number] | null;
}

export interface LithologyInterval {
  top: number;
  base: number;
  description: string;
  aquifer: boolean;
}

export type SegmentKind = 'plain' | 'screen' | 'sump';

export interface Segment {
  kind: SegmentKind;
  top: number;
  base: number;
}

export interface Levels {
  restLevel?: number;
  pumpingLevel?: number;
  maxDrawdown?: number;
  pumpIntake?: number;
  /** False when the level was still falling at the end of the test. */
  stabilised?: boolean;
}

export interface ScreenLimits {
  top: number;
  base: number;
  minLength: number;
}

export interface Section {
  totalDepth: number;
  /** Depth at the foot of the track — a little below the hole. */
  domain: number;
  lithology: LithologyInterval[];
  waterStrikes: number[];
  segments: Segment[];
  gravelPack: [number, number];
  backfill: [number, number];
  sanitarySeal: [number, number];
  levels: Levels;
  boreDiameterIn: number;
  casingDiameterIn: number;
  casingMaterial: string;
  slotMm: number;
  stickupM: number;
  drillingMethod: string;
  screenLimits: ScreenLimits;
}

/** A DataFlag from the toolkit — the same objects the reports carry. */
export interface Flag {
  level: 'info' | 'warning' | 'error';
  code: string;
  message: string;
  context: string;
}

export interface MethodResult {
  label: string;
  transmissivity: number | null;
}

export interface YieldBlock {
  pending: string;
  safeYieldM3PerH?: number | null;
  lowM3PerH?: number | null;
  highM3PerH?: number | null;
  rangeText?: string;
  longTermM3PerH?: number | null;
  specificCapacity?: number | null;
  availableDrawdownM?: number | null;
  usableDrawdownM?: number | null;
  pumpDepthM?: number | null;
  safetyFactor?: number;
  designPeriodDays?: number;
  basis?: string;
  envelopeBasis?: string;
  transmissivity?: number | null;
  methods?: MethodResult[];
}

export interface DesignRules {
  sumpLengthM: number;
  gravelAboveTopScreenM: number;
  sanitarySealDepthM: number;
  minScreenBelowSwlM: number;
  submergenceMinM: number;
  seasonalAllowanceM: number;
}

export interface DesignBlock {
  yield: YieldBlock;
  screens: { top: number; base: number }[];
  totalScreenM: number;
  screenShare: number;
  slotMm: number;
  rules: DesignRules;
  basis: string[];
  flags: Flag[];
}

// Every status groundwater/quality/assess.py can emit. It has to be the
// complete set: a status the union omits is one the tone mapping below falls
// through on, and falling through drew an ungraded row green.
export type ParameterStatus =
  | 'within_limits'
  | 'exceeds_health'
  | 'exceeds_aesthetic'
  | 'exceeds_national'
  | 'indeterminate'
  | 'below_detection'
  | 'no_guideline'
  | 'not_measured';

export interface QualityRow {
  parameter: string;
  value: number | null;
  unit: string;
  belowDetection: boolean;
  whoHealth: string;
  whoAesthetic: string;
  national: string;
  status: ParameterStatus;
  remark: string;
  limitKind: 'max' | 'range' | 'none';
  limitName: string;
  limitMax: number | null;
  limitMin: number | null;
  /** Value as a multiple of the binding limit. Null when there is none. */
  ratio: number | null;
}

export interface IonicBalance {
  cationsMeq: number;
  anionsMeq: number;
  errorPercent: number;
  cations: Record<string, number>;
  anions: Record<string, number>;
  usedAlkalinity: boolean;
}

export interface Corrosivity {
  lsi: number | null;
  rsi: number | null;
  aggressiveIndex: number | null;
  larsonSkold: number | null;
  classification: string;
  isAggressive: boolean;
  verdict: string;
  materialsNote: string;
  assumptions: string[];
}

export interface PiperData {
  meq: { ca: number; mg: number; naK: number; hco3: number; cl: number; so4: number };
  percent: { ca: number; mg: number; naK: number; hco3: number; cl: number; so4: number };
}

export interface QualityBlock {
  sampleId: string;
  sampleDate: string;
  laboratory: string;
  rows: QualityRow[];
  verdict: string;
  verdictState: 'health_fail' | 'national_fail' | 'indeterminate' | 'aesthetic' | 'pass';
  uncertainties: string[];
  healthExceedances: string[];
  nationalExceedances: string[];
  aestheticExceedances: string[];
  indeterminate: string[];
  ionic: IonicBalance | null;
  piper: PiperData | null;
  corrosivity: Corrosivity | null;
  wqi: { value: number; rating: string } | null;
  flags: Flag[];
}

export interface CostItem {
  code: string;
  stage: string;
  category: string;
  item: string;
  unit: string;
  quantity: number;
  unitCost: number;
  amount: number;
  note: string;
}

export interface CostGroup {
  label: string;
  amount: number;
  share: number;
}

export interface CostingBlock {
  items: CostItem[];
  byStage: CostGroup[];
  byCategory: CostGroup[];
  directCost: number;
  overheads: number;
  totalCost: number;
  margin: number;
  price: number;
  vat: number;
  costPerMetre: number;
  overheadsPercent: number;
  marginPercent: number;
  contingencyPercent: number;
  vatPercent: number;
  exchangeRate: number;
  assumptions: string[];
  flags: Flag[];
  quantityBasis: {
    totalDepthM: number;
    casingM: number | null;
    screenM: number | null;
    gravelIntervalM: number | null;
    overburdenM: number | null;
  };
}

export interface SpineView {
  project: string;
  site: Site;
  section: Section;
  design: DesignBlock;
  costing: CostingBlock;
  quality: QualityBlock | null;
  /** True when this payload was re-derived from analyst-placed screens. */
  edited: boolean;
}

/** What the component sends back to Python. */
export interface SpineResult {
  screens?: [number, number][];
  ledger?: Record<string, unknown>;
}
