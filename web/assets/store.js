/* The website and launcher browse the same public catalog. Local artwork is a
   checksum-matched, larger preview; new uploads work with API thumbnails too. */
(function () {
  'use strict';
  var grid = document.getElementById('storeGrid');
  if (!grid) return;
  var status = document.getElementById('storeStatus');
  var empty = document.getElementById('storeEmpty');
  var search = document.getElementById('storeSearch');
  var buttons = document.querySelectorAll('[data-store-kind]');
  var dialog = document.getElementById('storeDialog');
  var kinds = {cape: 'Capes', pet: 'Pets', wing: 'Wings', head: 'Headwear', feet: 'Footwear'};
  var library = {cape: 'Cape', pet: 'Pets', wing: 'Back', head: 'Head', feet: 'Feet'};
  var selected = 'all';
  var known = new Map();
  Array.from(grid.children).forEach(function (card) {
    known.set(card.dataset.id + ':' + card.dataset.sha, card);
  });

  function filter() {
    var term = search.value.trim().toLowerCase();
    var shown = 0;
    Array.from(grid.children).forEach(function (card) {
      var match = (selected === 'all' || card.dataset.kind === selected) &&
        (card.dataset.name + ' ' + card.dataset.description).toLowerCase().includes(term);
      card.hidden = !match;
      shown += match ? 1 : 0;
    });
    empty.hidden = shown !== 0;
    document.getElementById('storeCount').textContent = shown +
      (shown === 1 ? ' cosmetic' : ' cosmetics');
  }
  buttons.forEach(function (button) {
    button.addEventListener('click', function () {
      selected = button.dataset.storeKind;
      buttons.forEach(function (other) {
        other.setAttribute('aria-pressed', String(other === button));
      });
      filter();
    });
  });
  search.addEventListener('input', filter);
  document.getElementById('storeTools').hidden = false;

  grid.addEventListener('click', function (event) {
    var button = event.target.closest('.store-view');
    if (!button) return;
    var card = button.closest('.store-card');
    var image = card.querySelector('img');
    document.getElementById('storeDialogImage').src = image.src;
    document.getElementById('storeDialogImage').alt = image.alt;
    document.getElementById('storeDialogTitle').textContent = card.dataset.name;
    document.getElementById('storeDialogDescription').textContent = card.dataset.description;
    document.getElementById('storeDialogKind').textContent = kinds[card.dataset.kind] + ' / Free';
    document.getElementById('storeDialogEquip').textContent =
      'In Cubeon, open Cosmetics → Store, download ' + card.dataset.name +
      ', then equip it in ' + library[card.dataset.kind] + '.';
    dialog.showModal();
  });
  document.getElementById('storeDialogClose').addEventListener('click', function () { dialog.close(); });
  dialog.addEventListener('click', function (event) {
    if (event.target === dialog) {
      var bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right ||
          event.clientY < bounds.top || event.clientY > bounds.bottom) dialog.close();
    }
  });

  function valid(item) {
    return item && typeof item.id === 'string' && /^[a-z][a-z0-9_-]{2,63}$/.test(item.id) &&
      Object.prototype.hasOwnProperty.call(kinds, item.kind) &&
      typeof item.name === 'string' && item.name.trim().length > 0 && item.name.length <= 80 &&
      typeof item.description === 'string' && item.description.length <= 400 &&
      typeof item.sha256 === 'string' && /^[a-f0-9]{64}$/.test(item.sha256) &&
      typeof item.preview_png === 'string' && item.preview_png.length <= 32768 &&
      /^[A-Za-z0-9+/]+={0,2}$/.test(item.preview_png);
  }
  function makeCard(item) {
    var existing = known.get(item.id + ':' + item.sha256);
    var card = existing ? existing.cloneNode(true) : document.getElementById('storeCardTemplate').content.firstElementChild.cloneNode(true);
    card.dataset.id = item.id;
    card.dataset.sha = item.sha256;
    card.dataset.name = item.name;
    card.dataset.description = item.description;
    card.dataset.kind = item.kind;
    card.querySelector('h2').textContent = item.name;
    card.querySelector('p').textContent = item.description;
    card.querySelector('.store-kind').textContent = kinds[item.kind];
    card.querySelector('.store-view').setAttribute('aria-label', 'View ' + item.name);
    var image = card.querySelector('img');
    image.alt = item.name + ' on a Minecraft character';
    if (!existing) image.src = 'data:image/png;base64,' + item.preview_png;
    card.hidden = false;
    return card;
  }

  async function refresh() {
    var items = [], ids = new Set();
    var controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, 20000);
    try {
      for (var offset = 0; offset < 600; offset += 12) {
        var response = await fetch('/api/cosmetics?kind=all&models=2&offset=' + offset,
          {headers: {Accept: 'application/json'}, signal: controller.signal});
        if (!response.ok) throw new Error('catalog_unavailable');
        var page = await response.json();
        if (page.schema !== 1 || page.offset !== offset || page.page_size !== 12 ||
            typeof page.has_more !== 'boolean' || !Array.isArray(page.items) || page.items.length > 12)
          throw new Error('invalid_catalog');
        page.items.forEach(function (item) {
          if (!valid(item) || ids.has(item.id)) throw new Error('invalid_cosmetic');
          ids.add(item.id);
          items.push(item);
        });
        if (!page.has_more) break;
        if (offset === 588) throw new Error('catalog_too_large');
      }
      items.sort(function (a, b) { return a.name.localeCompare(b.name); });
      var fragment = document.createDocumentFragment();
      items.forEach(function (item) { fragment.appendChild(makeCard(item)); });
      grid.replaceChildren(fragment);
      status.textContent = 'Available in Cubeon. All cosmetics are free.';
      filter();
    } catch (_) {
      status.textContent = 'Browse the collection below. Open Cubeon for the latest availability.';
    } finally {
      clearTimeout(timeout);
    }
  }
  filter();
  refresh();
})();
