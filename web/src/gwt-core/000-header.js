// @ts-check
/* gwt-core.js - the groundwater science engine, in the browser.
 *
 * A direct port of the `groundwater` Python package: the same formulas, the
 * same thresholds, the same deliberate field-data behaviours. Nothing here
 * touches the DOM, so it can be unit-tested headlessly and gwt-worker.js can
 * load it, with the tables in gwt-data.js, into a Web Worker.
 *
 * What runs where. In the worker: invertSounding, one sounding per request;
 * analysePumpingTest; and what recompute derives from the sheets once they
 * are read - readVesSheets, drillingFromGrid, pumpingFromGrid,
 * qualityFromGrid and assessSample. On the page: reading a workbook or a Word
 * sheet (readPumpingDocx), because both need DOMParser, which a worker does
 * not have; interpretModel and rankInterpretations on each inverted model;
 * and everything else - the design, the costing, the maps, the report
 * sentences. Opened from file://, where a browser will not start a worker,
 * or wherever the worker fails to start, the worker's share runs on the page
 * too, through the same functions and the same calls.
 *
 * Units, held to throughout:
 *   depth, thickness, spacing      m
 *   resistivity                    ohm-m
 *   discharge                      m3/h on the sheet, m3/day inside the fits
 *   transmissivity                 m2/day
 *   time                           minutes on the sheet, days inside the fits
 *   concentrations                 mg/L unless the parameter says otherwise
 */
(function (global) {
  'use strict';

  /** @type {GWTNamespace} */
  var GWT = global.GWT || (global.GWT = {});
  /** @type {Record<string, any>} */
  var C = GWT.core = {};

  /* The types the JSDoc in this file names. web/jscheck checks them, and
   * nothing at run time reads them. Numbers, strings and arrays are typed as
   * what they are. A record - a sounding, a model, a test, a project - is
   * typed as an open record: the engine adds fields to records as it goes,
   * and a type listing every field would be a second copy of the Python
   * dataclasses to keep in step. The name still says which record a
   * function takes, and a null passed where a record is wanted is still
   * caught. */
  /** @typedef {Record<string, any>} Rec  any other record */
  /** @typedef {Record<string, any>} Config  what withConfig returns */
  /** @typedef {Record<string, any>} Sounding  one VES sounding as read */
  /** @typedef {Record<string, any>} LayeredModel  what layeredModel returns */
  /** @typedef {Record<string, any>} Interpretation  what interpretModel returns */
  /** @typedef {Record<string, any>} VesConfig  a Config's ves section */
  /** @typedef {Record<string, any>} PumpingConfig  a Config's pumping section */
  /** @typedef {Record<string, any>} DesignConfig  a Config's design section */
  /** @typedef {Record<string, any>} PumpingTest  one pumping test as read */
  /** @typedef {Record<string, any>} PumpingAnalysis  what analysePumpingTest returns */
  /** @typedef {Record<string, any>} QualitySample  one laboratory sample as read */
  /** @typedef {Record<string, any>} QualityAssessment  what assessSample returns */
  /** @typedef {{minimum: number|null, maximum: number}} Limit  a guideline limit */
  /** @typedef {Record<string, any>} DrillingLog  one drilling log as read */
  /** @typedef {Record<string, any>} Design  what designBorehole returns */
  /** @typedef {Array<Array<*>>} Grid  a sheet's cells, row by row: numbers, strings, Dates and nulls */
  /** @typedef {Record<string, any>} Polygon  one chiefdom of loadPolygons */
  /** @typedef {Record<string, any>} WaterPoint  one water point of parseWpdxRecords */
  /** @typedef {Record<string, any>} MapPoint  one point on a survey-scale map */
  /** @typedef {{nx: number, ny: number, x: number[], y: number[], z: Array<number|null>|null}} SurfaceGrid */

  /* Own-key lookup. Several tables here are indexed with free text off a
   * field sheet, and a plain `map[key]` finds Object.prototype: a borehole
   * status of "constructor" returned a function where a status class was
   * expected. Python's dicts have no such inherited keys, so this is also
   * what keeps the two engines agreeing. */
  function own(map, key) {
    return Object.prototype.hasOwnProperty.call(map, key);
  }
