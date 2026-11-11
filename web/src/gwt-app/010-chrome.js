
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
    /* the moon, sun or half circle is not a name a screen reader can say */
    theme.setAttribute('aria-label', 'Switch theme, now ' + themeName());
    S.append(actions, [
      button('Save project', saveProject, { variant: 'ghost',
        title: 'Download the whole working session as a .gwt file' }),
      button('Open project', openProject, { variant: 'ghost' }),
      theme,
    ]);
    if (held >= 0 && actions.children[held]) actions.children[held].focus();
    renderNav();
  }

  function themeIcon() {
    var theme = store.get('theme', 'dark');
    return theme === 'dark' ? '☾' : (theme === 'light' ? '☀' : '◐');
  }

  function themeName() {
    var theme = store.get('theme', 'dark');
    return theme === 'dark' ? 'dark' : (theme === 'light' ? 'light' : 'as the device is set');
  }

  function toggleTheme() {
    var order = ['auto', 'light', 'dark'];
    var next = order[(order.indexOf(store.get('theme', 'dark')) + 1) % order.length];
    store.set('theme', next);
    applyTheme();
    renderChrome();
    render();
  }

  function applyTheme() {
    var theme = store.get('theme', 'dark');
    if (theme === 'auto') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
  }

  /* A dot per page shows what is done, so the next thing to do is visible from
   * anywhere in the workspace. */
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

  /* Drawn again with every page, so that its dots and its current page
   * are right; the keyboard on one of its items is put back on the same
   * item, where it used to be dropped on the page body mid-Tab. */
  function renderNav() {
    var nav = $('#app-nav');
    var held = nav.contains(document.activeElement)
      ? document.activeElement.getAttribute('data-page') : null;
    S.clear(nav);
    var current = store.get('nav');
    NAV_GROUPS.forEach(function (group) {
      var items = group[1].map(function (page) {
        var key = page[0];
        return el('button.nav-item' + (key === current ? '.active' : '') +
          (pageDone(key) ? '.done' : ''), {
          type: 'button',
          onclick: function () { goto(key); },
          'aria-current': key === current ? 'page' : null,
          dataset: { page: key },
        }, [el('span.nav-dot'), el('span', page[1])]);
      });
      S.append(nav, el('div.nav-group', [
        group[0] ? el('div.nav-group-title', group[0]) : null,
        el('div', items),
      ]));
    });
    var again = held && nav.querySelector('.nav-item[data-page="' + held + '"]');
    if (again) again.focus();
  }

  /* The navigation is a drawer on a narrow screen, behind the toggle in the
   * top bar. The toggle says whether it is open (aria-expanded); opening it
   * puts the keyboard on the page it shows, and Escape, or the keyboard
   * leaving it for the page it covers, closes it. `refocus` sends the
   * keyboard back to the toggle as it closes. */
  function setNavOpen(open, refocus) {
    var nav = $('#app-nav'), toggle = $('#nav-toggle');
    nav.classList.toggle('open', open);
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
