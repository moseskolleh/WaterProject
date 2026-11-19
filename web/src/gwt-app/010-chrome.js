
  /* ------------------------------------------------------------------ chrome */

  function siteLabel() {
    var site = store.get('site');
    return site.community || site.project || site.client || 'Untitled project';
  }

  function renderChrome() {
    var site = store.get('site');
    var chip = $('#site-chip');
    S.clear(chip);
    var meta = [site.district, site.client].filter(Boolean).join(' · ');
    S.append(chip, [
      el('span.site-chip-name', siteLabel()),
      el('span.site-chip-meta', meta ||
        'Load a sample or upload a field sheet to begin'),
    ]);

    /* The buttons are drawn again, and the keyboard on one of them (the
     * theme button, pressed with Enter) would be left on nothing: it is put
     * back on the button in the same place. */
    var actions = $('#top-actions');
    var held = Array.prototype.indexOf.call(actions.children, document.activeElement);
    S.clear(actions);
    var theme = button(themeIcon(), toggleTheme, { variant: 'ghost', title: 'Switch theme' });
    theme.classList.add('btn-icon');
    /* the moon, sun or half circle is not a name a screen reader can say */
    theme.setAttribute('aria-label', 'Switch theme, now ' + themeName());
    /* On a phone the bar is one row, and the two buttons are their verbs:
     * the word "project" is still in each, for a screen reader and for
     * anything that reads the button's text, and the stylesheet takes it
     * off the screen where there is no room for it. */
    S.append(actions, [
      button(['Save', el('span.btn-more', ' project')], saveProject, { variant: 'ghost',
        title: 'Download the whole working session as a .gwt file' }),
      button(['Open', el('span.btn-more', ' project')], openProject, { variant: 'ghost' }),
      theme,
    ]);
    if (held >= 0 && actions.children[held]) actions.children[held].focus();
    renderNav();
  }

  /* The theme is the device's own until the user chooses one: 'auto' leaves
   * the choice to the stylesheet's prefers-color-scheme rule. */
  function themeChoice() {
    var theme = store.get('theme', 'auto');
    return theme === 'dark' || theme === 'light' ? theme : 'auto';
  }

  function themeIcon() {
    var theme = themeChoice();
    return theme === 'dark' ? '☾' : (theme === 'light' ? '☀' : '◐');
  }

  function themeName() {
    var theme = themeChoice();
    return theme === 'auto' ? 'as the device is set' : theme;
  }

  function toggleTheme() {
    var order = ['auto', 'light', 'dark'];
    var next = order[(order.indexOf(themeChoice()) + 1) % order.length];
    store.set('theme', next);
    applyTheme();
    renderChrome();
    render();
  }

  /* The colour a phone paints its own bars with (index.html's two
   * theme-color lines, one for each setting of the device) follows a theme
   * chosen here, and goes back to the device's when the choice is auto. */
  var THEME_COLOURS = { light: '#f6f7f5', dark: '#0d0f0e' };

  function applyTheme() {
    var theme = themeChoice();
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
    Array.prototype.forEach.call(document.querySelectorAll('meta[name="theme-color"]'),
      function (meta) {
        var own = meta.getAttribute('data-scheme');
        if (own) meta.setAttribute('content', THEME_COLOURS[theme === 'auto' ? own : theme]);
      });
  }

  /* What is done shows in the navigation, as a tick in place of the step's
   * number, so the next thing to do is visible from anywhere in the
   * workspace. */
  function pageDone(key) {
    switch (key) {
      case 'site': return !!store.get('site.community');
      case 'ves': return !!(derived.interpretations && derived.interpretations.length);
      case 'design': return !!derived.design;
      case 'pumping': return !!derived.analysis;
      case 'quality': return !!derived.assessment;
      case 'costing': return !!derived.estimate;
      case 'supervision': return Object.keys(store.get('supervision.responses') || {}).length > 0;
      case 'handover': return !!(derived.design && derived.analysis);
      default: return false;
    }
  }

  /* Drawn again with every page, so that its ticks and its current page
   * are right; the keyboard on one of its items is put back on the same
   * item, where it used to be dropped on the page body mid-Tab.
   *
   * Every page is a button, in the order the groups list them, and a
   * button's text is its page's name and nothing else. A step of the
   * Borehole group also carries its number, or a tick once it is done:
   * both are drawn by the stylesheet in an empty element hidden from a
   * screen reader, which is told the same thing in words beside the button
   * ("Step 4 of 9, done"), as the button's description. */
  function renderNav() {
    var nav = $('#app-nav');
    var held = nav.contains(document.activeElement)
      ? document.activeElement.getAttribute('data-page') : null;
    S.clear(nav);
    /* the brand, which on a narrow screen is at the head of the drawer
     * rather than above the page */
    var brand = $('.app > .app-brand');
    if (brand) S.append(nav, brand.cloneNode(true));
    var current = store.get('nav');
    NAV_GROUPS.forEach(function (group, g) {
      var steps = group[0] === NAV_STEPS;
      var titleId = 'nav-group-' + g;
      var items = group[1].map(function (page, i) {
        var key = page[0], done = pageDone(key);
        var stateId = 'nav-state-' + key;
        return el('li', [
          el('button.nav-item' + (key === current ? '.active' : '') +
            (done ? '.done' : ''), {
            type: 'button',
            onclick: function () { goto(key); },
            'aria-current': key === current ? 'page' : null,
            'aria-describedby': steps ? stateId : null,
            dataset: { page: key },
          }, [
            steps ? el('span.nav-step', { 'aria-hidden': 'true' }) : null,
            el('span.nav-label', page[1]),
          ]),
          steps ? el('span.sr-only', { id: stateId }, 'Step ' + (i + 1) + ' of ' +
            group[1].length + (done ? ', done' : '')) : null,
        ]);
      });
      S.append(nav, el('div.nav-group' + (steps ? '.nav-group-primary' : ''), {
        role: 'group', 'aria-labelledby': titleId,
      }, [
        el('div.nav-group-title', { id: titleId }, group[0]),
        el((steps ? 'ol' : 'ul') + '.nav-list', items),
      ]));
    });
    var again = held && nav.querySelector('.nav-item[data-page="' + held + '"]');
    if (again) again.focus();
  }

  /* The navigation is a drawer on a narrow screen, behind the toggle in the
   * top bar, with a scrim over the page beside it. The toggle says whether it
   * is open (aria-expanded); opening it puts the keyboard on the page it
   * shows, and Escape, a tap on the scrim, or the keyboard leaving it for the
   * page it covers, closes it. `refocus` sends the
   * keyboard back to the toggle as it closes. */
  function setNavOpen(open, refocus) {
    var nav = $('#app-nav'), toggle = $('#nav-toggle');
    nav.classList.toggle('open', open);
    var scrim = $('#nav-scrim');
    if (scrim) scrim.classList.toggle('open', open);
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) {
      var here = nav.querySelector('.nav-item[aria-current="page"]') ||
        nav.querySelector('.nav-item');
      if (here) here.focus();
    } else if (refocus) {
      toggle.focus();
    }
  }

  function watchNavToggle() {
    var nav = $('#app-nav'), toggle = $('#nav-toggle');
    toggle.addEventListener('click', function () {
      setNavOpen(!nav.classList.contains('open'));
    });
    /* the scrim is the page behind the drawer: a tap on it shuts the drawer */
    var scrim = $('#nav-scrim');
    if (scrim) scrim.addEventListener('click', function () { setNavOpen(false, true); });
    /* an Escape a dialog has already answered is not this one's */
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && !e.defaultPrevented && nav.classList.contains('open')) {
        setNavOpen(false, true);
      }
    });
    nav.addEventListener('focusout', function (e) {
      var to = /** @type {Node | null} */ (e.relatedTarget);
      if (nav.classList.contains('open') && to && !nav.contains(to) && to !== toggle) {
        setNavOpen(false);
      }
    });
    /* The skip link names #main, which the router reads as an address it
     * does not know and answers with the Overview: from any other page it
     * went there. It moves the keyboard to the page, and leaves the address
     * as it is. */
    var skip = $('.skip-link');
    if (skip) {
      skip.addEventListener('click', function (e) {
        e.preventDefault();
        $('#main').focus();
      });
    }
  }
