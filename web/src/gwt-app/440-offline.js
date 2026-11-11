
  /* ----------------------------------------------------------- offline / PWA */

  /* Whether the browser has been asked to keep the app on disk. The toolkit is
   * used where the network is a luxury, so this is not a nicety: once the
   * worker is installed the app opens on a drilling site with no signal at
   * all. Registration is best-effort - file:// pages, private windows and
   * browsers without service worker support all fall through silently, and
   * the app works exactly as before in every one of them. */
  function registerServiceWorker() {
    if (!('serviceWorker' in navigator)) return;
    if (location.protocol !== 'https:' && location.hostname !== 'localhost'
      && location.hostname !== '127.0.0.1') return;
    navigator.serviceWorker.register('sw.js').then(function (reg) {
      /* Once it controls the page the app is on disk; say so where the user
       * is deciding whether to trust it in the field. */
      navigator.serviceWorker.ready.then(refreshInstallCard);
      reg.addEventListener('updatefound', function () {
        var incoming = reg.installing;
        if (!incoming) return;
        incoming.addEventListener('statechange', function () {
          /* "installed" with a controller already present means this is an
           * update, not a first install - say so rather than reloading, which
           * would throw away anything typed and not yet recomputed. */
          if (incoming.state === 'installed' && navigator.serviceWorker.controller) {
            S.toast('A newer version has been downloaded. It will be used the ' +
              'next time you open the app.', 'ok', 9000);
          }
        });
      });
    }).catch(function (e) {
      console.warn('Offline support unavailable:', e && e.message);
    });
  }

  /* Chromium hands over its install prompt exactly once and only if the page
   * refuses the default one, so it is stashed here and spent from the
   * Overview page's button. */
  var installPrompt = null;

  /* The card lives on the Overview page, and these events arrive whenever the
   * browser feels like it - including while a form is being filled in
   * elsewhere. Redraw only the page that shows the card, so nothing a user
   * has half-typed is thrown away to announce something they can see later. */
  function refreshInstallCard() {
    if (store.get('nav', 'overview') === 'overview') render();
  }

  function watchInstallPrompt() {
    global.addEventListener('beforeinstallprompt', function (event) {
      event.preventDefault();
      installPrompt = event;
      refreshInstallCard();
    });
    global.addEventListener('appinstalled', function () {
      installPrompt = null;
      S.toast('Installed. The toolkit now opens without a network.', 'ok');
      refreshInstallCard();
    });
  }

  function offlineReady() {
    return typeof navigator !== 'undefined' && 'serviceWorker' in navigator
      && !!navigator.serviceWorker.controller;
  }

  function installCard() {
    var ready = offlineReady();
    if (!installPrompt && !ready) return null;
    return card('Field use without a network', [
      ready ? el('div.callout.callout-ok', [
        el('p', el('strong', 'This app is saved on the device')),
        el('p', 'It will open and work with no network at all. Sample ' +
          'projects, the standards tables and every calculation are already ' +
          'here; only the live water point lookup needs a connection.'),
      ]) : null,
      installPrompt ? el('p', 'Install the toolkit on this device and it opens ' +
        'like any other application — full screen, no address bar. Everything ' +
        'still runs on the device; nothing is uploaded.') : null,
      installPrompt ? button('Install', function () {
        var prompt = installPrompt;
        installPrompt = null;
        prompt.prompt();
        prompt.userChoice.then(function (choice) {
          if (choice && choice.outcome !== 'accepted') refreshInstallCard();
        });
      }) : null,
    ].filter(Boolean));
  }
