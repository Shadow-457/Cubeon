(function () {
  'use strict';
  var CB = window.CB, registration, installPrompt, offlineReady = false;
  var $ = function (selector) { return document.querySelector(selector); };
  var development=['localhost','127.0.0.1','[::1]'].includes(location.hostname),startedWithController=!!navigator.serviceWorker&&!!navigator.serviceWorker.controller,reloading=false;
  if(development&&'serviceWorker' in navigator)navigator.serviceWorker.addEventListener('controllerchange',async function(){if(!startedWithController||reloading)return;reloading=true;if(window.Ed)window.Ed.prepareExport();if(await LocalStore.flush())location.reload();else{reloading=false;CB.toast('App updated. Back up unsaved work before reloading.');}});
  function connection() {
    var badge = $('#connectionBadge');
    badge.textContent = !navigator.onLine ? 'Offline' : offlineReady ? 'Offline ready' : 'Online';
    badge.dataset.ready = String(offlineReady); badge.title = !navigator.onLine ? 'Working offline · projects save on this device' : offlineReady ? 'This app and all bundled textures are available offline' : 'Set up offline access in Settings';
  }
  function status(text, error) { $('#offlineStatus').textContent = text; $('#offlineStatus').classList.toggle('offline-error', !!error); }
  function installed() { return matchMedia('(display-mode: standalone)').matches || navigator.standalone; }
  function installState() {
    $('#installApp').hidden = installed();
    $('#installApp').textContent = installPrompt ? 'Install Cubeon Bench' : 'How to install';
  }
  async function prepareOffline() {
    if (location.protocol === 'file:') { offlineReady = true; status('File mode works offline with the bundled textures. For app installation, serve this folder over localhost or HTTPS.'); connection(); return; }
    if (!('serviceWorker' in navigator) || !window.isSecureContext) { status('Offline installation needs HTTPS or localhost. Editing and local saves work here.', true); return; }
    $('#prepareOffline').disabled = true; status('Saving the app and all 3,964 textures for offline use…');
    try {
      registration = await navigator.serviceWorker.register('sw.js', {scope: './', updateViaCache: 'none'});
      await Promise.race([navigator.serviceWorker.ready, new Promise(function (_, reject) { setTimeout(function () { reject(new Error('Offline setup took too long. Check the connection and try again.')); }, 25000); })]);
      offlineReady = true; status('Ready offline. Every bundled texture, the editor, and your local projects work without a connection.'); connection();
      function waiting() { $('#updateApp').hidden = !registration.waiting;$('#updateNotice').hidden=!registration.waiting; }
      waiting(); registration.addEventListener('updatefound', function () { var worker = registration.installing; if (worker) worker.addEventListener('statechange', waiting); });
    } catch (error) { status('Offline setup failed: ' + error.message, true); }
    finally { $('#prepareOffline').disabled = false; }
  }
  window.addEventListener('beforeinstallprompt', function (event) { event.preventDefault(); installPrompt = event; installState(); });
  window.addEventListener('appinstalled', function () { installPrompt = null; installState(); CB.toast('Cubeon Bench installed.'); });
  window.addEventListener('online', connection); window.addEventListener('offline', connection);
  $('#prepareOffline').onclick = prepareOffline;
  $('#connectionBadge').onclick = function () { CB.go('settings');CB.settingsPage('offline'); $('#offlineCard').scrollIntoView({block: 'center'}); };
  $('#installApp').onclick = async function () {
    if (installPrompt) { var prompt = installPrompt; installPrompt = null; await prompt.prompt(); await prompt.userChoice; installState(); }
    else await AppDialog.open({title: 'Install Cubeon Bench', accept: 'Got it', noCancel: true, html: '<p>Open this app over HTTPS or localhost. In Chrome or Edge, choose <b>Install app</b> from the address bar or browser menu. On iPhone or iPad, use Safari’s <b>Share → Add to Home Screen</b>. Other browsers can bookmark the app.</p><p>Keep using the same browser profile and address to access your projects. Use Settings → Backups to move them between devices.</p>'});
  };
  $('#updateApp').onclick = async function () {
    if (!registration || !registration.waiting) return;
    if (window.Ed) window.Ed.prepareExport();
    if (!await LocalStore.flush()) { CB.toast('Save failed. Download a workspace backup before updating.'); return; }
    navigator.serviceWorker.addEventListener('controllerchange', function () { location.reload(); }, {once: true});
    registration.waiting.postMessage({type: 'ACTIVATE_UPDATE'});
  };
  $('#updateNotice').onclick=function(){$('#updateApp').click();};
  var shortcutGroups = [
    ['Workspace', [
      ['Quick actions', 'Ctrl / ⌘ K'], ['Help and shortcuts', 'F1 / ?'],
      ['New project', 'Ctrl / ⌘ Alt N'], ['Import pack or skin', 'Ctrl / ⌘ O'],
      ['Save now', 'Ctrl / ⌘ S'], ['Export project', 'Ctrl / ⌘ Shift E'],
      ['Export texture PNG', 'Ctrl / ⌘ Alt E'], ['Search textures', 'Ctrl / ⌘ F'],
      ['Import image as texture', 'Ctrl / ⌘ Shift I'], ['Paste image from clipboard', 'Ctrl / ⌘ V with an image copied'],
      ['Previous / next texture tab', 'Alt ← / →'], ['Close texture tab', 'Shift W'],
      ['Switch canvas / 3D preview', 'P'], ['Close panel / leave editor', 'Escape']]],
    ['Painting and selection', [
      ['Draw / erase / fill / pick', 'B / E / G / I'], ['Line / rectangle / ellipse', 'L / R / O'],
      ['Select / lighten / darken', 'M / U / D'], ['Open color picker', 'C'],
      ['Pick color temporarily', 'Alt + click'], ['Filled rectangle / ellipse', 'Hold Shift while drawing'],
      ['Smaller / larger brush', '[ / ]'], ['Undo', 'Ctrl / ⌘ Z'],
      ['Redo', 'Ctrl / ⌘ Shift Z / Ctrl Y'], ['Select all pixels', 'Ctrl / ⌘ A'],
      ['Deselect pixels', 'Ctrl / ⌘ Shift A / Escape'], ['Copy / cut / paste pixels', 'Ctrl / ⌘ C / X / V on canvas'],
      ['Clear selected pixels', 'Delete / Backspace on canvas']]],
    ['Canvas navigation', [
      ['Pan temporarily', 'Hold Space + drag'], ['Toggle Hand tool', 'H'],
      ['Zoom in / out', '+ / −'], ['Fit canvas / 100% zoom', 'F / 0'], ['Toggle pixel grid', 'Shift G']]],
    ['Animation frames', [
      ['Copy / cut / paste frame', 'Ctrl / ⌘ C / X / V in frame panel'],
      ['Copy / cut / paste frame from canvas', 'Ctrl / ⌘ Shift C / X / V'],
      ['Duplicate selected frame', 'Ctrl / ⌘ D'], ['Remove selected frame', 'Delete / Backspace in frame panel'],
      ['Previous / next frame', '↑ / ↓ / ← / → in frame list; Page Up / Down on canvas'],
      ['First / last frame', 'Home / End in frame list'], ['Move frame earlier / later', 'Alt ↑ / ↓ in frame panel'],
      ['Play / pause animation', 'Space in frame panel; Shift Space on canvas'],
      ['Create animation / add frame', 'Shift A'], ['Show / hide frames', 'Shift F']]],
    ['3D preview and panels', [
      ['Rotate model', 'Arrow keys in 3D; Shift for larger steps'], ['Zoom model', '+ / − in 3D'],
      ['Reset model view', 'F / 0 in 3D'], ['Toggle auto-rotation', 'Space in 3D'],
      ['Resize focused sidebar divider', '← / →'], ['Focus controls / activate button', 'Tab / Shift Tab; Enter / Space']]]
  ];
  function help() {
    var html = '<p>Choose Draw and a color to paint. Use <b>Create animation</b> to add frames, then Play to preview them.' +
      (window.BenchFeatures.depth ? ' Choose <b>Add depth</b> for easy 3D texture presets and height painting.' : '') + '</p>' +
      '<p class="mu">Click a frame for frame shortcuts, or the canvas for pixel shortcuts. Frame copies include timing. Text fields keep their normal keys.</p>' +
      '<label class="lb" for="shortcutSearch">Find a shortcut</label><input class="command-search" id="shortcutSearch" type="search" placeholder="Try copy, frame, zoom…" autocomplete="off">' +
      '<table class="shortcut-table">' + shortcutGroups.map(function(group) {
        return '<tbody><tr class="shortcut-heading"><th colspan="2">' + group[0] + '</th></tr>' + group[1].map(function(row) {
          return '<tr class="shortcut-row"><td>' + row[0] + '</td><td><kbd>' + row[1] + '</kbd></td></tr>';
        }).join('') + '</tbody>';
      }).join('') + '</table><p class="mu" id="shortcutEmpty" hidden>No matching shortcuts.</p>' +
      '<p style="margin-top:16px">Projects save automatically on this device. Export packs as ZIPs and skins as PNGs. Workspace backups include edits, animations, and imported files. Deleted projects stay in Settings → Trash.</p>';
    var result = AppDialog.open({title:'Help and keyboard shortcuts',accept:'Back to the bench',noCancel:true,html:html});
    $('#shortcutSearch').oninput = function() {
      var query = this.value.trim().toLowerCase(), count = 0;
      document.querySelectorAll('.shortcut-table tbody').forEach(function(group) {
        var visible = 0;
        group.querySelectorAll('.shortcut-row').forEach(function(row) {row.hidden = !row.textContent.toLowerCase().includes(query);if(!row.hidden)visible++;});
        group.hidden = !visible;count += visible;
      });
      $('#shortcutEmpty').hidden = !!count;
    };
    $('#shortcutSearch').focus({preventScroll:true});$('#appDialog').scrollTop=0;
    return result;
  }
  function commands() {
    if (!document.body.classList.contains('inapp') || $('#modal').classList.contains('show')) return;
    var items = [{name: 'New texture pack', run: function () { CB.newProject({type: 'pack'}); }}, {name: 'New skin', run: function () { CB.newProject({type: 'skin'}); }},
      {name: 'Import pack or skin', run: function () { $('#packImport').value = ''; $('#packImport').click(); }},
      {name: 'Export workspace backup', run: function () { Workspace.exportBackup(); }},
      {name: 'Projects', run: function () { if ($('#ed').classList.contains('show')) window.Ed.close(); CB.go('projects'); }},
      {name: 'Cubeon Toolbox', run: function () { if ($('#ed').classList.contains('show')) window.Ed.close(); CB.go('tools'); Toolbox.hub(); }},
      {name: 'Settings and Trash', run: function () { if ($('#ed').classList.contains('show')) window.Ed.close(); CB.go('settings'); }},
      {name: 'Help and shortcuts', run: help}];
    if($('#ed').classList.contains('show'))items.unshift({name:'Import image as texture',run:function(){window.Ed.importImage();}});
    if(window.Toolbox)Toolbox.tools.forEach(function(tool){items.push({name:tool[1],run:function(){Toolbox.open(tool[0]);}});});
    CB.D.projects.slice().sort(function (a, b) { return b.edited - a.edited; }).forEach(function (p) { items.push({name: 'Open ' + p.name, run: function () { window.Ed.open(p).catch(function (error) { CB.toast(error.message); }); }}); });
    AppDialog.open({title: 'Quick actions', accept: 'Close', noCancel: true, html: '<input class="command-search" id="commandSearch" type="search" autocomplete="off" placeholder="Find an action or project…" aria-label="Search actions and projects"><div id="commandResults"></div>'});
    function render() {
      var query = $('#commandSearch').value.toLowerCase(), found = items.map(function (item, index) { return {item: item, index: index}; }).filter(function (entry) { return entry.item.name.toLowerCase().includes(query); }).slice(0, 12);
      $('#commandResults').innerHTML = found.map(function (entry) { return '<button type="button" class="command-item" data-command="' + entry.index + '">' + CB.esc(entry.item.name) + '<span aria-hidden="true">↵</span></button>'; }).join('') || '<p class="mu">No matching actions or projects.</p>';
    }
    $('#commandSearch').oninput = render;
    $('#commandSearch').onkeydown = function (event) { if (event.key === 'ArrowDown') { event.preventDefault(); var first = $('#commandResults button'); if (first) first.focus(); } else if (event.key === 'Enter') { var first = $('#commandResults button'); if (first) first.click(); } };
    $('#commandResults').onclick = function (event) { var button = event.target.closest('[data-command]'); if (button) { AppDialog.close(null); items[Number(button.dataset.command)].run(); } };
    render(); $('#commandSearch').focus();
  }
  $('#appHelp').onclick = help;
  $('#canvasHelp').onclick = help;
  document.addEventListener('keydown', function (event) {
    if (event.defaultPrevented || event.isComposing || document.querySelector('dialog[open]') || $('#modal').classList.contains('show') || !document.body.classList.contains('inapp') || document.querySelector('#colorChooser:not([hidden])')) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); commands(); }
    if (event.key === 'F1' || event.key === '?' && !event.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])')) { event.preventDefault(); help(); }
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 's' && !event.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])')) {event.preventDefault();CB.save();LocalStore.flush();}
    if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === 'o') {event.preventDefault();if(!event.repeat){$('#packImport').value='';$('#packImport').click();}}
    if ((event.ctrlKey || event.metaKey) && event.altKey && event.key.toLowerCase() === 'n') {event.preventDefault();if(!event.repeat)CB.newProject({type:'pack'});}
  });
  var drops = 0;
  function hasFiles(event) { return event.dataTransfer && Array.from(event.dataTransfer.types).includes('Files'); }
  document.addEventListener('dragenter', function (event) { if (hasFiles(event)&&!document.querySelector('dialog[open]')) { drops++; $('#dropZone').hidden = false; $('#dropZone').querySelector('span').textContent=$('#ed').classList.contains('show')?'Drop an image to preview it as the open texture':'Java ZIP / Bedrock .mcpack · skin PNG · workspace backup'; } });
  document.addEventListener('dragleave', function (event) { if (hasFiles(event) && --drops <= 0) { drops = 0; $('#dropZone').hidden = true; } });
  document.addEventListener('dragover', function (event) { if (hasFiles(event)) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } });
  document.addEventListener('drop', function (event) {
    if (!hasFiles(event)) return; event.preventDefault(); drops = 0; $('#dropZone').hidden = true;
    if (document.querySelector('dialog[open]') || $('#modal').classList.contains('show')) { CB.toast('Close the current dialog before importing files.'); return; }
    var files = Array.from(event.dataTransfer.files); if (files.length !== 1) { CB.toast('Drop one pack, skin, or workspace backup at a time.'); return; }
    var file = files[0]; if (/\.cubeon\.zip$/i.test(file.name)) Workspace.importBackup(file);
    else if (/\.(zip|mcpack)$/i.test(file.name)) ResourcePacks.importFile(file).catch(function () {});
    else if ($('#ed').classList.contains('show')&&(/\.(png|jpe?g|webp)$/i.test(file.name)||/^image\/(png|jpeg|webp)$/.test(file.type)))window.Ed.importImage(file);
    else if (/\.png$/i.test(file.name)) Workspace.importSkin(file);
    else if (/\.(jpe?g|webp)$/i.test(file.name))CB.toast('Open a project and select a texture, then use Import image or drop it on the canvas.');
    else CB.toast('Choose a Java ZIP, Bedrock .mcpack, skin PNG, or .cubeon.zip workspace backup.');
  });
  CB.ready.then(function () { connection(); installState(); prepareOffline(); }, function () {});
  window.AppShell = {prepareOffline: prepareOffline, help: help, commands: commands};
})();
