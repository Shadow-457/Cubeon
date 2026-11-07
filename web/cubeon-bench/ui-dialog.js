(function () {
  'use strict';
  var host, finish, previous;
  function close(value) {
    if (!host || !host.open) return;
    host.close();
    var resolve = finish; finish = null;
    if (previous && previous.isConnected) previous.focus({preventScroll: true});
    if (resolve) resolve(value);
  }
  function open(options) {
    if (!host) {
      host = document.createElement('dialog'); host.id = 'appDialog'; host.className = 'app-dialog';
      host.setAttribute('aria-labelledby', 'appDialogTitle'); document.body.appendChild(host);
      host.addEventListener('cancel', function (event) { event.preventDefault(); close(null); });
      host.addEventListener('click', function (event) { if (event.target === host) close(null); });
    }
    if (host.open) close(null);
    previous = document.activeElement;
    host.innerHTML = '<div class="dialog-body"><h2 id="appDialogTitle"></h2><div id="appDialogContent"></div><div class="dialog-actions"><button type="button" class="gb" id="appDialogCancel">Cancel</button><button type="button" class="gb primary-action" id="appDialogAccept">Continue</button></div></div>';
    host.querySelector('h2').textContent = options.title;
    host.querySelector('#appDialogContent').innerHTML = options.html || '';
    var cancel = host.querySelector('#appDialogCancel'), accept = host.querySelector('#appDialogAccept');
    cancel.textContent = options.cancel || 'Cancel'; accept.textContent = options.accept || 'Continue';
    cancel.hidden = !!options.noCancel;
    accept.classList.toggle('danger-action', !!options.danger);
    cancel.onclick = function () { close(null); };
    accept.onclick = function () { close(options.read ? options.read(host) : true); };
    return new Promise(function (resolve) { finish = resolve; host.showModal(); accept.focus(); window.Motion.surface(host); });
  }
  window.AppDialog = {open: open, close: close};
})();
