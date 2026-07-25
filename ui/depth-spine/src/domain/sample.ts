import type { Borehole } from './types';

/**
 * Dr Timbo BH-01 — the sample project the design study is drawn from.
 * Representative values in the shape the real project file supplies.
 */
export const drTimboBh01: Borehole = {
  id: 'dr-timbo-bh-01',
  name: 'Dr Timbo BH-01',
  locality: 'Tonkolili',
  terrain: 'crystalline basement',

  ves: [
    { top: 0, base: 1.5, rho: 140 },
    { top: 1.5, base: 9, rho: 45 },
    { top: 9, base: 24, rho: 38 },
    { top: 24, base: 41, rho: 320, aquifer: true },
    { top: 41, base: null, rho: 2600 },
  ],

  lithology: [
    { top: 0, base: 1.5, name: 'Lateritic topsoil', fill: 'topsoil' },
    { top: 1.5, base: 9, name: 'Clayey sand', fill: 'clayey-sand' },
    {
      top: 9,
      base: 24,
      name: 'Sandy clay saprolite',
      note: 'weathered zone',
      fill: 'saprolite',
    },
    {
      top: 24,
      base: 41,
      name: 'Fractured granite',
      note: 'target aquifer',
      fill: 'fractured',
      aquifer: true,
    },
    { top: 41, base: null, name: 'Fresh granite', fill: 'fresh' },
  ],

  waterStrikes: [26.5, 33.0, 38.5],

  construction: {
    boreDiameter: 165,
    casingDiameter: 125,
    casingMaterial: 'uPVC',
    screenTop: 28,
    screenBase: 40,
    sanitarySealBase: 6,
    totalDepth: 45,
    // 6 rows of 1.0 mm x 50 mm slots at 16 mm vertical pitch -> 4.8 % open area.
    screen: { slotWidth: 1.0, slotLength: 50, rows: 6, pitch: 16 },
  },

  hydraulics: {
    restLevel: 8.2,
    pumpingLevel: 14.3,
    testRate: 1.03,
    testDuration: 360,
    drawdownPerLogCycle: 1.36,
    safetyFactor: 0.7,
  },

  field: {
    sandContent: 2,
    sandContentLimit: 5,
    verticality: 0.4,
    verticalityLimit: 1.0,
  },
};
