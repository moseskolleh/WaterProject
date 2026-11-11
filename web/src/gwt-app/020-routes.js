
  /* ------------------------------------------------------------------ routes */

  /* Every page has an address, #/<page>, and a page that shows several
   * things of one kind gives each an address of its own, #/<page>/<item>: a
   * sounding on the Geophysics page (#/ves/VES-3), the borehole a pumping
   * test was run on (#/pumping/KTL-01). The address is what the back and
   * forward buttons move between, what the user guide links to, and what a
   * QR code on a field sheet can carry. The store's nav is still what a page
   * is drawn from; the address follows it, and it follows the address. */
  var route = { item: '', focused: true };

  function hashFor(key, item) {
    return '#/' + key + (item ? '/' + encodeURIComponent(item) : '');
  }

  /* The page and item an address names. An address that names no page -
   * mistyped, or from a release with a page this one lacks - is the Overview,
   * and says so with `unknown`, so the address bar can be put right. */
  function routeFrom(hash) {
    var text = String(hash || '').replace(/^#\/?/, '');
    if (!text) return { key: '', item: '' };
    var parts = text.split('/');
    var key, item;
    try {
      key = decodeURIComponent(parts[0]);
      item = decodeURIComponent(parts.slice(1).join('/')).trim();
    } catch (e) { key = ''; }
    if (!key || !Object.prototype.hasOwnProperty.call(PAGES, key)) {
      return { key: 'overview', item: '', unknown: true };
    }
    return { key: key, item: item };
  }

  /* Whether the device has been asked for less motion: nothing scrolls
   * smoothly then, here or in the stylesheet. */
  function lessMotion() {
    return !!(global.matchMedia &&
      global.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  /* Draw a page, as goto and the address both ask for it. */
  function show(key, item) {
    store.set('nav', key);
    route.item = item || '';
    route.focused = !route.item;
    var drawn = render();
    setNavOpen(false);
    $('#main').focus({ preventScroll: true });
    if (!route.item) {
      /* the main pane is the scroll container on a wide screen and the page
       * is on a narrow one, so both are sent back to the top */
      var how = /** @type {ScrollBehavior} */ (lessMotion() ? 'auto' : 'smooth');
      $('#main').scrollTo({ top: 0, behavior: how });
      global.scrollTo({ top: 0, behavior: how });
    }
    return drawn;
  }

  /* Go to a page, and to one item on it if an item is named. The address
   * changes with it, which adds a step to the browser's history. The promise
   * is the page drawn, with whatever it had to fetch first. */
  function goto(key, item) {
    if (!Object.prototype.hasOwnProperty.call(PAGES, key)) key = 'overview';
    var address = hashFor(key, item);
    if (global.location && global.location.hash !== address) {
      /* the hashchange this fires finds the page already showing */
      global.location.hash = address;
    }
    return show(key, item);
  }

  /* The address changed under the app: back, forward, a link, or a hand in
   * the address bar. */
  function followAddress() {
    var wanted = routeFrom(global.location.hash);
    if (!wanted.key) wanted = { key: 'overview', item: '' };
    if (wanted.unknown) {
      /* replaced rather than added, so back does not return to it */
      global.location.replace(hashFor('overview'));
    }
    if (wanted.key === store.get('nav') && wanted.item === route.item) return;
    show(wanted.key, wanted.item);
  }

  /* Mark a node as the item an address can name on this page. */
  function itemNode(id, node) {
    if (id && node && node.setAttribute) node.setAttribute('data-item', String(id));
    return node;
  }

  function sameItem(a, b) {
    return String(a).trim().toLowerCase() === String(b).trim().toLowerCase();
  }

  /* After a page is drawn: bring the item its address names into view, once
   * per visit, or say on the page that it is not there. A link printed for
   * one borehole and opened on a project holding another must not look as
   * though it had worked. */
  function showItem(host) {
    if (!route.item) return;
    var found = Array.prototype.find.call(host.querySelectorAll('[data-item]'),
      function (node) { return sameItem(node.getAttribute('data-item'), route.item); });
    if (found) {
      found.classList.add('item-target');
      if (!route.focused) {
        route.focused = true;
        found.scrollIntoView({ block: 'start' });
      }
      return;
    }
    /* not yet: the sheets are still being read or the soundings inverted,
     * and the item may be among what they bring */
    if (recomputeState.running || Object.keys(work).length) return;
    var named = Array.prototype.map.call(host.querySelectorAll('[data-item]'),
      function (node) { return node.getAttribute('data-item'); });
    var head = host.querySelector('.page-head');
    var note = el('div.callout.callout-warn.item-missing', [
      el('p', el('strong', 'Nothing here is called ' + route.item)),
      el('p', 'This address points at ' + route.item + ', which is not in the ' +
        'project open in this browser' + (named.length ? ' (it holds ' +
        S.joinList(named) + ')' : '') + '. Open the project it belongs to, or ' +
        'load its field sheet.'),
    ]);
    if (head && head.nextSibling) host.insertBefore(note, head.nextSibling);
    else host.insertBefore(note, host.firstChild);
  }

  function nextStep(note, label, page) {
    return el('div.next-step', [
      el('p.next-note', note),
      button(label + ' →', function () { goto(page); }),
    ]);
  }

  function pageHead(title, lead, crumb) {
    return el('div.page-head', [
      crumb ? el('div.crumb', crumb) : null,
      el('h1', title),
      lead ? el('p.lead', lead) : null,
    ]);
  }

  /* Shown wherever a national verdict is put in front of the user, for as long
   * as any national value in the standards table is still unconfirmed. Failing
   * an unconfirmed limit is a prompt to check the specification, not a
   * compliance finding - and the difference matters to whoever signs. */
  function provisionalStandardsNote() {
    var params = C.provisionalNationalParameters();
    if (!params.length) return null;
    return el('div.callout.callout-warn', [
      el('p', el('strong', 'National limits are provisional')),
      el('p', C.PROVISIONAL_NATIONAL_NOTE),
      el('p.muted', 'Unconfirmed: ' + params.join(', ') + '.'),
    ]);
  }
