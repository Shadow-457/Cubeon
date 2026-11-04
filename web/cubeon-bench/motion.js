(function () {
  'use strict';
  var preference = matchMedia('(prefers-reduced-motion: reduce)'), running = new Set();
  function reduced() { return preference.matches || document.body && document.body.classList.contains('calm'); }
  function animate(element, frames, options) {
    if (!element || !element.animate || reduced()) return;
    var animation = element.animate(frames, Object.assign({duration: 380, easing: 'cubic-bezier(.22,1,.36,1)'}, options));
    running.add(animation);
    animation.finished.then(function () { running.delete(animation); }, function () { running.delete(animation); });
    return animation;
  }
  function reveal(container) {
    if (!container || reduced()) return;
    Array.from(container.children).filter(function (child) { return child.getClientRects().length; }).slice(0, 8).forEach(function (child, i) {
      child.getAnimations().forEach(function (a) { if (running.has(a)) a.cancel(); });
      animate(child, [{opacity: 0, transform: 'translateY(10px)'}, {opacity: 1, transform: 'translateY(0)'}], {delay: i * 35, fill: 'backwards'});
    });
  }
  function nav() {
    var host = document.querySelector('.nv'), active = host && host.querySelector('[aria-current="page"]');
    if (!active || !host.getClientRects().length) return;
    var indicator = host.querySelector('.nav-indicator');
    if (!indicator) {
      indicator = document.createElement('span'); indicator.className = 'nav-indicator'; indicator.setAttribute('aria-hidden', 'true'); host.prepend(indicator);
    }
    var origin = host.getBoundingClientRect(), box = active.getBoundingClientRect();
    indicator.style.width = box.width + 'px'; indicator.style.height = box.height + 'px';
    indicator.style.transform = 'translate3d(' + (box.left - origin.left) + 'px,' + (box.top - origin.top) + 'px,0)';
    host.classList.add('has-indicator');
    requestAnimationFrame(function () { indicator.classList.add('ready'); });
  }
  function editor(host) {
    animate(host.querySelector('.edt'), [{opacity: 0, transform: 'translateY(-6px)'}, {opacity: 1, transform: 'translateY(0)'}], {duration: 300});
    animate(host.querySelector('.edc'), [{opacity: .4}, {opacity: 1}], {duration: 340});
  }
  function sync() { if (reduced()) running.forEach(function (animation) { animation.cancel(); }); }
  window.addEventListener('resize', nav, {passive: true});
  preference.addEventListener('change', function () {
    sync();
    if (window.bench) window.bench.setReduced(reduced());
  });
  window.Motion = {reduced: reduced, sync: sync, reveal: reveal, nav: nav, editor: editor,
    surface: function (element) { animate(element, [{opacity: 0, transform: 'translateY(8px)'}, {opacity: 1, transform: 'translateY(0)'}], {duration: 240}); }};
})();
