(function () {
  'use strict';
  var ed = document.getElementById('ed'), media = matchMedia('(max-width:900px)');
  var textures = document.getElementById('edLeft'), tools = document.getElementById('edRight');
  var search = ed.querySelector('.edsr'), moved = [];
  [search, document.getElementById('edL'), document.getElementById('edR'), document.getElementById('canvasHelp')].forEach(function (element) {
    var marker = document.createComment('Desktop editor position');
    element.before(marker); moved.push({element:element, marker:marker});
  });
  function closePanels() {
    var active = document.activeElement, returnTo = active && active.closest('#edLeft') ? 'edL' :
      active && active.closest('#edRight') ? 'edR' : active && active.closest('#edFrames') ? 'mobileFrames' : null;
    if (ed.classList.contains('frames-open')) document.getElementById('edFramesClose').click();
    ed.classList.remove('l-open', 'r-open'); sync();
    if (media.matches && returnTo) document.getElementById(returnTo).focus({preventScroll:true});
  }
  function sync() {
    var mobile = media.matches, visible = ed.classList.contains('show');
    var left = mobile && visible && ed.classList.contains('l-open');
    var right = mobile && visible && ed.classList.contains('r-open');
    var frames = mobile && visible && ed.classList.contains('frames-open');
    var color = ed.dataset.toolSection === 'color';
    document.querySelector('.editor-panel-backdrop').hidden = !(left || right || frames);
    [[textures,left], [tools,right], [document.getElementById('edFrames'),frames]].forEach(function (item) {
      item[0].inert = mobile && !item[1];
      if (mobile) item[0].setAttribute('aria-hidden', String(!item[1]));
      else item[0].removeAttribute('aria-hidden');
    });
    document.getElementById('edL').setAttribute('aria-expanded', String(left));
    document.getElementById('edR').setAttribute('aria-expanded', String(right && !color));
    document.getElementById('mobileColor').setAttribute('aria-expanded', String(right && color));
    document.getElementById('mobileFrames').setAttribute('aria-expanded', String(frames));
    var preview = document.getElementById('edPv').classList.contains('on');
    document.getElementById('mobilePreview').setAttribute('aria-pressed', String(preview));
    document.getElementById('mobilePreview').querySelector('span').textContent = preview ? 'Canvas' : 'Preview';
    var unavailable = tools.classList.contains('off');
    document.getElementById('mobileColor').disabled = unavailable;
    document.getElementById('mobileFrames').disabled = unavailable ||
      (document.getElementById('canvasAnimate').hidden && document.getElementById('edFramesToggle').hidden);
    document.getElementById('mobileColorSwatch').style.backgroundColor = document.querySelector('#edCol > span').style.backgroundColor;
  }
  function layout() {
    if (media.matches) {
      textures.querySelector('.mobile-panel-header').after(search);
      document.getElementById('mobileTexturesSlot').appendChild(moved[1].element);
      document.getElementById('mobileToolsSlot').appendChild(moved[2].element);
      ed.querySelector('.canvas-controls').appendChild(moved[3].element);
    } else {
      moved.forEach(function (item) { item.marker.after(item.element); });
      closePanels();
    }
    sync();
    if (window.Ed) window.Ed.refreshLayout(true);
  }
  ed.addEventListener('click', function (event) {
    if (event.target.closest('[data-editor-dismiss]')) { closePanels(); return; }
    if (event.target.closest('#mobileColor')) {
      var already = ed.classList.contains('r-open') && ed.dataset.toolSection === 'color';
      closePanels(); ed.dataset.toolSection = 'color';
      ed.classList.toggle('r-open', !already); sync();
      if (!already) tools.scrollTop = document.getElementById('editorColors').offsetTop - tools.querySelector('.mobile-panel-header').offsetHeight;
    }
    if (event.target.closest('#mobileFrames')) {
      var toggle = document.getElementById('edFramesToggle');
      if (!toggle.hidden) toggle.click();
      else if (!document.getElementById('canvasAnimate').hidden) document.getElementById('canvasAnimate').click();
    }
    if (event.target.closest('#edR') && ed.classList.contains('r-open')) tools.scrollTop = 0;
  });
  new MutationObserver(sync).observe(ed, {attributes:true, attributeFilter:['class']});
  media.addEventListener('change', layout);
  window.MobileEditor = {sync:sync};
  layout();
})();
