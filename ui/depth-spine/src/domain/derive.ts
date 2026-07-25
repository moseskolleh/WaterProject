import type { Borehole, ScreenInterval } from './types';

/**
 * Everything downstream of the screen interval.
 *
 * The point of the Depth Spine is that the screen is the design decision and
 * the rest follows from it. So this module takes the borehole plus the current
 * screen interval and returns every derived number and check in one pass —
 * drag a handle, call this again, and the whole right-hand rail is correct.
 */

/** Design rules, all in metres unless stated. */
export const RULES = {
  /** Pump intake is set this far above the base of the screen. */
  pumpAboveScreenBase: 2,
  /** Minimum water column above the intake at the design yield. */
  minSubmergence: 3,
  /** Gravel pack extends this far above the top of the screen. */
  packAboveScreen: 4,
  /** Gravel pack extends this far below the base of the screen. */
  packBelowScreen: 3,
  /** Sump length below the screen. */
  sumpLength: 3,
  /** RWSN guidance for the depth of the sanitary seal. */
  advisedSealDepth: 9,
  /** Maximum entrance velocity through the screen, m/s. */
  maxEntranceVelocity: 0.03,
  /** Minimum useful open area, per cent. */
  minOpenAreaPct: 3,
  /** Shortest screen the handles will allow. */
  minScreenLength: 3,
} as const;

export type CheckStatus = 'ok' | 'warn';

export interface Check {
  id: string;
  label: string;
  /** Right-hand value on the row — the number that makes the check auditable. */
  value: string;
  status: CheckStatus;
}

export interface Verdict {
  status: CheckStatus;
  title: string;
  detail: string;
}

export interface Derived {
  // Screen
  screenTop: number;
  screenBase: number;
  screenLength: number;
  openAreaPct: number;
  openAreaM2: number;
  entranceVelocity: number;
  /** Slot depths for drawing the screen hatching. */
  packTop: number;
  packBase: number;
  sumpBase: number;

  // Hydraulics
  transmissivity: number;
  safeYield: number;
  drawdown: number;
  pumpSetting: number;
  submergence: number;

  // Interpretation
  overburden: number;
  aquiferTop: number;
  aquiferBase: number;
  strikesInScreen: number[];
  strikesMissed: number[];

  verdict: Verdict;
  checks: Check[];
}

const oneDp = (n: number) => Math.round(n * 10) / 10;

/** Clamp a proposed screen interval to the rules above and the borehole geometry. */
export function clampScreen(bh: Borehole, next: ScreenInterval): ScreenInterval {
  const { sanitarySealBase, totalDepth } = bh.construction;
  const deepest = totalDepth - RULES.sumpLength;
  const top = Math.min(
    Math.max(next.screenTop, sanitarySealBase),
    deepest - RULES.minScreenLength,
  );
  const base = Math.min(
    Math.max(next.screenBase, top + RULES.minScreenLength),
    deepest,
  );
  return { screenTop: oneDp(top), screenBase: oneDp(base) };
}

/**
 * Open area of the screen as a percentage of its wall — a property of the slot
 * geometry, so it does not change with length. The absolute open area and the
 * entrance velocity do, which is what the acceptance check actually cares about.
 */
function openArea(bh: Borehole, screenLength: number) {
  const { slotWidth, slotLength, rows, pitch } = bh.construction.screen;
  const od = bh.construction.casingDiameter;
  const slotsPerMetre = rows * (1000 / pitch);
  const openPerMetre = slotsPerMetre * slotLength * slotWidth; // mm² per m
  const wallPerMetre = Math.PI * od * 1000; // mm² per m
  const pct = (openPerMetre / wallPerMetre) * 100;
  const m2 = (pct / 100) * Math.PI * (od / 1000) * screenLength;
  return { pct, m2 };
}

export function derive(bh: Borehole, screen: ScreenInterval): Derived {
  const { screenTop, screenBase } = clampScreen(bh, screen);
  const screenLength = screenBase - screenTop;
  const { restLevel, pumpingLevel, testRate, safetyFactor, drawdownPerLogCycle } =
    bh.hydraulics;

  // Cooper-Jacob straight-line fit: T = 2.3 Q / (4 pi ds), Q in m3/day.
  const qPerDay = testRate * 86.4;
  const transmissivity = (2.3 * qPerDay) / (4 * Math.PI * drawdownPerLogCycle);
  const safeYield = testRate * safetyFactor;
  const drawdown = pumpingLevel - restLevel;

  const pumpSetting = Math.min(
    screenBase - RULES.pumpAboveScreenBase,
    bh.construction.totalDepth - RULES.sumpLength - RULES.pumpAboveScreenBase,
  );
  const submergence = pumpSetting - pumpingLevel;

  const { pct: openAreaPct, m2: openAreaM2 } = openArea(bh, screenLength);
  const entranceVelocity = safeYield / 1000 / openAreaM2; // m/s

  const packTop = screenTop - RULES.packAboveScreen;
  const packBase = Math.min(
    screenBase + RULES.packBelowScreen,
    bh.construction.totalDepth,
  );
  const sumpBase = Math.min(
    screenBase + RULES.sumpLength,
    bh.construction.totalDepth - 2,
  );

  const aquifer = bh.ves.find((l) => l.aquifer);
  const aquiferTop = aquifer?.top ?? 0;
  const aquiferBase = aquifer?.base ?? bh.construction.totalDepth;
  const overburden = aquiferTop;

  // A strike is captured if the screen spans it, or if it lies in the gravel
  // pack — the pack is continuous, so that inflow still drains to the screen.
  const total = bh.waterStrikes.length;
  const list = (ds: number[]) => ds.map((d) => d.toFixed(1)).join(', ');
  const strikesInScreen = bh.waterStrikes.filter(
    (d) => d >= screenTop && d <= screenBase,
  );
  const strikesInPack = bh.waterStrikes.filter(
    (d) => (d < screenTop || d > screenBase) && d >= packTop && d <= packBase,
  );
  const strikesMissed = bh.waterStrikes.filter((d) => d < packTop || d > packBase);

  let verdict: Verdict;
  if (strikesMissed.length > 0) {
    verdict = {
      status: 'warn',
      title: `Screen misses ${strikesMissed.length} of ${total} strikes`,
      detail:
        `${oneDp(screenTop)}–${oneDp(screenBase)} m leaves ${list(strikesMissed)} m ` +
        `outside both screen and gravel pack — that inflow is lost.`,
    };
  } else if (strikesInPack.length > 0) {
    verdict = {
      status: 'ok',
      title: `All ${total} strikes connected`,
      detail:
        `${oneDp(screenTop)}–${oneDp(screenBase)} m screens ${list(strikesInScreen)} m; ` +
        `${list(strikesInPack)} m sits outside the screen but inside the gravel pack ` +
        `(${oneDp(packTop)}–${oneDp(packBase)} m), so it still drains to it.`,
    };
  } else {
    verdict = {
      status: 'ok',
      title: `Screen brackets all ${total} strikes`,
      detail:
        `${oneDp(screenTop)}–${oneDp(screenBase)} m covers ${list(bh.waterStrikes)} m ` +
        `within the fractured interval.`,
    };
  }

  const packSpansScreen =
    packTop >= 0 &&
    screenTop - packTop >= 2 &&
    packBase - screenBase >= 2;
  const screenInAquifer = screenTop >= aquiferTop && screenBase <= aquiferBase;

  const checks: Check[] = [
    {
      id: 'submergence',
      label: 'Intake below pumping level',
      value: `${submergence >= 0 ? '+' : ''}${oneDp(submergence)} m`,
      status: submergence >= RULES.minSubmergence ? 'ok' : 'warn',
    },
    {
      id: 'gravel-pack',
      label: `Gravel pack spans screen +${RULES.packAboveScreen} m`,
      value: `${oneDp(packTop)}–${oneDp(packBase)}`,
      status: packSpansScreen ? 'ok' : 'warn',
    },
    {
      id: 'screen-in-aquifer',
      label: 'Screen inside the fractured interval',
      value: screenInAquifer
        ? `${oneDp(aquiferTop)}–${oneDp(aquiferBase)}`
        : 'outside',
      status: screenInAquifer ? 'ok' : 'warn',
    },
    {
      id: 'sand-content',
      label: 'Sand content after development',
      value: `${bh.field.sandContent} ppm`,
      status:
        bh.field.sandContent <= bh.field.sandContentLimit ? 'ok' : 'warn',
    },
    {
      id: 'sanitary-seal',
      label: `Sanitary seal ${oneDp(bh.construction.sanitarySealBase)} m — below ${RULES.advisedSealDepth} m advised`,
      value:
        bh.construction.sanitarySealBase >= RULES.advisedSealDepth
          ? 'pass'
          : 'check',
      status:
        bh.construction.sanitarySealBase >= RULES.advisedSealDepth
          ? 'ok'
          : 'warn',
    },
    {
      id: 'verticality',
      label: `Verticality ${bh.field.verticality}° over ${oneDp(bh.construction.totalDepth)} m`,
      value: bh.field.verticality <= bh.field.verticalityLimit ? 'pass' : 'fail',
      status: bh.field.verticality <= bh.field.verticalityLimit ? 'ok' : 'warn',
    },
  ];

  return {
    screenTop,
    screenBase,
    screenLength,
    openAreaPct,
    openAreaM2,
    entranceVelocity,
    packTop,
    packBase,
    sumpBase,
    transmissivity,
    safeYield,
    drawdown,
    pumpSetting,
    submergence,
    overburden,
    aquiferTop,
    aquiferBase,
    strikesInScreen,
    strikesMissed,
    verdict,
    checks,
  };
}
