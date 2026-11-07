(function () {
  'use strict';
  var preference = matchMedia('(prefers-reduced-motion: reduce)'), running = new Set(), current = new WeakMap(), panels = new Map();
  function reduced() { return preference.matches || document.body && document.body.classList.contains('calm'); }
  function animate(element, frames, options) {
    if (!element || !element.animate || reduced()) return;
    var previous = current.get(element); if (previous) previous.cancel();
    var animation = element.animate(frames, Object.assign({duration: 260, easing: 'cubic-bezier(.2,.8,.2,1)'}, options));
    current.set(element, animation);
    running.add(animation);
    function done() { running.delete(animation); if (current.get(element) === animation) current.delete(element); }
    animation.finished.then(done, done);
    return animation;
  }
  function reveal(container) {
    if (!container || reduced()) return;
    Array.from(container.children).filter(function (child) { return child.getClientRects().length; }).slice(0, 6).forEach(function (child, i) {
      child.getAnimations().forEach(function (a) { if (running.has(a)) a.cancel(); });
      animate(child, [{opacity: 0, transform: 'translateY(6px)'}, {opacity: 1, transform: 'translateY(0)'}], {delay: i * 12, fill: 'backwards', duration: 280});
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
    animate(host, [{opacity: 0}, {opacity: 1}], {duration: 160});
    animate(host.querySelector('.edt'), [{opacity: 0, transform: 'translateY(-4px)'}, {opacity: 1, transform: 'translateY(0)'}], {duration: 240});
    animate(host.querySelector('.edc'), [{opacity: .6}, {opacity: 1}], {duration: 220});
  }
  function panel(element, visible) {
    if (!element) return;
    var old = panels.get(element);
    if (old && old.visible === visible && (old.animation || element.hidden === !visible)) return;
    var wasHidden = element.hidden, style = !wasHidden && getComputedStyle(element);
    var from = wasHidden ? {opacity: 0, transform: 'translateX(16px)'} : {opacity: style.opacity, transform: style.transform};
    if (old && old.animation) old.animation.cancel();
    var state = {visible: visible, animation: null}; panels.set(element, state);
    element.inert = !visible; element.setAttribute('aria-hidden', String(!visible));
    if (reduced() || !element.animate || wasHidden && !visible) { element.hidden = !visible; return; }
    element.hidden = false;
    var animation = animate(element, [from, {opacity: visible ? 1 : 0, transform: visible ? 'none' : 'translateX(12px)'}], {duration: visible ? 280 : 180});
    state.animation = animation;
    function finish() { if (panels.get(element) !== state) return; element.hidden = !state.visible; state.animation = null; }
    animation.finished.then(finish, finish);
  }
  function capture(elements) {
    var boxes = new Map(); if (reduced()) return boxes;
    Array.from(elements).forEach(function (element) { if (element.dataset.motionKey && element.getClientRects().length) boxes.set(element.dataset.motionKey, element.getBoundingClientRect()); });
    return boxes;
  }
  function reorder(boxes, elements) {
    if (!boxes || !boxes.size || reduced()) return;
    Array.from(elements).forEach(function (element) {
      var old = boxes.get(element.dataset.motionKey); if (!old) return;
      var box = element.getBoundingClientRect(), x = old.left - box.left, y = old.top - box.top;
      if (Math.abs(x) + Math.abs(y) < 1) return;
      animate(element, [{transform: 'translate3d(' + x + 'px,' + y + 'px,0)'}, {transform: 'translate3d(0,0,0)'}], {duration: 280});
    });
  }
  function sync() {
    if (!reduced()) return;
    running.forEach(function (animation) { animation.cancel(); });
    panels.forEach(function (state, element) { element.hidden = !state.visible; state.animation = null; });
  }
  window.addEventListener('resize', nav, {passive: true});
  preference.addEventListener('change', function () {
    sync();
    if (window.bench) window.bench.setReduced(reduced());
  });
  window.Motion = {reduced: reduced, sync: sync, reveal: reveal, nav: nav, editor: editor, panel: panel, capture: capture, reorder: reorder,
    surface: function (element) { animate(element, [{opacity: 0, transform: 'translateY(6px)'}, {opacity: 1, transform: 'translateY(0)'}], {duration: 220}); }};
})();
