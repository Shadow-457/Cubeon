(function () {
  'use strict';
  var surface = document.currentScript.dataset.benchSurface;
  try {
    if (surface === 'workspace') {
      localStorage.setItem('cb-bench-entered', '1');
      return;
    }
    if (/\/landing(?:\.html)?\/?$/.test(location.pathname) || location.hash) return;
    var previous = null;
    try { previous = JSON.parse(localStorage.getItem('cb-data') || 'null'); } catch (_) {}
    if (localStorage.getItem('cb-bench-entered') === '1' ||
        previous && (Array.isArray(previous.projects) || previous.onboarded)) {
      location.replace(new URL('workspace.html', document.baseURI).href);
    }
  } catch (_) {}
})();
