(function () {
  'use strict';
  // Temporarily hide depth access; keep the implementation and saved maps.
  window.BenchFeatures = {depth: false};
  document.documentElement.classList.toggle('bench-depth-disabled', !window.BenchFeatures.depth);
})();
