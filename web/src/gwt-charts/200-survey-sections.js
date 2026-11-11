
  /* =================================== survey sections and subsurface maps */

  /* The browser geophysical report drew no figure the survey itself produced:
   * no geoelectric section, no layer pseudo-section and none of the four
   * subsurface maps, while the Python engine drew every one of them
   * (ROADMAP webapp-parity-5). A client reading the browser's report of the
   * same survey got the text of a geophysical investigation with none of its
   * pictures. The geometry, the interpolation and the refusals are mirrored in
   * gwt-core.js; these are the figures drawn from them.
   *
   * Every one of these functions returns null where the engine handed back a
   * reason instead of geometry, and the report layer prints that reason. That
   * is the point of the pairing: a section drawn between two soundings 20 km
   * apart, or a surface interpolated through two points, is worse than no
   * figure at all, because a figure is read as a measurement.
   */

  /* config.py HouseStyle.figure_width_in. The Python figures are 6.3 in wide
   * and maps.py _figsize gives every map its height from the ground it covers,
   * so the browser figure is shaped like the report's rather than being a
   * fixed rectangle the same survey is squashed into. */
  var FIGURE_WIDTH_IN = 6.3;
