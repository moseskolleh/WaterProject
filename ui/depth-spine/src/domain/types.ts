/**
 * Domain model for the Depth Spine workspace (direction 2a).
 *
 * Everything in this file is indexed by depth in metres below ground level.
 * The spine only works if every column reads the same numbers, so nothing here
 * is expressed in pixels — the pixel mapping lives in `scale.ts` alone.
 */

/** A resistivity layer from the inverted VES model. */
export interface VesLayer {
  /** Depth to top of layer, metres below ground level. */
  top: number;
  /** Depth to base. `null` means the half-space — drawn to the foot of the track. */
  base: number | null;
  /** Apparent resistivity, ohm-metres. */
  rho: number;
  /** True for the interval interpreted as the target aquifer. */
  aquifer?: boolean;
}

export type LithologyFill =
  | 'topsoil'
  | 'clayey-sand'
  | 'saprolite'
  | 'fractured'
  | 'fresh';

/** A described unit from the drillers' cuttings log. */
export interface LithologyUnit {
  top: number;
  base: number | null;
  name: string;
  /** Second line under the name — weathering state, aquifer note, and so on. */
  note?: string;
  fill: LithologyFill;
  aquifer?: boolean;
}

/** Screen slot geometry — fixes the open area per metre of screen. */
export interface ScreenSpec {
  /** Slot width (aperture), mm. */
  slotWidth: number;
  /** Slot length, mm. */
  slotLength: number;
  /** Number of slot rows around the circumference. */
  rows: number;
  /** Vertical pitch between slots in a row, mm. */
  pitch: number;
}

export interface Construction {
  /** Drilled diameter, mm. */
  boreDiameter: number;
  /** Casing / screen outside diameter, mm. */
  casingDiameter: number;
  casingMaterial: string;
  /** Depth to top of the screened interval — user-editable via the handles. */
  screenTop: number;
  /** Depth to base of the screened interval — user-editable via the handles. */
  screenBase: number;
  /** Base of the sanitary (grout) seal. */
  sanitarySealBase: number;
  /** Total drilled depth. */
  totalDepth: number;
  screen: ScreenSpec;
}

export interface Hydraulics {
  /** Static (rest) water level. */
  restLevel: number;
  /** Stabilised pumping level at the test rate. */
  pumpingLevel: number;
  /** Constant-rate test discharge, L/s. */
  testRate: number;
  /** Test duration, minutes. */
  testDuration: number;
  /** Drawdown per log cycle from the Cooper-Jacob straight-line fit, metres. */
  drawdownPerLogCycle: number;
  /** Safety factor applied to the test rate to certify a safe yield. */
  safetyFactor: number;
}

/** Field-measured acceptance results that are recorded, not derived. */
export interface FieldRecord {
  /** Sand content after development, ppm. */
  sandContent: number;
  sandContentLimit: number;
  /** Verticality over the drilled depth, degrees. */
  verticality: number;
  verticalityLimit: number;
}

export interface Borehole {
  id: string;
  name: string;
  locality: string;
  terrain: string;
  ves: VesLayer[];
  lithology: LithologyUnit[];
  /** Depths at which water was struck while drilling. */
  waterStrikes: number[];
  construction: Construction;
  hydraulics: Hydraulics;
  field: FieldRecord;
}

/** The subset of the model the screen handles mutate. */
export interface ScreenInterval {
  screenTop: number;
  screenBase: number;
}
