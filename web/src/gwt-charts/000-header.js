/* gwt-charts.js - every figure the toolkit draws, as inline SVG.
 *
 * No plotting library: the figures are small, specific and need to match the
 * matplotlib originals that go into the .docx reports, so they are drawn
 * directly. Each function returns an <svg> element that can be shown on the
 * page and rasterised to PNG for a report by toPng().
 *
 * Colour is taken from the stylesheet's tokens at draw time and written into
 * the SVG as literal values, so a figure exports correctly and a theme change
 * simply redraws. Field data is always the blue and a fitted model always the
 * orange, and the two are additionally separated by mark type, so the pair
 * never depends on hue alone.
 */
(function (global) {
  'use strict';

  /** @type {GWTNamespace} */
  var GWT = global.GWT || (global.GWT = {});
  var S = GWT.support;
  var C = GWT.core;
  var svgEl = S.svgEl, el = S.el;

  var NS = 'http://www.w3.org/2000/svg';
